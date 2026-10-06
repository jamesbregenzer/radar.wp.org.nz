#!/usr/bin/env python3
"""Import the browser-downloaded Trac CSV into the raw data archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import shutil
import re
import sys
from pathlib import Path

from radarlib import ROOT, load_queries
from trac_receipts import configured_query, query_url, write_trac_receipt

DOWNLOADS = Path.home() / "Downloads"
RAW_MANUAL = ROOT / "data" / "raw" / "manual"
DEFAULT_DOWNLOAD = DOWNLOADS / "query.csv"


def enabled_query_slugs() -> set[str]:
    return {query["slug"] for query in load_queries()}


COLLECTION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}-\d{2}-\d{2}Z)?$")


def import_download(query_slug: str, source: Path = DEFAULT_DOWNLOAD, *, collection_id: str, source_url: str | None = None) -> Path:
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

    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise FileExistsError(f"Immutable raw source snapshot already exists: {target}")
        resolved_url = source_url or query_url(configured_query(query_slug))
        write_trac_receipt(
            query_slug=query_slug,
            collection_id=collection_id,
            source_url=resolved_url,
            csv_path=target,
            retrieved_at=datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        return target

    shutil.copy2(source, temporary)
    temporary.replace(target)
    resolved_url = source_url or query_url(configured_query(query_slug))
    write_trac_receipt(
        query_slug=query_slug,
        collection_id=collection_id,
        source_url=resolved_url,
        csv_path=target,
        retrieved_at=datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )

    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_slug", help="Enabled query slug from config/queries.json.")
    parser.add_argument("--collection-id", required=True, help="Immutable collection identity captured at run start.")
    parser.add_argument("--source", type=Path, default=DEFAULT_DOWNLOAD, help="Downloaded CSV path. Defaults to ~/Downloads/query.csv.")
    parser.add_argument("--source-url", help="Exact Trac CSV URL used for acquisition.")
    args = parser.parse_args()

    try:
        target = import_download(args.query_slug, args.source, collection_id=args.collection_id, source_url=args.source_url)
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Imported {args.source}")
    print(f"Saved to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
