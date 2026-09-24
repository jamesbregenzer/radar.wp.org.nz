#!/usr/bin/env python3
"""Canonical WP-4 Radar application entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from certification import CERTIFIED_CURRENT, validate_named
from operations import (
    certify_operation,
    collect_operation,
    generate_operation,
    pipeline_operation,
    publish_operation,
    validate_collection_operation,
    verify_operation,
)
from radarcore import parse_run_time


def add_reference_time(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--reference-time", required=required, help="Explicit ISO-8601 operation time")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    collect = subparsers.add_parser("collect")
    add_reference_time(collect)
    collect.add_argument("--query", action="append", help="Configured query slug; repeatable")

    validate = subparsers.add_parser("validate-collection")
    add_reference_time(validate)
    validate.add_argument("--collection-id", required=True)

    generate = subparsers.add_parser("generate")
    add_reference_time(generate)
    generate.add_argument("--collection-id", required=True)

    certify = subparsers.add_parser("certify")
    add_reference_time(certify)
    certify.add_argument("--collection-id", required=True)
    certify.add_argument("--source-revision")
    certify.add_argument("--output", type=Path, default=CERTIFIED_CURRENT)

    verify = subparsers.add_parser("verify")
    add_reference_time(verify)
    verify.add_argument("--input", type=Path, default=CERTIFIED_CURRENT)

    publish = subparsers.add_parser("publish")
    add_reference_time(publish)
    publish.add_argument("--input", type=Path, default=CERTIFIED_CURRENT)
    publish.add_argument("--published-snapshot-id")

    pipeline = subparsers.add_parser("pipeline")
    add_reference_time(pipeline)
    pipeline.add_argument("--collection-id", required=True)
    pipeline.add_argument("--source-revision", required=True)
    pipeline.add_argument("--skip-collect", action="store_true", help="Use an already archived collection")
    return parser


def dispatch(args: argparse.Namespace) -> dict:
    context = parse_run_time(args.reference_time)
    if args.operation == "collect":
        return collect_operation(context, args.query)
    if args.operation == "validate-collection":
        return validate_collection_operation(context, args.collection_id)
    if args.operation == "generate":
        return generate_operation(context, args.collection_id)
    if args.operation == "certify":
        return certify_operation(context, args.collection_id, args.source_revision, args.output)
    if args.operation == "verify":
        return verify_operation(context, args.input)
    if args.operation == "publish":
        return publish_operation(context, args.input, args.published_snapshot_id)
    return pipeline_operation(context, args.collection_id, args.source_revision,
                              include_collect=not args.skip_collect)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = dispatch(args)
    schema_errors = validate_named(result, "execution-result.v1")
    if schema_errors:
        raise RuntimeError("operation emitted invalid execution-result.v1: " + "; ".join(schema_errors))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] in {"success", "no_data_delta"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
