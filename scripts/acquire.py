#!/usr/bin/env python3
"""Acquire approved Radar V2 sources into one canonical observation set."""
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, re, shlex, signal, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TRAC_REGISTRY = ROOT / "config/core-trac-v2-source-registry.json"
WAVE2_CONFIG = ROOT / "config/wave2-sources.json"
DEFAULT_RAW_ROOT = ROOT / "data/raw"
DEFAULT_DOWNLOADS = ROOT / "data/downloads"
FIREFOX_PROFILE = ROOT / "data/.firefox-profile"
FIREFOX_EXECUTABLE = Path("/Applications/Firefox.app/Contents/MacOS/firefox")
PRIMARY_ROLES = {"DIRECT_OPPORTUNITY", "SIGNAL", "RECONCILIATION"}
CSV_NAME = re.compile(r"^(?:query|report_[0-9]+)(?:\s*\([0-9]+\))?\.csv$")
DEFAULT_TIMEOUT = 90
DEFAULT_RUN_TIMEOUT = 45 * 60
CORE_TRAC_RETRY_DELAY = 1
FIREFOX_STOP_TIMEOUT = 15
FIREFOX_PROFILE_WAIT_TIMEOUT = 5
REQUIRED_CSV_FIELDS = {"id", "summary", "status"}
OPTIONAL_CSV_FIELDS = {"keywords", "workflow", "component", "owner", "type", "priority", "milestone", "version", "time", "changetime", "comments", "_comments", "description"}
CSV_FIELD_ALIASES = {
    "id": "id", "ticket": "id",
    "summary": "summary",
    "status": "status", "_status": "status",
    "component": "component",
    "owner": "owner",
    "type": "type",
    "priority": "priority", "_priority": "priority",
    "milestone": "milestone",
    "version": "version", "_version": "version",
    "keywords": "keywords", "workflow": "workflow",
    "time": "time", "created": "time", "_created": "time",
    "changetime": "changetime", "modified": "changetime",
    "comments": "comments",
    "_comments": "_comments",
    "description": "description", "_description": "description",
}

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
def source_slug(source_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", source_id.lower()).strip("-")
def run_slug(observed_at: str) -> str:
    return observed_at.replace(":", "-").replace("+00:00", "Z")
def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def primary_core_trac_sources(registry_path: Path = TRAC_REGISTRY) -> list[dict[str, Any]]:
    registry = load_json(registry_path)
    if registry.get("schema") != "radar-core-trac-source-registry.v2": raise ValueError("unsupported Core Trac source registry schema")
    return [source for source in registry.get("sources", []) if source.get("sourceRole") in PRIMARY_ROLES]
def download_state(downloads: Path) -> dict[Path, tuple[int, int]]:
    if not downloads.exists(): return {}
    return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in downloads.iterdir() if p.is_file() and CSV_NAME.fullmatch(p.name)}
def new_csv_file(before: dict[Path, tuple[int, int]], downloads: Path) -> Path | None:
    candidates = [p for p, state in download_state(downloads).items() if p not in before or before[p] != state]
    return max(candidates, key=lambda p: p.stat().st_mtime_ns) if candidates else None

def download_is_incomplete(path: Path) -> bool:
    return any(path.with_name(path.name + suffix).exists() for suffix in (".part", ".download"))
