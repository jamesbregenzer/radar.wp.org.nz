#!/usr/bin/env python3
"""Stable WP-4 product operations. No scheduler, credentials, or Git publishing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from certification import (
    CERTIFIED_CURRENT,
    CertificationError,
    build_collection,
    certify,
    execution_result,
    file_sha256,
    validate_named,
    verify_certified,
)
from pipeline import CollectionResult, collect_query, generate_presentations
from radarcore import DatasetSelection, RunContext, select_datasets
from radarlib import DATA_RAW, ROOT, TICKET_ID_KEYS, load_queries

SUCCESS = "OK"
FAILURE_CODES = {
    "COLLECTION_QUERY_FAILED", "COLLECTION_INCOMPLETE", "COLLECTION_MALFORMED",
    "COLLECTION_AMBIGUOUS", "GENERATION_FAILED", "CERTIFICATION_FAILED",
    "VERIFICATION_FAILED", "PUBLICATION_NOT_ELIGIBLE", "SOURCE_REVISION_INVALID",
    "PIPELINE_STAGE_FAILED", "COLLECTION_ID_MISMATCH",
}


def product_path(path: Path, fallback: str) -> str:
    """Return a portable product identifier, never a machine-local path."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"{fallback.rstrip('/')}/{path.name}"


def stage_reference(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in ("operation", "status", "code", "output_identities")}


def expected_query_slugs(selected: list[str] | None = None) -> list[str]:
    configured = [query["slug"] for query in load_queries()]
    if selected is None:
        return configured
    unknown = sorted(set(selected) - set(configured))
    if unknown:
        raise ValueError(f"unknown query slugs: {', '.join(unknown)}")
    return [slug for slug in configured if slug in set(selected)]


def selection_for(collection_id: str, raw_dir: Path = DATA_RAW) -> DatasetSelection:
    return select_datasets(raw_dir, collection_id, expected_query_slugs(), TICKET_ID_KEYS)


def evidence_artifacts(selection: DatasetSelection) -> list[dict[str, str]]:
    return [
        {"path": product_path(evidence.artifact_path, f"data/raw/manual/{selection.identity}"),
         "sha256": evidence.sha256}
        for _, evidence in sorted(selection.evidence.items()) if evidence.sha256
    ]


def classify_selection_failure(selection: DatasetSelection) -> str:
    if selection.ambiguous:
        return "COLLECTION_AMBIGUOUS"
    errors = [error for evidence in selection.evidence.values() for error in evidence.errors]
    if any(error.startswith("malformed_csv") or "header" in error for error in errors):
        return "COLLECTION_MALFORMED"
    return "COLLECTION_INCOMPLETE"


def collect_operation(
    context: RunContext,
    selected_queries: list[str] | None = None,
    collector: Callable[[str, RunContext], CollectionResult] = collect_query,
) -> dict[str, Any]:
    try:
        slugs = expected_query_slugs(selected_queries)
    except ValueError as error:
        return execution_result("collect", "failure", context, errors=[str(error)], code="COLLECTION_QUERY_FAILED")
    results = []
    collection_errors: list[str] = []
    for slug in slugs:
        try:
            results.append(collector(slug, context))
        except Exception as error:
            collection_errors.append(f"query failed: {slug}: {error}")
    failed = [result.query_slug for result in results if not result.succeeded]
    failed.extend(slug for slug in slugs if slug not in {result.query_slug for result in results})
    artifacts = []
    for result in results:
        artifacts.extend(evidence_artifacts(result.selection))
    query_results = [
        {
            "operation": "collect",
            "status": "success" if result.succeeded else "failure",
            "code": SUCCESS if result.succeeded else "COLLECTION_QUERY_FAILED",
            "output_identities": [result.query_slug, result.selection.identity] if result.succeeded else [],
        }
        for result in results
    ]
    return execution_result(
        "collect", "failure" if failed else "success", context,
        inputs=slugs, outputs=[context.collection_date] if not failed else [], artifacts=artifacts,
        errors=[f"query failed: {slug}" for slug in failed if not any(f"query failed: {slug}:" in item for item in collection_errors)]
               + collection_errors,
        code="COLLECTION_QUERY_FAILED" if failed else SUCCESS,
        stages=query_results,
    )


def validate_collection_operation(context: RunContext, collection_id: str, raw_dir: Path = DATA_RAW) -> dict[str, Any]:
    selection = selection_for(collection_id, raw_dir)
    collection = build_collection(selection, context)
    schema_errors = validate_named(collection, "collection.v1")
    success = selection.complete and not schema_errors
    errors = list(collection["errors"]) + schema_errors
    return execution_result(
        "validate-collection", "success" if success else "failure", context,
        inputs=[collection_id], outputs=[collection["collection_id"]] if success else [],
        artifacts=evidence_artifacts(selection), warnings=collection["warnings"], errors=errors,
        code=SUCCESS if success else classify_selection_failure(selection),
    )


