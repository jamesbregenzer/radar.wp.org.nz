#!/usr/bin/env python3
"""Import the browser-downloaded Trac CSV into the raw data archive."""

from __future__ import annotations

import argparse
import shutil
import re
import sys
from pathlib import Path

from radarlib import ROOT, load_queries

DOWNLOADS = Path.home() / "Downloads"
RAW_MANUAL = ROOT / "data" / "raw" / "manual"
DEFAULT_DOWNLOAD = DOWNLOADS / "query.csv"


def enabled_query_slugs() -> set[str]:
    return {query["slug"] for query in load_queries()}


COLLECTION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def import_download(query_slug: str, source: Path = DEFAULT_DOWNLOAD, *, collection_id: str) -> Path:
    if query_slug not in enabled_query_slugs():
        raise ValueError(f"Unknown or disabled query slug: {query_slug}")

    if not source.exists():
        raise FileNotFoundError(f"Could not find downloaded CSV: {source}")
    if not COLLECTION_ID_RE.fullmatch(collection_id):
        raise ValueError(f"Invalid collection ID: {collection_id}")

    target_dir = RAW_MANUAL / collection_id
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / f"{query_slug}.csv"
    temporary = target.with_suffix(".csv.tmp")

    shutil.copy2(source, temporary)
    temporary.replace(target)

    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_slug", help="Enabled query slug from config/queries.json.")
    parser.add_argument("--collection-id", required=True, help="Immutable YYYY-MM-DD collection identity captured at run start.")
    parser.add_argument("--source", type=Path, default=DEFAULT_DOWNLOAD, help="Downloaded CSV path. Defaults to ~/Downloads/query.csv.")
    args = parser.parse_args()

    try:
        target = import_download(args.query_slug, args.source, collection_id=args.collection_id)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Imported {args.source}")
    print(f"Saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