def wait_for_new_csv(downloads: Path, before: dict[Path, tuple[int, int]], timeout: float = DEFAULT_TIMEOUT, *, clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> Path:
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    while clock() < deadline:
        candidate = new_csv_file(before, downloads)
        if candidate and not download_is_incomplete(candidate) and candidate.stat().st_size > 0:
            size = candidate.stat().st_size; sleep(0.2)
            if candidate.exists() and candidate.stat().st_size == size: return candidate
        sleep(0.2)
    raise TimeoutError("Firefox did not create a new query.csv or report_N.csv")
def prepare_firefox_profile(downloads: Path = DEFAULT_DOWNLOADS, profile: Path = FIREFOX_PROFILE) -> None:
    downloads.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    prefs = "\n".join([
        f'user_pref("browser.download.dir", {json.dumps(str(downloads))});',
        'user_pref("browser.download.folderList", 2);',
        'user_pref("browser.download.useDownloadDir", true);',
        'user_pref("browser.download.always_ask_before_handling_new_types", false);',
        'user_pref("browser.helperApps.alwaysAsk.force", false);',
        'user_pref("browser.helperApps.neverAsk.saveToDisk", "text/csv,application/csv,application/octet-stream");',
        'user_pref("browser.sessionstore.resume_from_crash", false);',
        'user_pref("browser.startup.couldRestoreSession.count", -1);',
        'user_pref("browser.sessionstore.max_resumed_crashes", -1);',
        'user_pref("browser.shell.checkDefaultBrowser", false);',
    ]) + "\n"
    (profile / "user.js").write_text(prefs, encoding="utf-8")

def firefox_command(url: str, profile: Path = FIREFOX_PROFILE) -> list[str]:
    return [str(FIREFOX_EXECUTABLE), "-no-remote", "-profile", str(profile), url]

class FirefoxSession:
    def __init__(self, launcher: subprocess.Popen, profile: Path = FIREFOX_PROFILE) -> None:
        self.launcher = launcher
        self.profile = profile
        self.graceful_quit_count = 0
        self.emergency_kill_used = False

def radar_firefox_pids(profile: Path = FIREFOX_PROFILE) -> list[int]:
    result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("cannot verify processes using the Radar Firefox profile")
    rows: dict[int, tuple[int, str]] = {}
    profile_processes: set[int] = set()
    for line in result.stdout.splitlines():
        try:
            fields = line.strip().split(None, 1)
            pid = int(fields[0])
            command = fields[1]
            argv = shlex.split(command)
        except (IndexError, ValueError):
            continue
        profile_args = [argv[index + 1] for index, argument in enumerate(argv[:-1]) if argument == "-profile"]
        parent = 0
        parent_match = re.search(r"-parentPid (\d+)", command)
        if parent_match:
            parent = int(parent_match.group(1))
        rows[pid] = (parent, command)
        if str(profile) in profile_args:
            profile_processes.add(pid)
    pids = set()
    for pid in profile_processes:
        _parent, command = rows[pid]
        candidate = pid
        while candidate in rows and str(FIREFOX_EXECUTABLE) not in rows[candidate][1]:
            candidate = rows[candidate][0]
        if candidate in rows and str(FIREFOX_EXECUTABLE) in rows[candidate][1] and candidate != os.getpid():
            pids.add(candidate)
    return sorted(pids)

def ensure_firefox_profile_available(profile: Path = FIREFOX_PROFILE, timeout: float = FIREFOX_PROFILE_WAIT_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while True:
        pids = radar_firefox_pids(profile)
        if not pids:
            for name in ("parent.lock", "lock"):
                lock = profile / name
                if os.path.lexists(lock):
                    lock.unlink()
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Radar Firefox profile is still held by process(es): {', '.join(map(str, pids))}")
        time.sleep(0.1)

def navigate_firefox(url: str, profile: Path = FIREFOX_PROFILE, *, timeout: float | None = None) -> None:
    subprocess.run([str(FIREFOX_EXECUTABLE), "-profile", str(profile), url], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)

def open_firefox(url: str, *, downloads: Path = DEFAULT_DOWNLOADS, profile: Path = FIREFOX_PROFILE) -> FirefoxSession:
    prepare_firefox_profile(downloads, profile)
    ensure_firefox_profile_available(profile)
    launcher = subprocess.Popen(firefox_command(url, profile), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return FirefoxSession(launcher, profile)

def close_firefox(session: FirefoxSession | None = None, *, profile: Path = FIREFOX_PROFILE) -> None:
    if session is None:
        ensure_firefox_profile_available(profile)
        return
    owned_pids = radar_firefox_pids(session.profile)
    if not owned_pids:
        ensure_firefox_profile_available(profile)
        return
    for pid in owned_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    session.graceful_quit_count += 1
    deadline = time.monotonic() + FIREFOX_STOP_TIMEOUT
    while radar_firefox_pids(session.profile) and time.monotonic() < deadline:
        time.sleep(0.25)
    remaining = radar_firefox_pids(session.profile)
    if remaining:
        session.emergency_kill_used = True
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    ensure_firefox_profile_available(profile)
def normalize_csv_header(header: str) -> str | None:
    return CSV_FIELD_ALIASES.get(header.lstrip("\ufeff").strip().casefold())


def validate_csv(body: bytes, expected_fields: list[str]) -> tuple[int, list[dict[str, str]]]:
    if not body.strip(): raise ValueError("acquired CSV is empty")
    try:
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""), strict=True)
        headers = reader.fieldnames or []
        normalized_headers = [normalize_csv_header(header) for header in headers]
        available = {field for field in normalized_headers if field}
        missing = [field for field in expected_fields if field not in available and field not in OPTIONAL_CSV_FIELDS]
        missing_required = [field for field in expected_fields if field in REQUIRED_CSV_FIELDS and field not in available]
        if missing_required:
            missing.extend(missing_required)
        if missing: raise ValueError(f"acquired CSV is missing expected fields: {', '.join(missing)}")
        rows = []
        for raw_row in reader:
            if None in raw_row: raise ValueError("acquired CSV has a row with the wrong number of fields")
            row: dict[str, str] = {}
            for header, value in raw_row.items():
                field = normalize_csv_header(header)
                if field == "description" and not isinstance(value, str):
                    raise ValueError("acquired CSV has a missing description column")
                if field == "description" and field in row:
                    if row[field] == value or value == "":
                        continue
                    if row[field] == "":
                        row[field] = value
                        continue
                    raise ValueError("acquired CSV has conflicting description columns")
                if field and field not in row:
                    row[field] = value
            rows.append(row)
        if any(not str(row.get("id") or "").strip() for row in rows): raise ValueError("acquired CSV has a row without a ticket id")
        return len(rows), [dict(row) for row in rows]
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"acquired CSV is unreadable: {error}") from error

