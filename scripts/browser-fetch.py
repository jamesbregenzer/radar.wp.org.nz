#!/usr/bin/env python3
"""Fetch a configured WordPress Trac CSV through the governed provider session."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from acquisition_placement import (
    ERROR_CODE,
    PlacementError,
    placement_environment,
    require_trac_acquisition_placement,
    utc_timestamp,
)
from radarlib import ROOT, load_queries
from trac_receipts import query_url

DOWNLOADS = Path.home() / "Downloads"
DEFAULT_TIMEOUT_SECONDS = 90

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
    parser.add_argument("--interactive-canary", action="store_true", help="Allow an explicitly requested diagnostic run outside the canonical provider.")
    args = parser.parse_args()

    started_at = utc_timestamp()
    try:
        placement = require_trac_acquisition_placement(allow_interactive_canary=args.interactive_canary)
    except PlacementError:
        print(ERROR_CODE, file=sys.stderr)
        return 78

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
        child_env = os.environ.copy()
        child_env.update(placement_environment(placement, started_at=started_at))
        subprocess.run([
            sys.executable,
            str(ROOT / "scripts" / "import-download.py"),
            args.query_slug,
            "--source", str(downloaded),
            "--collection-id", args.collection_id,
            "--source-url", url,
        ], check=True, env=child_env)
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
