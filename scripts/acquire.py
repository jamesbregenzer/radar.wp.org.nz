#!/usr/bin/env python3
"""Acquire approved Radar V2 sources into one canonical observation set."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TRAC_REGISTRY = ROOT / "config/core-trac-v2-source-registry.json"
WAVE2_CONFIG = ROOT / "config/wave2-sources.json"
DEFAULT_RAW_ROOT = ROOT / "data/raw"
DEFAULT_DOWNLOADS = ROOT / "data/downloads"
FIREFOX_PROFILE = ROOT / "data/.firefox-profile"
PRIMARY_ROLES = {"DIRECT_OPPORTUNITY", "SIGNAL", "RECONCILIATION"}
CSV_NAME = re.compile(r"^(?:query|report_[0-9]+)(?: \([0-9]+\))?\.csv$")
DEFAULT_TIMEOUT = 90
REQUIRED_CSV_FIELDS = {"id", "summary", "status", "keywords"}
OPTIONAL_CSV_FIELDS = {"component", "owner", "type", "priority", "milestone", "version", "time", "changetime", "comments", "_comments"}
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
    "keywords": "keywords", "workflow": "keywords",
    "time": "time", "created": "time", "_created": "time",
    "changetime": "changetime", "modified": "changetime",
    "comments": "comments",
    "_comments": "_comments",
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
def wait_for_new_csv(downloads: Path, before: dict[Path, tuple[int, int]], timeout: int = DEFAULT_TIMEOUT) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidate = new_csv_file(before, downloads)
        if candidate and not download_is_incomplete(candidate) and candidate.stat().st_size > 0:
            size = candidate.stat().st_size; time.sleep(0.2)
            if candidate.exists() and candidate.stat().st_size == size: return candidate
        time.sleep(0.2)
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
    ]) + "\n"
    (profile / "user.js").write_text(prefs, encoding="utf-8")

def open_firefox(url: str, browser: str = "Firefox") -> None:
    prepare_firefox_profile()
    subprocess.run(["open", "-n", "-a", browser, "--args", "-no-remote", "-profile", str(FIREFOX_PROFILE), url], check=True)
def close_firefox(browser: str = "Firefox") -> None:
    subprocess.run(["osascript", "-e", f'tell application "{browser}" to quit'], check=False)
def normalize_csv_header(header: str) -> str | None:
    return CSV_FIELD_ALIASES.get(header.lstrip("\ufeff").strip().casefold())


def validate_csv(body: bytes, expected_fields: list[str]) -> tuple[int, list[dict[str, str]]]:
    if not body.strip(): raise ValueError("acquired CSV is empty")
    try:
        reader = csv.DictReader(body.decode("utf-8-sig").splitlines(), strict=True)
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
                if field and field not in row:
                    row[field] = value
            for field in expected_fields:
                row.setdefault(field, "")
            rows.append(row)
        if any(not str(row.get("id") or "").strip() for row in rows): raise ValueError("acquired CSV has a row without a ticket id")
        return len(rows), [dict(row) for row in rows]
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"acquired CSV is unreadable: {error}") from error

def make_observation(source: dict[str, Any], observed_at: str, *, rows: list[dict[str, Any]], result: str, revision: str | None, raw_artifacts: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    record = {"schema": "radar-observation.v2", "version": 2, "sourceId": source["id"], "sourceFamily": source.get("sourceFamily", "CORE_TRAC"), "sourceRole": source.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": source.get("semanticMeaning", "Public source observation."), "candidateFamilyMappings": source.get("candidateFamilyMappings", []), "identityField": source.get("identityField"), "resourceType": source.get("resourceType", "PUBLIC_RESOURCE"), "exactUpstreamUrl": source.get("csvUrl") or source.get("authoritativeSource"), "observedAt": observed_at, "sourceRevision": revision, "acquisitionResult": result, "rows": rows, "rawArtifacts": raw_artifacts}
    if source.get("semanticValidation") is not None: record["semanticValidation"] = source["semanticValidation"]
    if error: record["error"] = error
    return record

def acquire_core_trac(source: dict[str, Any], run_dir: Path, observed_at: str, downloads: Path, timeout: int, *, opener: Callable[[str], None] = open_firefox, waiter: Callable[[Path, dict[Path, tuple[int, int]], int], Path] = wait_for_new_csv, closer: Callable[[], None] = close_firefox) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True); before = download_state(downloads)
    try:
        opener(source["csvUrl"]); downloaded = waiter(downloads, before, timeout); body = downloaded.read_bytes()
        row_count, rows = validate_csv(body, list(source.get("expectedFields") or [])); artifact = run_dir / f"{source_slug(source['id'])}.csv"; artifact.write_bytes(body); sha = sha256_bytes(body)
        artifact_path = str(artifact.relative_to(ROOT)) if artifact.is_relative_to(ROOT) else artifact.name
        return make_observation(source, observed_at, rows=rows, result="success", revision=sha, raw_artifacts=[{"path": artifact_path, "sha256": sha, "byteLength": len(body), "contentType": "text/csv", "rowCount": row_count}])
    except Exception as error:
        return make_observation(source, observed_at, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}")
    finally: closer()

def fetch_wave2_source(config: dict[str, Any]) -> list[tuple[str, bytes, dict[str, str], int]]:
    from wave2_sources import configured_responses, fetch_public
    return configured_responses(config, fetch_public)

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

def acquire_wave2(config: dict[str, Any], run_dir: Path, observed_at: str, *, fetcher: Callable[[dict[str, Any]], list[tuple[str, bytes, dict[str, str], int]]] = fetch_wave2_source) -> dict[str, Any]:
    from wave2_sources import normalize_resources
    run_dir.mkdir(parents=True, exist_ok=True); responses = fetcher(config)
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
    return make_observation(source, observed_at, rows=rows, result="success", revision=sha256_bytes(json.dumps(resources, sort_keys=True).encode()), raw_artifacts=raw_artifacts)

def acquire_run(*, raw_root: Path = DEFAULT_RAW_ROOT, observed_at: str | None = None, downloads: Path | None = None, timeout: int = DEFAULT_TIMEOUT, trac_sources: list[dict[str, Any]] | None = None, wave2_sources: list[dict[str, Any]] | None = None, trac_acquirer: Callable[..., dict[str, Any]] = acquire_core_trac, wave2_acquirer: Callable[..., dict[str, Any]] = acquire_wave2) -> dict[str, Any]:
    observed = observed_at or utc_now(); run_dir = raw_root / run_slug(observed); run_dir.mkdir(parents=True, exist_ok=True); downloads_path = downloads or DEFAULT_DOWNLOADS
    trac_sources = trac_sources if trac_sources is not None else primary_core_trac_sources(); wave2_sources = wave2_sources if wave2_sources is not None else load_json(WAVE2_CONFIG).get("sources", []); observations = []
    for source in trac_sources: observations.append(trac_acquirer(source, run_dir, observed, downloads_path, timeout))
    for source in wave2_sources:
        try: observations.append(wave2_acquirer(source, run_dir, observed))
        except Exception as error:
            fallback = {"id": source["sourceFamily"], "sourceFamily": source["sourceFamily"], "sourceRole": source.get("sourceRole", "DIRECT_OPPORTUNITY"), "semanticMeaning": source.get("semanticMeaning", source.get("label", "Public source observation.")), "authoritativeSource": source.get("authoritativeSource")}
            observations.append(make_observation(fallback, observed, rows=[], result="failed", revision=None, raw_artifacts=[], error=f"{type(error).__name__}: {error}"))
    manifest = {"schema": "radar-observation-set.v2", "version": 2, "runId": run_slug(observed), "observedAt": observed, "observations": observations}; manifest["success"] = any(item["acquisitionResult"] == "success" for item in observations); write_json(run_dir / "run.json", manifest); return manifest

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT); parser.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS); parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT); args = parser.parse_args(); manifest = acquire_run(raw_root=args.raw_root, downloads=args.downloads, timeout=args.timeout); print(json.dumps(manifest, indent=2, sort_keys=True)); return 0 if manifest["success"] else 1
if __name__ == "__main__": raise SystemExit(main())
