#!/usr/bin/env python3
"""Acquire the approved Radar V2 source artifacts into one immutable raw run."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TRAC_REGISTRY = ROOT / "config" / "core-trac-v2-source-registry.json"
WAVE2_CONFIG = ROOT / "config" / "wave2-sources.json"
DEFAULT_RAW_ROOT = ROOT / "data" / "raw"
PRIMARY_ROLES = {"DIRECT_OPPORTUNITY", "SIGNAL", "RECONCILIATION"}
CSV_NAME = re.compile(r"^(?:query|report_[0-9]+)\.csv$")
DEFAULT_TIMEOUT = 90


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


def primary_core_trac_sources(registry_path: Path = TRAC_REGISTRY) -> list[dict[str, Any]]:
    registry = load_json(registry_path)
    if registry.get("schema") != "radar-core-trac-source-registry.v2":
        raise ValueError("unsupported Core Trac source registry schema")
    return [source for source in registry.get("sources", []) if source.get("sourceRole") in PRIMARY_ROLES]


def snapshot_downloads(downloads: Path) -> dict[Path, tuple[int, int]]:
    if not downloads.exists():
        return {}
    return {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in downloads.iterdir()
        if path.is_file() and CSV_NAME.fullmatch(path.name)
    }


def new_csv_file(before: dict[Path, tuple[int, int]], downloads: Path) -> Path | None:
    candidates = []
    for path, state in snapshot_downloads(downloads).items():
        if path not in before or before[path] != state:
            candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None


def wait_for_new_csv(downloads: Path, before: dict[Path, tuple[int, int]], timeout: int = DEFAULT_TIMEOUT) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidate = new_csv_file(before, downloads)
        if candidate and candidate.stat().st_size > 0:
            size = candidate.stat().st_size
            time.sleep(0.2)
            if candidate.exists() and candidate.stat().st_size == size:
                return candidate
        time.sleep(0.2)
    raise TimeoutError("Firefox did not create a new query.csv or report_N.csv")


def open_firefox(url: str, browser: str = "Firefox") -> None:
    subprocess.run(["open", "-n", "-a", browser, "--args", url], check=True)


def close_firefox(browser: str = "Firefox") -> None:
    subprocess.run(["osascript", "-e", f'tell application "{browser}" to quit'], check=False)


def validate_csv(body: bytes, expected_fields: list[str]) -> int:
    if not body.strip():
        raise ValueError("acquired CSV is empty")
    try:
        text = body.decode("utf-8-sig")
        reader = csv.DictReader(text.splitlines(), strict=True)
        fields = reader.fieldnames or []
        missing = [field for field in expected_fields if field not in fields]
        if missing:
            raise ValueError(f"acquired CSV is missing expected fields: {', '.join(missing)}")
        rows = 0
        for row in reader:
            if None in row:
                raise ValueError("acquired CSV has a row with the wrong number of fields")
            rows += 1
        return rows
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"acquired CSV is unreadable: {error}") from error


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_record(source_id: str, url: str, observed_at: str, artifact: Path, body: bytes, *, row_count: int | None = None, http_status: int | None = None) -> dict[str, Any]:
    record = {
        "sourceId": source_id,
        "exactUrl": url,
        "observedAt": observed_at,
        "success": True,
        "artifact": artifact.name,
        "artifactSha256": sha256_bytes(body),
        "byteLength": len(body),
    }
    if row_count is not None:
        record["rowCount"] = row_count
    if http_status is not None:
        record["httpStatus"] = http_status
    return record


def failure_record(source_id: str, url: str, observed_at: str, error: Exception) -> dict[str, Any]:
    return {"sourceId": source_id, "exactUrl": url, "observedAt": observed_at, "success": False, "error": f"{type(error).__name__}: {error}"}


def acquire_core_trac(source: dict[str, Any], run_dir: Path, observed_at: str, downloads: Path, timeout: int, *, opener: Callable[[str], None] = open_firefox, waiter: Callable[[Path, dict[Path, tuple[int, int]], int], Path] = wait_for_new_csv, closer: Callable[[], None] = close_firefox) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    before = snapshot_downloads(downloads)
    opener(source["csvUrl"])
    try:
        downloaded = waiter(downloads, before, timeout)
        body = downloaded.read_bytes()
        row_count = validate_csv(body, list(source.get("expectedFields") or []))
        artifact = run_dir / f"{source_slug(source['id'])}.csv"
        artifact.write_bytes(body)
        record = artifact_record(source["id"], source["csvUrl"], observed_at, artifact, body, row_count=row_count)
        write_json(run_dir / f"{source_slug(source['id'])}.json", record)
        return record
    finally:
        closer()


def fetch_wave2_source(config: dict[str, Any]) -> list[tuple[str, bytes, dict[str, str], int]]:
    from wave2_sources import configured_responses, fetch_public

    return configured_responses(config, fetch_public)


def acquire_wave2(config: dict[str, Any], run_dir: Path, observed_at: str, *, fetcher: Callable[[dict[str, Any]], list[tuple[str, bytes, dict[str, str], int]] ] = fetch_wave2_source) -> list[dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    responses = fetcher(config)
    if not responses:
        raise ValueError("source has no configured response endpoints")
    records = []
    slug = source_slug(config["sourceFamily"])
    for index, (url, body, _headers, status) in enumerate(responses, start=1):
        if status != 200:
            raise ValueError(f"HTTP {status} from {url}")
        suffix = "" if len(responses) == 1 else f"-{index:03d}"
        artifact = run_dir / f"{slug}{suffix}.raw.json"
        artifact.write_bytes(body)
        records.append(artifact_record(config["sourceFamily"], url, observed_at, artifact, body, http_status=status))
    write_json(run_dir / f"{slug}.json", {"sourceId": config["sourceFamily"], "observedAt": observed_at, "success": True, "artifacts": records})
    return records


def acquire_run(*, raw_root: Path = DEFAULT_RAW_ROOT, observed_at: str | None = None, downloads: Path | None = None, timeout: int = DEFAULT_TIMEOUT, trac_sources: list[dict[str, Any]] | None = None, wave2_sources: list[dict[str, Any]] | None = None, trac_acquirer: Callable[..., dict[str, Any]] = acquire_core_trac, wave2_acquirer: Callable[..., list[dict[str, Any]]] = acquire_wave2) -> dict[str, Any]:
    observed = observed_at or utc_now()
    run_dir = raw_root / run_slug(observed)
    run_dir.mkdir(parents=True, exist_ok=True)
    downloads_path = downloads or (Path.home() / "Downloads")
    trac_sources = trac_sources if trac_sources is not None else primary_core_trac_sources()
    if wave2_sources is None:
        wave2_sources = load_json(WAVE2_CONFIG).get("sources", [])
    results: list[dict[str, Any]] = []
    for source in trac_sources:
        try:
            results.append(trac_acquirer(source, run_dir, observed, downloads_path, timeout))
        except Exception as error:
            results.append(failure_record(source["id"], source["csvUrl"], observed, error))
    for source in wave2_sources:
        try:
            artifacts = wave2_acquirer(source, run_dir, observed)
            results.append({"sourceId": source["sourceFamily"], "exactUrl": source.get("authoritativeSource"), "observedAt": observed, "success": True, "artifacts": artifacts})
        except Exception as error:
            results.append(failure_record(source["sourceFamily"], source.get("authoritativeSource", ""), observed, error))
    manifest = {"schema": "radar.raw-acquisition-run.v1", "version": 1, "runId": run_slug(observed), "observedAt": observed, "success": all(item["success"] for item in results), "results": results}
    write_json(run_dir / "run.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    manifest = acquire_run(raw_root=args.raw_root, downloads=args.downloads, timeout=args.timeout)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
