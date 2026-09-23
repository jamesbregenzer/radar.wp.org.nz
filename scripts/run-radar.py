#!/usr/bin/env python3
"""Run the WP Core Radar collection and reporting pipeline."""

from __future__ import annotations

import argparse
import sys

from pipeline import collect_query, generate_presentations
from radarcore import parse_run_time
from radarlib import load_queries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append", help="Run only this query slug. Can be used multiple times.")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip browser fetching and only generate reports.")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue if an individual query fetch fails.")
    parser.add_argument("--reference-time", help="ISO-8601 run time for deterministic generation")
    parser.add_argument("--collection-id", help="Generate from exactly this archived collection identity")
    args = parser.parse_args()
    context = parse_run_time(args.reference_time)

    queries = load_queries()
    if args.query:
        wanted = set(args.query)
        queries = [q for q in queries if q["slug"] in wanted]

    if not queries and not args.skip_fetch:
        print("No enabled queries found. Check config/queries.json.", file=sys.stderr)
        return 1

    if not args.skip_fetch:
        for query in queries:
            slug = query["slug"]
            print(f"\n=== Fetching {slug}: {query.get('name', slug)} ===")
            result = collect_query(slug, context)
            code = result.exit_code

            if not result.succeeded:
                evidence = result.selection.evidence.get(slug)
                detail = "; ".join((evidence.errors if evidence else ("no evidence",)))
                message = f"Fetch/validation failed for {slug} with exit code {code}: {detail}"
                if args.continue_on_error:
                    print(message, file=sys.stderr)
                    continue

                print(message, file=sys.stderr)
                return code or 1

    print("\n=== Generating report and dashboard ===")
    collection_id = args.collection_id or (context.collection_date if not args.skip_fetch else None)
    code = generate_presentations(context, collection_id=collection_id)
    if code != 0:
        return code

    print("\nRadar run complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
