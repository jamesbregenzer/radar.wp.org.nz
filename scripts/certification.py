#!/usr/bin/env python3
"""Canonical Radar data construction, certification, and offline verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from radarcore import DatasetSelection, RunContext, file_sha256, load_scoring_config
from radarlib import (
    COMMENTS_KEYS,
    COMPONENT_KEYS,
    CREATED_KEYS,
    KEYWORDS_KEYS,
    MILESTONE_KEYS,
    MODIFIED_KEYS,
    OWNER_KEYS,
    STATUS_KEYS,
    SUMMARY_KEYS,
    Opportunity,
    build_opportunities,
    first_value,
    load_queries,
    priority_tier,
    trac_url,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"
CERTIFIED_CURRENT = ROOT / "data" / "certified" / "current"
QUERIES_CONFIG = ROOT / "config" / "queries.json"
SCORING_CONFIG = ROOT / "config" / "scoring.json"

SCHEMA_FILES = {
    "collection.v1": "collection.v1.schema.json",
    "snapshot.v1": "snapshot.v1.schema.json",
    "opportunity.v1": "opportunity.v1.schema.json",
    "execution-result.v1": "execution-result.v1.schema.json",
}


class CertificationError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    """UTF-8 JSON: sorted object keys, compact separators, one LF."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def load_schema(name: str, schemas_dir: Path = SCHEMAS_DIR) -> dict[str, Any]:
    return json.loads((schemas_dir / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Focused deterministic validator for the JSON Schema vocabulary used here."""
    errors: list[str] = []
    expected = schema.get("type")
    allowed_types = [expected] if isinstance(expected, str) else (expected or [])
    if allowed_types and not any(_type_matches(instance, item) for item in allowed_types):
        return [f"{path}: expected {'/'.join(allowed_types)}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value is not in enum")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string is too short")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], instance):
            errors.append(f"{path}: string does not match pattern")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: too few items")
        if schema.get("uniqueItems") and len({canonical_json(item) for item in instance}) != len(instance):
            errors.append(f"{path}: duplicate items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(validate_schema(item, item_schema, f"{path}[{index}]"))
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key}")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: unknown property {key}")
        for key, subschema in properties.items():
            if key in instance:
                errors.extend(validate_schema(instance[key], subschema, f"{path}.{key}"))
    return errors


def validate_named(instance: Any, name: str, schemas_dir: Path = SCHEMAS_DIR) -> list[str]:
    return validate_schema(instance, load_schema(name, schemas_dir))


def repository_artifact_path(selection: DatasetSelection, path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"data/raw/manual/{selection.identity}/{path.name}"


def _collection_preimage(selection: DatasetSelection, context: RunContext) -> dict[str, Any]:
    query_evidence = []
    for slug in sorted(selection.expected_queries):
        evidence = selection.evidence[slug]
        query_evidence.append({
            "query_slug": slug,
            "source_identity": evidence.source_identity,
            "artifact_path": repository_artifact_path(selection, evidence.artifact_path),
            "collected_at": context.generated_iso,
            "exists": evidence.exists,
            "valid_csv": evidence.valid_csv,
            "recognized_ticket_id": evidence.recognized_ticket_id,
            "row_count": evidence.row_count,
            "sha256": evidence.sha256,
            "warnings": sorted(evidence.warnings),
            "errors": sorted(evidence.errors),
        })
    ambiguous = [
        {"query_slug": slug, "artifact_paths": sorted(repository_artifact_path(selection, path) for path in paths)}
        for slug, paths in sorted(selection.ambiguous.items())
    ]
    unexpected = sorted(repository_artifact_path(selection, path) for path in selection.unexpected)
    errors = []
    if selection.ambiguous:
        errors.append("ambiguous_required_query")
    if not selection.complete:
        errors.append("incomplete_required_collection")
    return {
        "schema": "collection.v1",
        "version": 1,
        "reference_time": context.generated_iso,
        "state": "complete" if selection.complete else "incomplete",
        "expected_queries": sorted(selection.expected_queries),
        "query_evidence": query_evidence,
        "unexpected_artifacts": unexpected,
        "ambiguous_artifacts": ambiguous,
        "warnings": ["unexpected_artifacts_present"] if unexpected else [],
        "errors": errors,
    }


def build_collection(selection: DatasetSelection, context: RunContext) -> dict[str, Any]:
    value = _collection_preimage(selection, context)
    value["collection_id"] = f"collection-v1-{canonical_hash(value)[:24]}"
    return value


def _string_or_none(value: str) -> str | None:
    return value or None


def _integer_or_none(value: str) -> int | None:
    return int(value) if value.isdigit() else None


def _score_breakdown(reasons: tuple[str, ...]) -> list[dict[str, Any]]:
    values = []
    for reason in reasons:
        match = re.search(r"([+-]\d+)$", reason)
        values.append({"signal": reason[: match.start()].strip() if match else reason, "points": int(match.group(1)) if match else 0})
    return values


def build_opportunity_record(
    opportunity: Opportunity,
    all_sources: set[str],
    selection: DatasetSelection,
    collection_id: str,
    snapshot_id: str,
    scoring_version: str,
    query_by_slug: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = opportunity.row
    sources = []
    for slug in sorted(all_sources):
        query = query_by_slug.get(slug, {})
        evidence = selection.evidence[slug]
        sources.append({
            "query_slug": slug,
            "source_identity": evidence.source_identity,
            "artifact_path": repository_artifact_path(selection, evidence.artifact_path),
            "track": str(query.get("track", slug)),
        })
    review = opportunity.review or {}
    radar_state: dict[str, Any] = {}
    for key in ("status", "received_props", "props_recorded_at", "changeset"):
        if key in review and review[key] not in (None, "", False):
            radar_state[key] = review[key]
    tier, tier_label = priority_tier(opportunity.as_item())
    keywords = sorted(set(first_value(row, KEYWORDS_KEYS).split()))
    complexity = sorted(
        reason.rsplit(" ", 1)[0] for reason in opportunity.reasons if reason.startswith("setup complexity:")
    )
    return {
        "schema": "opportunity.v1",
        "version": 1,
        "ticket": {
            "id": opportunity.ticket_id,
            "url": trac_url(opportunity.ticket_id),
            "summary": first_value(row, SUMMARY_KEYS, "Untitled ticket"),
            "component": _string_or_none(first_value(row, COMPONENT_KEYS)),
            "status": _string_or_none(first_value(row, STATUS_KEYS)),
            "resolution": _string_or_none(first_value(row, ("resolution", "Resolution"))),
            "owner": _string_or_none(first_value(row, OWNER_KEYS)),
            "reporter": _string_or_none(first_value(row, ("reporter", "Reporter"))),
            "type": _string_or_none(first_value(row, ("type", "Type"))),
            "priority": _string_or_none(first_value(row, ("priority", "Priority"))),
            "milestone": _string_or_none(first_value(row, MILESTONE_KEYS)),
            "wordpress_version": _string_or_none(first_value(row, ("version", "Version"))),
            "keywords": keywords,
            "created": _string_or_none(first_value(row, CREATED_KEYS)),
            "modified": _string_or_none(first_value(row, MODIFIED_KEYS)),
            "comment_count": _integer_or_none(first_value(row, COMMENTS_KEYS)),
        },
        "discovery": {
            "sources": sources,
            "tracks": sorted({source["track"] for source in sources}),
        },
        "ranking": {
            "score": opportunity.score,
            "tier": tier,
            "tier_label": tier_label,
            "scoring_version": scoring_version,
            "reasons": list(opportunity.reasons),
            "breakdown": _score_breakdown(opportunity.reasons),
            "complexity_markers": complexity,
        },
        "radar_state": radar_state,
        "provenance": {
            "collection_id": collection_id,
            "snapshot_id": snapshot_id,
        },
    }


def derive_snapshot_id(
    collection_hash: str,
    dataset_seed_hash: str,
    context: RunContext,
    source_revision: str | None,
    scoring_hash: str,
    query_hash: str,
) -> str:
    identity = {
        "schema": "snapshot.v1",
        "collection_hash": collection_hash,
        "dataset_seed_hash": dataset_seed_hash,
        "reference_time": context.generated_iso,
        "source_revision": source_revision,
        "scoring_config_sha256": scoring_hash,
        "query_config_sha256": query_hash,
    }
    return f"snapshot-v1-{canonical_hash(identity)[:24]}"


def execution_result(
    operation: str,
    status: str,
    context: RunContext,
    *,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    artifacts: list[dict[str, str]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "execution-result.v1",
        "version": 1,
        "operation": operation,
        "status": status,
        "started_at": context.generated_iso,
        "completed_at": context.generated_iso,
        "reference_time": context.generated_iso,
        "input_identities": inputs or [],
        "output_identities": outputs or [],
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "retry_safe": True,
    }


@dataclass(frozen=True)
class CertificationBundle:
    collection: dict[str, Any]
    opportunities: dict[str, Any]
    snapshot: dict[str, Any]
    manifest_sha256: str
    result: dict[str, Any]

    def files(self) -> dict[str, bytes]:
        return {
            "collection.json": canonical_json(self.collection),
            "opportunities.json": canonical_json(self.opportunities),
            "snapshot.json": canonical_json(self.snapshot),
            "snapshot.sha256": (self.manifest_sha256 + "  snapshot.json\n").encode("ascii"),
        }


def build_certification_bundle(
    selection: DatasetSelection,
    context: RunContext,
    source_revision: str | None = None,
    schemas_dir: Path = SCHEMAS_DIR,
) -> CertificationBundle:
    collection = build_collection(selection, context)
    failures = validate_named(collection, "collection.v1", schemas_dir)
    if not selection.complete:
        failures.append("collection selection is incomplete")
    if failures:
        raise CertificationError("; ".join(failures))

    scoring = load_scoring_config()
    scoring_hash = file_sha256(SCORING_CONFIG)
    query_hash = file_sha256(QUERIES_CONFIG)
    collection_hash = canonical_hash(collection)
    opportunities, source_map, _ = build_opportunities(context, selection)
    query_by_slug = {query["slug"]: query for query in load_queries()}

    # Seed excludes snapshot provenance to avoid a circular identifier.
    seed = [{"ticket_id": item.ticket_id, "score": item.score, "reasons": list(item.reasons),
             "sources": sorted(source_map[item.ticket_id])} for item in opportunities]
    dataset_seed_hash = canonical_hash(seed)
    snapshot_id = derive_snapshot_id(collection_hash, dataset_seed_hash, context, source_revision,
                                     scoring_hash, query_hash)
    records = [build_opportunity_record(item, source_map[item.ticket_id], selection,
                                        collection["collection_id"], snapshot_id,
                                        scoring["version"], query_by_slug)
               for item in opportunities]
    for index, record in enumerate(records):
        failures.extend(f"opportunities[{index}] {error}" for error in validate_named(record, "opportunity.v1", schemas_dir))
    if failures:
        raise CertificationError("; ".join(failures))

    opportunity_set = {
        "schema": "opportunity-set.v1",
        "version": 1,
        "collection_id": collection["collection_id"],
        "snapshot_id": snapshot_id,
        "opportunities": records,
    }
    collection_bytes = canonical_json(collection)
    opportunity_bytes = canonical_json(opportunity_set)
    dataset_hash = sha256_bytes(opportunity_bytes)
    snapshot = {
        "schema": "snapshot.v1",
        "version": 1,
        "snapshot_id": snapshot_id,
        "collection_id": collection["collection_id"],
        "collection_sha256": sha256_bytes(collection_bytes),
        "source_revision": source_revision,
        "scoring_version": scoring["version"],
        "scoring_config_sha256": scoring_hash,
        "query_config_sha256": query_hash,
        "reference_time": context.generated_iso,
        "schema_versions": sorted(SCHEMA_FILES),
        "opportunity_count": len(records),
        "identity_seed_sha256": dataset_seed_hash,
        "dataset_sha256": dataset_hash,
        "artifacts": [
            {"path": "collection.json", "sha256": sha256_bytes(collection_bytes)},
            {"path": "opportunities.json", "sha256": dataset_hash},
        ],
        "certification": {"state": "certified", "warnings": collection["warnings"], "errors": []},
    }
    failures = validate_named(snapshot, "snapshot.v1", schemas_dir)
    if failures:
        raise CertificationError("; ".join(failures))
    manifest_hash = canonical_hash(snapshot)
    result = execution_result(
        "certify", "success", context,
        inputs=[collection["collection_id"]], outputs=[snapshot_id],
        artifacts=[{"path": item["path"], "sha256": item["sha256"]} for item in snapshot["artifacts"]]
                  + [{"path": "snapshot.json", "sha256": manifest_hash}],
        warnings=collection["warnings"],
    )
    result_errors = validate_named(result, "execution-result.v1", schemas_dir)
    if result_errors:
        raise CertificationError("; ".join(result_errors))
    return CertificationBundle(collection, opportunity_set, snapshot, manifest_hash, result)


def certify(
    selection: DatasetSelection,
    context: RunContext,
    source_revision: str | None = None,
    current_dir: Path = CERTIFIED_CURRENT,
    schemas_dir: Path = SCHEMAS_DIR,
) -> dict[str, Any]:
    """Fail closed: only a fully built and verified bundle replaces current."""
    try:
        bundle = build_certification_bundle(selection, context, source_revision, schemas_dir)
        publish_bundle(bundle, current_dir)
        return bundle.result
    except Exception as error:
        result = execution_result(
            "certify", "failure", context,
            inputs=[selection.identity], errors=[str(error)],
        )
        result_errors = validate_named(result, "execution-result.v1", schemas_dir)
        if result_errors:
            raise CertificationError("invalid failure result: " + "; ".join(result_errors)) from error
        return result


def publish_bundle(bundle: CertificationBundle, current_dir: Path = CERTIFIED_CURRENT) -> None:
    current_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".certified-", dir=current_dir.parent))
    backup = current_dir.parent / ".current-backup"
    try:
        for name, content in bundle.files().items():
            (staging / name).write_bytes(content)
        verify_certified(staging)
        if backup.exists():
            shutil.rmtree(backup)
        if current_dir.exists():
            os.replace(current_dir, backup)
        os.replace(staging, current_dir)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not current_dir.exists():
            os.replace(backup, current_dir)
        raise


def verify_certified(current_dir: Path = CERTIFIED_CURRENT, schemas_dir: Path = SCHEMAS_DIR) -> dict[str, Any]:
    required = ("collection.json", "opportunities.json", "snapshot.json", "snapshot.sha256")
    missing = [name for name in required if not (current_dir / name).exists()]
    if missing:
        raise CertificationError(f"missing certified artifacts: {', '.join(missing)}")
    collection = json.loads((current_dir / "collection.json").read_text(encoding="utf-8"))
    opportunities = json.loads((current_dir / "opportunities.json").read_text(encoding="utf-8"))
    snapshot = json.loads((current_dir / "snapshot.json").read_text(encoding="utf-8"))
    errors = validate_named(collection, "collection.v1", schemas_dir) + validate_named(snapshot, "snapshot.v1", schemas_dir)
    for index, record in enumerate(opportunities.get("opportunities", [])):
        errors.extend(f"opportunities[{index}] {error}" for error in validate_named(record, "opportunity.v1", schemas_dir))
    if collection.get("state") != "complete" or snapshot.get("certification", {}).get("state") != "certified":
        errors.append("collection/snapshot is not certified complete")
    expected_queries = set(collection.get("expected_queries", []))
    evidence_queries = {item.get("query_slug") for item in collection.get("query_evidence", [])}
    if expected_queries != evidence_queries:
        errors.append("collection query inventory mismatch")
    for evidence in collection.get("query_evidence", []):
        if not (evidence.get("exists") and evidence.get("valid_csv") and evidence.get("recognized_ticket_id")) or evidence.get("errors"):
            errors.append(f"invalid required query evidence: {evidence.get('query_slug')}")
        source_path = ROOT / evidence.get("artifact_path", "")
        if not source_path.exists() or file_sha256(source_path) != evidence.get("sha256"):
            errors.append(f"source artifact hash mismatch: {evidence.get('query_slug')}")
    if opportunities.get("collection_id") != collection.get("collection_id"):
        errors.append("opportunity collection identity mismatch")
    if opportunities.get("snapshot_id") != snapshot.get("snapshot_id"):
        errors.append("opportunity snapshot identity mismatch")
    collection_preimage = dict(collection)
    collection_id = collection_preimage.pop("collection_id", "")
    if collection_id != f"collection-v1-{canonical_hash(collection_preimage)[:24]}":
        errors.append("collection identity mismatch")
    expected_snapshot_id = derive_snapshot_id(
        snapshot.get("collection_sha256", ""), snapshot.get("identity_seed_sha256", ""),
        RunContext.from_iso(snapshot.get("reference_time", "")), snapshot.get("source_revision"),
        snapshot.get("scoring_config_sha256", ""), snapshot.get("query_config_sha256", ""),
    )
    if snapshot.get("snapshot_id") != expected_snapshot_id:
        errors.append("snapshot identity mismatch")
    if snapshot.get("collection_sha256") != file_sha256(current_dir / "collection.json"):
        errors.append("collection hash mismatch")
    if snapshot.get("opportunity_count") != len(opportunities.get("opportunities", [])):
        errors.append("opportunity count mismatch")
    for artifact in snapshot.get("artifacts", []):
        path = current_dir / artifact["path"]
        if not path.exists() or file_sha256(path) != artifact["sha256"]:
            errors.append(f"artifact hash mismatch: {artifact['path']}")
    if snapshot.get("dataset_sha256") != file_sha256(current_dir / "opportunities.json"):
        errors.append("dataset hash mismatch")
    expected_manifest = (current_dir / "snapshot.sha256").read_text(encoding="ascii").split()[0]
    if expected_manifest != file_sha256(current_dir / "snapshot.json"):
        errors.append("snapshot manifest hash mismatch")
    if snapshot.get("scoring_config_sha256") != file_sha256(SCORING_CONFIG):
        errors.append("scoring configuration hash mismatch")
    if snapshot.get("query_config_sha256") != file_sha256(QUERIES_CONFIG):
        errors.append("query configuration hash mismatch")
    if errors:
        raise CertificationError("; ".join(errors))
    return execution_result(
        "verify", "success", RunContext.from_iso(snapshot["reference_time"]),
        inputs=[snapshot["snapshot_id"]], outputs=[snapshot["snapshot_id"]],
        artifacts=[{"path": artifact["path"], "sha256": artifact["sha256"]} for artifact in snapshot["artifacts"]],
    )
