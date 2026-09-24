#!/usr/bin/env python3
"""Fetch a configured WordPress Trac CSV through the local browser session."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from radarlib import ROOT, load_queries

DOWNLOADS = Path.home() / "Downloads"
DEFAULT_TIMEOUT_SECONDS = 90

QUERY_COLUMNS = (
    "id",
    "summary",
    "status",
    "component",
    "owner",
    "type",
    "priority",
    "milestone",
    "version",
    "keywords",
    "time",
    "changetime",
    # Trac custom query may ignore unsupported columns; keep likely comment
    # count aliases here so momentum scoring starts working if Trac exposes one.
    "comments",
    "_comments",
)



def query_url(query: dict) -> str:
    if query.get("url"):
        return str(query["url"])

    track = query.get("track")
    if not track:
        raise ValueError(f"Query {query.get('slug', '<unknown>')} is missing both url and track.")

    params = urlencode(
        {
            "status": "!closed",
            "keywords": f"~{track}",
            "format": "csv",
            "col": list(QUERY_COLUMNS),
        },
        doseq=True,
    )
    return f"https://core.trac.wordpress.org/query?{params}"


def wait_for_download(timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Path:
    target = DOWNLOADS / "query.csv"
    partials = [DOWNLOADS / "query.csv.part", DOWNLOADS / "query.csv.download"]

    start = time.time()
    last_size = -1
    stable_seen_at: float | None = None

    while time.time() - start < timeout:
        if target.exists() and not any(path.exists() for path in partials):
            size = target.stat().st_size
            if size > 0 and size == last_size:
                if stable_seen_at and time.time() - stable_seen_at >= 1:
                    return target
            else:
                stable_seen_at = time.time()
                last_size = size
        time.sleep(0.5)

    raise TimeoutError(f"Timed out waiting for {target}")


def remove_previous_downloads() -> None:
    for file in DOWNLOADS.glob("query*.csv"):
        if file.is_file():
            file.unlink()
    for file in DOWNLOADS.glob("query*.csv.*"):
        if file.is_file():
            file.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_slug", help="Enabled query slug from config/queries.json.")
    parser.add_argument("--collection-id", required=True, help="Immutable collection identity captured at run start.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--browser", default="Firefox")
    parser.add_argument("--keep-browser-open", action="store_true")
    args = parser.parse_args()

    queries = {query["slug"]: query for query in load_queries()}
    query = queries.get(args.query_slug)
    if not query:
        print(f"Unknown or disabled query: {args.query_slug}", file=sys.stderr)
        return 1

    remove_previous_downloads()
    url = query_url(query)

    print(f"Opening {args.browser} for {args.query_slug}...")
    subprocess.run(["open", "-n", "-a", args.browser, "--args", url], check=True)

    try:
        downloaded = wait_for_download(args.timeout)
        print(f"Downloaded {downloaded}")
        subprocess.run([
            sys.executable,
            str(ROOT / "scripts" / "import-download.py"),
            args.query_slug,
            "--source", str(downloaded),
            "--collection-id", args.collection_id,
        ], check=True)
        downloaded.unlink(missing_ok=True)
        print("Removed downloaded query.csv")
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if not args.keep_browser_open:
            subprocess.run(["osascript", "-e", f'tell application "{args.browser}" to quit'], check=False)
            print(f"Closed {args.browser}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
