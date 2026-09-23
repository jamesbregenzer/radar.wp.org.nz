#!/usr/bin/env python3
"""Fail unless today's collector snapshot contains every enabled Trac feed."""

from __future__ import annotations

import csv
import sys
from datetime import datetime

from radarlib import DATA_RAW, TICKET_ID_KEYS, load_queries


def main() -> int:
    collected_date = datetime.now().strftime("%Y-%m-%d")
    snapshot = DATA_RAW / "manual" / collected_date
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

    print(f"Collector snapshot {collected_date} is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
