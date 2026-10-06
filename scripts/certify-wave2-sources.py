#!/usr/bin/env python3
"""Verify committed Wave 2 snapshots and their immutable raw acquisitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from certification import canonical_hash, canonical_json
from wave2_sources import DEFAULT_CONFIG, DEFAULT_SOURCE_DIR, family_slug, load_config, verify_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "certified" / "wave2" / "source-certification.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = load_config(args.config)
    results = []
    for item in config["sources"]:
        path = args.source_dir / f"{family_slug(item['sourceFamily'])}.json"
        if not path.exists():
            results.append({
                "sourceFamily": item["sourceFamily"],
                "status": "failed",
                "recordCount": 0,
                "candidateSignalCount": 0,
                "errors": [f"missing snapshot: {path}"],
            })
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        result = verify_snapshot(snapshot)
        result["snapshot"] = str(path.relative_to(ROOT))
        result["snapshotId"] = snapshot.get("snapshotId")
        result["certifiedTime"] = snapshot.get("certifiedTime")
        results.append(result)
    certified_times = [item.get("certifiedTime") for item in results if item.get("certifiedTime")]
    body = {
        "schema": "radar-wave2-source-certification.v1",
        "version": 1,
        "certifiedAt": max(certified_times) if certified_times else None,
        "state": "certified" if all(item["status"] == "certified" for item in results) else "failed",
        "sources": results,
    }
    body["canonicalHash"] = canonical_hash(body)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(body))
    print(args.output)
    return 0 if body["state"] == "certified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
