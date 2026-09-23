#!/usr/bin/env python3
"""Narrow WP-3 certification/verification interface; WP-4 owns the final CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from certification import CERTIFIED_CURRENT, CertificationError, certify, verify_certified
from radarcore import parse_run_time, select_datasets
from radarlib import DATA_RAW, TICKET_ID_KEYS, load_queries


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    certify_parser = subparsers.add_parser("certify")
    certify_parser.add_argument("--collection-id", required=True)
    certify_parser.add_argument("--reference-time", required=True)
    certify_parser.add_argument("--source-revision")
    certify_parser.add_argument("--output", type=Path, default=CERTIFIED_CURRENT)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, default=CERTIFIED_CURRENT)
    args = parser.parse_args()

    if args.operation == "certify":
        context = parse_run_time(args.reference_time)
        expected = [query["slug"] for query in load_queries()]
        selection = select_datasets(DATA_RAW, args.collection_id, expected, TICKET_ID_KEYS)
        result = certify(selection, context, args.source_revision, args.output)
    else:
        try:
            result = verify_certified(args.input)
        except CertificationError as error:
            print(json.dumps({"schema": "execution-result.v1", "operation": "verify", "status": "failure", "errors": [str(error)]}, sort_keys=True))
            return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
