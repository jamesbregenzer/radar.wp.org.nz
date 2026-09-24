#!/usr/bin/env python3
"""Generate deterministic Static Assets projections from certified Radar data."""

from __future__ import annotations

import json
from pathlib import Path

from certification import CERTIFIED_CURRENT, canonical_json, file_sha256, verify_certified

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "docs" / "radar" / "api" / "v1"


def generate_api_assets(current_dir: Path = CERTIFIED_CURRENT, output_dir: Path = API_DIR) -> list[Path]:
    verified = verify_certified(current_dir)
    snapshot = json.loads((current_dir / "snapshot.json").read_text(encoding="utf-8"))
    health = {
        "schema": "radar-health.v1",
        "version": 1,
        "status": "healthy",
        "snapshot_id": snapshot["snapshot_id"],
        "collection_id": snapshot["collection_id"],
        "certification_state": snapshot["certification"]["state"],
        "reference_time": snapshot["reference_time"],
        "opportunity_count": snapshot["opportunity_count"],
        "scoring_version": snapshot["scoring_version"],
        "source_revision": snapshot.get("source_revision"),
        "dataset_sha256": snapshot["dataset_sha256"],
        "warnings": snapshot["certification"].get("warnings", []),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("snapshot.json", "collection.json", "opportunities.json", "snapshot.sha256"):
        destination = output_dir / name
        destination.write_bytes((current_dir / name).read_bytes())
        paths.append(destination)
    health_path = output_dir / "health.json"
    health_path.write_bytes(canonical_json(health))
    paths.append(health_path)
    # Verification result is intentionally not published; it only gates output.
    if verified["status"] != "success" or any(not path.exists() for path in paths):
        raise RuntimeError("certified API projection failed")
    return paths


def main() -> int:
    for path in generate_api_assets():
        print(f"Wrote {path.relative_to(ROOT)} ({file_sha256(path)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
