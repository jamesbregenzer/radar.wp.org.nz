#!/usr/bin/env python3
"""Fail unless today's collector snapshot contains every enabled Trac feed."""

from __future__ import annotations

import csv
import argparse
import re
import sys

from radarlib import DATA_RAW, TICKET_ID_KEYS, load_queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-id", required=True, help="Immutable YYYY-MM-DD collection identity captured at run start.")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.collection_id):
        parser.error("collection ID must be YYYY-MM-DD")

    snapshot = DATA_RAW / "manual" / args.collection_id
    failures: list[str] = []

    for query in load_queries():
        slug = str(query["slug"])
        path = snapshot / f"{slug}.csv"
        if not path.exists():
            failures.append(f"{slug}: missing {path.relative_to(DATA_RAW.parent.parent)}")
            continue

        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            row_count = sum(1 for _ in reader)

        if not headers.intersection(TICKET_ID_KEYS):
            failures.append(f"{slug}: no recognized ticket ID column")
        print(f"{slug}: {row_count} rows")

    if failures:
        print("Collector snapshot is incomplete; refusing publication:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"Collector snapshot {args.collection_id} is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