def rows_for_observation(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep full descriptions in the verified raw CSV, not a second run copy."""
    return [{key: value for key, value in row.items() if key != "description"} for row in rows]

def make_observation(source: dict[str, Any], observed_at: str, *, rows: list[dict[str, Any]], result: str, revision: str | None, raw_artifacts: list[dict[str, Any]], error: str | None = None, diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {"schema": "radar-observation.v2", "version": 2, "sourceId": source["id"], "sourceFamily": source.get("sourceFamily", "CORE_TRAC"), "sourceRole": source.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": source.get("semanticMeaning", "Public source observation."), "candidateFamilyMappings": source.get("candidateFamilyMappings", []), "identityField": source.get("identityField"), "resourceType": source.get("resourceType", "PUBLIC_RESOURCE"), "exactUpstreamUrl": source.get("csvUrl") or source.get("authoritativeSource"), "observedAt": observed_at, "sourceRevision": revision, "acquisitionResult": result, "rows": rows, "rawArtifacts": raw_artifacts}
    if source.get("semanticValidation") is not None: record["semanticValidation"] = source["semanticValidation"]
    if error: record["error"] = error
    if diagnostics: record["acquisitionDiagnostics"] = diagnostics
    return record

def acquire_core_trac(source: dict[str, Any], run_dir: Path, observed_at: str, downloads: Path, timeout: float, *, opener: Callable[[str], Any] = open_firefox, waiter: Callable[..., Path] = wait_for_new_csv, closer: Callable[[Any], None] = close_firefox, session: FirefoxSession | None = None, first_in_session: bool = False, navigator: Callable[..., None] = navigate_firefox, initial_download_state: dict[Path, tuple[int, int]] | None = None, deadline: float | None = None, source_started_at: float | None = None, clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    run_dir.mkdir(parents=True, exist_ok=True)
    source_started_at = clock() if source_started_at is None else source_started_at
    source_deadline = source_started_at + max(0.0, timeout)
    if deadline is not None:
        source_deadline = min(source_deadline, deadline)
    source_budget = max(0.0, source_deadline - source_started_at)
    last_error: Exception | None = None
    last_before: dict[Path, tuple[int, int]] = {}
    attempts_used = 0
    process = None
    for attempt in range(2):
        attempt_deadline = min(source_deadline, source_started_at + source_budget * (attempt + 1) / 2)
        if clock() >= attempt_deadline:
            last_error = TimeoutError("Core Trac source deadline exhausted before attempt")
            break
        attempts_used += 1
        before = initial_download_state if attempt == 0 and first_in_session and initial_download_state is not None else download_state(downloads)
        last_before = before
        retry = False; fatal = False
        process = None
        try:
            if session is None:
                process = opener(source["csvUrl"])
            elif not (first_in_session and attempt == 0):
                navigation_timeout = max(0.0, attempt_deadline - clock())
                navigator(source["csvUrl"], timeout=navigation_timeout)
            wait_timeout = max(0.0, attempt_deadline - clock())
            if wait_timeout <= 0:
                raise TimeoutError("Core Trac attempt deadline exhausted before CSV wait")
            if waiter is wait_for_new_csv:
                downloaded = waiter(downloads, before, wait_timeout, clock=clock, sleep=sleep)
            else:
                downloaded = waiter(downloads, before, wait_timeout)
            if clock() > attempt_deadline:
                raise TimeoutError("Core Trac attempt exceeded its deadline")
            body = downloaded.read_bytes()
            row_count, rows = validate_csv(body, list(source.get("expectedFields") or []))
            if clock() > attempt_deadline:
                raise TimeoutError("Core Trac parsing exceeded its deadline")
            artifact = run_dir / f"{source_slug(source['id'])}.csv"; artifact.write_bytes(body); sha = sha256_bytes(body)
            artifact_path = str(artifact.relative_to(ROOT)) if artifact.is_relative_to(ROOT) else artifact.name
            downloaded.unlink()
            return make_observation(source, observed_at, rows=rows_for_observation(rows), result="success", revision=sha, raw_artifacts=[{"path": artifact_path, "sha256": sha, "byteLength": len(body), "contentType": "text/csv", "rowCount": row_count}])
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            last_error = TimeoutError(f"Core Trac attempt deadline exceeded: {error}")
            retry = attempt == 0 and clock() < source_deadline
        except Exception as error:
            last_error = error; fatal = True
        finally:
            if session is None:
                closer(process)
        if fatal or not retry:
            break
        remaining = max(0.0, source_deadline - clock())
        sleep(min(CORE_TRAC_RETRY_DELAY, remaining * 0.1))
    error = last_error or RuntimeError("Core Trac acquisition failed")
    launcher = session.launcher if session is not None else process
    after = download_state(downloads)
    diagnostics = {
        "matchingCsvCountBefore": len(last_before),
        "matchingCsvCountAfter": len(after),
        "changedMatchingCsvCount": sum(1 for path, state in after.items() if last_before.get(path) != state),
        "incompleteMatchingCsvCount": sum(1 for path in after if download_is_incomplete(path)),
        "firefoxLauncherExitCode": launcher.poll() if launcher is not None else None,
        "attemptsUsed": attempts_used,
        "sourceBudgetSeconds": source_budget,
        "sourceElapsedSeconds": max(0.0, clock() - source_started_at),
        "failureClass": "timeout" if isinstance(error, TimeoutError) else "acquisition_error",
        "humanVerification": "unobserved",
    }
    return make_observation(source, observed_at, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}", diagnostics=diagnostics)

def fetch_wave2_source(config: dict[str, Any], *, deadline: float | None = None, clock: Callable[[], float] = time.monotonic) -> list[tuple[str, bytes, dict[str, str], int]]:
    from wave2_sources import configured_responses, fetch_public
    def fetch_with_budget(url: str) -> tuple[bytes, dict[str, str], int]:
        remaining = 45.0 if deadline is None else deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Radar run deadline exhausted before public source request")
        response = fetch_public(url, timeout=min(45.0, remaining))
        if deadline is not None and clock() > deadline:
            raise TimeoutError("Radar run deadline exceeded during public source request")
        return response
    return configured_responses(config, fetch_with_budget)

def validate_wave2_payload(adapter: str | None, payload: Any, url: str) -> None:
    if adapter in {"wp_rest_posts", "github_issues", "github_repository"}:
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError(f"expected a JSON array of objects from {url}")
        required = "id" if adapter == "wp_rest_posts" else "number"
        if any(required not in item for item in payload):
            raise ValueError(f"response contains an item without {required} from {url}")
    elif adapter == "wp_rest_tree":
        items = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
        if any(not isinstance(item, dict) or "id" not in item for item in items):
            raise ValueError(f"WordPress handbook response contains an item without id from {url}")
    elif adapter == "wordpress_releases" and (not isinstance(payload, dict) or not isinstance(payload.get("offers"), list) or not all(isinstance(item, dict) for item in payload["offers"])):
        raise ValueError(f"WordPress release response has no offers array from {url}")

def acquire_wave2(config: dict[str, Any], run_dir: Path, observed_at: str, *, fetcher: Callable[..., list[tuple[str, bytes, dict[str, str], int]]] = fetch_wave2_source, deadline: float | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    from wave2_sources import normalize_resources
    run_dir.mkdir(parents=True, exist_ok=True)
    if fetcher is fetch_wave2_source:
        responses = fetcher(config, deadline=deadline, clock=clock)
    else:
        responses = fetcher(config)
    if deadline is not None and clock() > deadline:
        raise TimeoutError("Radar run deadline exceeded during public source acquisition")
    if not responses: raise ValueError("source has no configured response endpoints")
    raw_artifacts = []; payloads = []
    for index, (url, body, _headers, status) in enumerate(responses, start=1):
        if status != 200: raise ValueError(f"HTTP {status} from {url}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid JSON from {url}: {error}") from error
        validate_wave2_payload(config.get("adapter"), payload, url)
        suffix = "" if len(responses) == 1 else f"-{index:03d}"; artifact = run_dir / f"{source_slug(config['sourceFamily'])}{suffix}.raw.json"; artifact.write_bytes(body); sha = sha256_bytes(body)
        artifact_path = str(artifact.relative_to(ROOT)) if artifact.is_relative_to(ROOT) else artifact.name
        raw_artifacts.append({"path": artifact_path, "sha256": sha, "byteLength": len(body), "contentType": "application/json", "url": url, "httpStatus": status}); payloads.append((url, body, {}, status))
    resources = normalize_resources(config, payloads, observed_at)
    rows = [{"id": item.get("nativeIdentity"), "title": item.get("title"), "url": item.get("url"), "status": item.get("state") or item.get("status"), "candidateFamilyMappings": [{"familyId": signal["familyId"], "confidence": signal.get("confidence", "medium")} for signal in item.get("candidateSignals", []) if signal.get("state") in {"CLEAR_OPPORTUNITY", "POSSIBLE_OPPORTUNITY"}], "resource": item} for item in resources]
    source = {"id": config["sourceFamily"], "sourceFamily": config["sourceFamily"], "sourceRole": config.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": config.get("semanticMeaning", config.get("label", "Public source observation.")), "candidateFamilyMappings": config.get("candidateFamilyMappings", []), "identityField": "id", "resourceType": "PUBLIC_RESOURCE", "authoritativeSource": config.get("authoritativeSource")}
    if deadline is not None and clock() > deadline:
        raise TimeoutError("Radar run deadline exceeded during public source normalization")
    return make_observation(source, observed_at, rows=rows, result="success", revision=sha256_bytes(json.dumps(resources, sort_keys=True).encode()), raw_artifacts=raw_artifacts)

def source_coverage(configured_sources: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item.get("sourceId"): item for item in observations}
    families: dict[str, list[tuple[str, bool]]] = {}
    for source in configured_sources:
        source_id = str(source.get("id") or source.get("sourceFamily") or "")
        family = str(source.get("sourceFamily") or ("CORE_TRAC" if source.get("csvUrl") else source_id) or "UNKNOWN")
        observation = by_id.get(source_id)
        families.setdefault(family, []).append((source_id, bool(observation and observation.get("acquisitionResult") == "success")))
    summary = {}
    for family, sources in sorted(families.items()):
        succeeded = sum(success for _source_id, success in sources)
        configured = len(sources)
        state = "complete" if configured and succeeded == configured else "unavailable" if configured and succeeded == 0 else "degraded" if configured else "not_configured"
        summary[family] = {
            "state": state,
            "configuredSourceCount": configured,
            "successfulSourceCount": succeeded,
            "failedSourceCount": configured - succeeded,
            "failedSourceIds": sorted(source_id for source_id, success in sources if not success),
        }
    states = [item["state"] for item in summary.values()]
    overall = "not_configured" if not states else "complete" if all(state == "complete" for state in states) else "unavailable" if all(state == "unavailable" for state in states) else "degraded"
    return {"overallState": overall, "families": summary}

def acquire_run(*, raw_root: Path = DEFAULT_RAW_ROOT, observed_at: str | None = None, downloads: Path | None = None, timeout: int = DEFAULT_TIMEOUT, run_timeout: float = DEFAULT_RUN_TIMEOUT, trac_sources: list[dict[str, Any]] | None = None, wave2_sources: list[dict[str, Any]] | None = None, trac_acquirer: Callable[..., dict[str, Any]] = acquire_core_trac, wave2_acquirer: Callable[..., dict[str, Any]] = acquire_wave2, clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Acquire configured sources under one deadline and receipt every unattempted source.

    The budget bounds source acquisition; safe browser cleanup and receipt writing
    still run when the deadline expires.
    """
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    run_started_at = clock()
    run_deadline = run_started_at + max(0.0, run_timeout)
    observed = observed_at or utc_now(); run_dir = raw_root / run_slug(observed); run_dir.mkdir(parents=True, exist_ok=True); downloads_path = downloads or DEFAULT_DOWNLOADS
    trac_sources = trac_sources if trac_sources is not None else primary_core_trac_sources(); wave2_sources = wave2_sources if wave2_sources is not None else load_json(WAVE2_CONFIG).get("sources", []); observations = []
    if trac_acquirer is acquire_core_trac:
        session = None
        initial_download_state = download_state(downloads_path) if trac_sources else None
        try:
            if trac_sources and clock() < run_deadline:
                try:
                    session = open_firefox(trac_sources[0]["csvUrl"], downloads=downloads_path)
                except Exception as error:
                    for source in trac_sources:
                        observations.append(make_observation(source, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}"))
            elif trac_sources:
                for source in trac_sources:
                    observations.append(make_observation(source, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error="TimeoutError: Radar run deadline exhausted before Core Trac acquisition"))
            if session is not None or not trac_sources:
                for index, source in enumerate(trac_sources):
                    source_started_at = clock()
                    if source_started_at >= run_deadline:
                        observations.append(make_observation(source, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error="TimeoutError: Radar run deadline exhausted before Core Trac source"))
                        continue
                    try:
                        source_timeout = min(float(timeout), run_deadline - source_started_at)
                        observations.append(trac_acquirer(source, run_dir, observed, downloads_path, source_timeout, session=session, first_in_session=index == 0, initial_download_state=initial_download_state if index == 0 else None, deadline=run_deadline, source_started_at=source_started_at, clock=clock, sleep=sleep))
                    except Exception as error:
                        observations.append(make_observation(source, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}"))
        finally:
            if session is not None:
                close_firefox(session)
    else:
        for source in trac_sources:
            if clock() >= run_deadline:
                observations.append(make_observation(source, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error="TimeoutError: Radar run deadline exhausted before Core Trac source"))
                continue
            source_timeout = min(float(timeout), run_deadline - clock())
            observations.append(trac_acquirer(source, run_dir, observed, downloads_path, source_timeout))
    for source in wave2_sources:
        if clock() >= run_deadline:
            fallback = {"id": source["sourceFamily"], "sourceFamily": source["sourceFamily"], "sourceRole": source.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": source.get("semanticMeaning", source.get("label", "Public source observation.")), "authoritativeSource": source.get("authoritativeSource")}
            observations.append(make_observation(fallback, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error="TimeoutError: Radar run deadline exhausted before public source"))
            continue
        try:
            if wave2_acquirer is acquire_wave2:
                observations.append(wave2_acquirer(source, run_dir, observed, deadline=run_deadline, clock=clock))
            else:
                observations.append(wave2_acquirer(source, run_dir, observed))
        except Exception as error:
            fallback = {"id": source["sourceFamily"], "sourceFamily": source["sourceFamily"], "sourceRole": source.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": source.get("semanticMeaning", source.get("label", "Public source observation.")), "authoritativeSource": source.get("authoritativeSource")}
            observations.append(make_observation(fallback, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}"))
    configured_sources = [*trac_sources, *wave2_sources]
    manifest = {"schema": "radar-observation-set.v2", "version": 2, "runId": run_slug(observed), "observedAt": observed, "observations": observations}; manifest["success"] = any(item["acquisitionResult"] == "success" for item in observations); manifest["sourceCoverage"] = source_coverage(configured_sources, observations); write_json(run_dir / "run.json", manifest); return manifest

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT); parser.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS); parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT); args = parser.parse_args(); manifest = acquire_run(raw_root=args.raw_root, downloads=args.downloads, timeout=args.timeout); print(json.dumps(manifest, indent=2, sort_keys=True)); return 0 if manifest["success"] else 1
if __name__ == "__main__": raise SystemExit(main())