def quiet_subprocess_runner(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, file=sys.stderr, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return completed.returncode


def generation_artifact_paths(context: RunContext) -> list[Path]:
    return [
        ROOT / "reports/latest.md", ROOT / f"reports/radar-{context.collection_date}.md",
        ROOT / "docs/radar/index.html", ROOT / "docs/radar/admin-data.json",
        ROOT / "docs/radar/contributions/index.html",
    ]


def generate_operation(
    context: RunContext,
    collection_id: str,
    runner: Callable[[list[str]], int] = quiet_subprocess_runner,
    artifacts: list[Path] | None = None,
    raw_dir: Path = DATA_RAW,
) -> dict[str, Any]:
    validation = validate_collection_operation(context, collection_id, raw_dir)
    if validation["status"] != "success":
        return execution_result("generate", "failure", context, inputs=[collection_id],
                                errors=validation["errors"], code=validation["code"])
    try:
        code = generate_presentations(context, runner=runner, collection_id=collection_id)
    except Exception as error:
        return execution_result("generate", "failure", context, inputs=[collection_id],
                                errors=[str(error)], code="GENERATION_FAILED")
    paths = artifacts or generation_artifact_paths(context)
    missing = [product_path(path, "generated") for path in paths if not path.exists()]
    if code or missing:
        return execution_result("generate", "failure", context, inputs=[collection_id],
                                errors=([f"generator exit code {code}"] if code else []) + [f"missing artifact: {p}" for p in missing],
                                code="GENERATION_FAILED")
    refs = [{"path": product_path(path, "generated"),
             "sha256": file_sha256(path)} for path in paths]
    return execution_result("generate", "success", context, inputs=[collection_id],
                            outputs=[collection_id], artifacts=refs)


def resolve_source_revision(explicit: str | None, repo: Path = ROOT,
                            run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> tuple[str | None, str | None]:
    if explicit:
        if not re_full_sha(explicit):
            return None, "explicit source revision must be a 40-character hexadecimal SHA"
        return explicit.lower(), None
    status = run(["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True)
    if status.returncode or status.stdout.strip():
        return None, "automatic source revision requires a clean Git working tree"
    revision = run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True)
    value = revision.stdout.strip()
    if revision.returncode or not re_full_sha(value):
        return None, "unable to resolve a clean local Git source revision"
    return value.lower(), None


def re_full_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdefABCDEF" for character in value)


def certify_operation(context: RunContext, collection_id: str, source_revision: str | None,
                      current_dir: Path = CERTIFIED_CURRENT, raw_dir: Path = DATA_RAW) -> dict[str, Any]:
    revision, error = resolve_source_revision(source_revision)
    if error:
        return execution_result("certify", "failure", context, inputs=[collection_id], errors=[error], code="SOURCE_REVISION_INVALID")
    selection = selection_for(collection_id, raw_dir)
    return certify(selection, context, revision, current_dir)


def verify_operation(context: RunContext, bundle_dir: Path = CERTIFIED_CURRENT) -> dict[str, Any]:
    try:
        result = verify_certified(bundle_dir)
        result["reference_time"] = context.generated_iso
        result["started_at"] = context.generated_iso
        result["completed_at"] = context.generated_iso
        return result
    except Exception as error:
        return execution_result("verify", "failure", context, inputs=[product_path(bundle_dir, "data/certified")],
                                errors=[str(error)], code="VERIFICATION_FAILED")


def publish_operation(context: RunContext, bundle_dir: Path = CERTIFIED_CURRENT,
                      published_snapshot_id: str | None = None) -> dict[str, Any]:
    verified = verify_operation(context, bundle_dir)
    if verified["status"] != "success":
        return execution_result("publish", "failure", context,
                                inputs=[product_path(bundle_dir, "data/certified")],
                                errors=verified["errors"], code="PUBLICATION_NOT_ELIGIBLE")
    snapshot = json.loads((bundle_dir / "snapshot.json").read_text(encoding="utf-8"))
    snapshot_id = snapshot["snapshot_id"]
    artifacts = [
        {"path": product_path(bundle_dir / name, "data/certified/current"),
         "sha256": file_sha256(bundle_dir / name)}
        for name in ("collection.json", "opportunities.json", "snapshot.json", "snapshot.sha256")
    ]
    if published_snapshot_id == snapshot_id:
        return execution_result("publish", "no_data_delta", context, inputs=[snapshot_id], outputs=[snapshot_id],
                                artifacts=artifacts, warnings=["NO_DATA_DELTA"], code="NO_DATA_DELTA")
    return execution_result("publish", "success", context, inputs=[snapshot_id], outputs=[snapshot_id], artifacts=artifacts)


def pipeline_operation(
    context: RunContext,
    collection_id: str,
    source_revision: str,
    *,
    include_collect: bool = True,
    operations: dict[str, Callable[..., dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    ops = operations or {}
    stages: list[dict[str, Any]] = []
    calls = []
    if include_collect:
        if collection_id != context.collection_date:
            return execution_result(
                "pipeline", "failure", context, inputs=[collection_id],
                errors=[f"collection ID {collection_id} does not match reference-time date {context.collection_date}"],
                code="COLLECTION_ID_MISMATCH",
            )
        # Canonical collection is deliberately all-or-nothing. Query subsets are
        # supported only by the standalone diagnostic collect operation.
        calls.append(("collect", lambda: ops.get("collect", collect_operation)(context)))
    calls.extend([
        ("validate-collection", lambda: ops.get("validate", validate_collection_operation)(context, collection_id)),
        ("generate", lambda: ops.get("generate", generate_operation)(context, collection_id)),
        ("certify", lambda: ops.get("certify", certify_operation)(context, collection_id, source_revision)),
        ("verify", lambda: ops.get("verify", verify_operation)(context)),
        ("publish", lambda: ops.get("publish", publish_operation)(context)),
    ])
    outputs: list[str] = []
    for name, call in calls:
        try:
            result = call()
        except Exception as error:
            result = execution_result(name, "failure", context, errors=[str(error)], code="PIPELINE_STAGE_FAILED")
        stages.append(stage_reference(result))
        if result["status"] not in {"success", "no_data_delta"}:
            return execution_result("pipeline", "failure", context, inputs=[collection_id],
                                    errors=[f"stage failed: {name}"], code="PIPELINE_STAGE_FAILED", stages=stages)
        outputs = result["output_identities"] or outputs
    return execution_result("pipeline", "success", context, inputs=[collection_id], outputs=outputs, stages=stages)
