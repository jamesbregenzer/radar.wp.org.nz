#!/usr/bin/env python3
"""Collect one or all configured Wave 2 WordPress source families."""

from __future__ import annotations

import argparse
from pathlib import Path

from wave2_sources import DEFAULT_CONFIG, DEFAULT_RAW_ROOT, DEFAULT_SOURCE_DIR, collect_source, load_config, write_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-family", action="append")
    parser.add_argument("--observed-at")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    config = load_config(args.config)
    selected = set(args.source_family or [])
    sources = [item for item in config["sources"] if not selected or item["sourceFamily"] in selected]
    missing = selected - {item["sourceFamily"] for item in sources}
    if missing:
        raise SystemExit(f"unknown source families: {', '.join(sorted(missing))}")
    for item in sources:
        snapshot = collect_source(item, observed_at=args.observed_at, raw_root=args.raw_root)
        path = write_snapshot(snapshot, args.output_dir)
        print(f"{item['sourceFamily']}\t{snapshot['recordCount']}\t{snapshot['candidateSignalCount']}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
