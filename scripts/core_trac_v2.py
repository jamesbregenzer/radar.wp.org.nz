#!/usr/bin/env python3
"""Registry-driven Core Trac V2 source normalization."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from certification import canonical_hash

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "core-trac-v2-source-registry.json"
CORE_TRAC_FAMILY = "CORE_TRAC"
PRIMARY_ROLES = {"DIRECT_OPPORTUNITY", "SIGNAL", "RECONCILIATION"}
TICKET_ID_KEYS = ("id", "ticket", "Ticket", "ticket_id", "Ticket ID")


def load_core_trac_source_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    validate_core_trac_source_registry(registry)
    return registry


def validate_core_trac_source_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema") != "radar-core-trac-source-registry.v2":
        raise ValueError("unsupported Core Trac source registry schema")
    seen: set[str] = set()
    for source in registry.get("sources", []):
        source_id = str(source.get("id") or "")
        if not source_id or source_id in seen:
            raise ValueError(f"duplicate or missing source id: {source_id}")
        seen.add(source_id)
        role = source.get("sourceRole")
        if role not in PRIMARY_ROLES:
            raise ValueError(f"{source_id} has unsupported sourceRole")
        if not source.get("semanticMeaning"):
            raise ValueError(f"{source_id} is missing semantic meaning")
        if not source.get("candidateFamilyMappings") and role == "DIRECT_OPPORTUNITY":
            raise ValueError(f"{source_id} direct opportunity source lacks candidate-family mappings")
        if not source.get("htmlUrl") or not source.get("csvUrl"):
            raise ValueError(f"{source_id} is missing upstream URLs")
        if "locator" in source and source["locator"].get("kind") == "trac-report" and not source.get("semanticValidation"):
            raise ValueError(f"{source_id} relies on report locator without semantic validation")


def registry_revision(registry: dict[str, Any]) -> str:
    return f"core-trac-source-registry-v2-{canonical_hash(registry)[:24]}"


def source_registry_summary(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    value = registry or load_core_trac_source_registry()
    sources = value.get("sources", [])
    primary = [item for item in sources if item.get("sourceRole") in PRIMARY_ROLES]
    return {
        "schema": value["schema"],
        "version": value["version"],
        "registryRevision": registry_revision(value),
        "registryStatus": value.get("registryStatus", "IMPLEMENTED"),
        "primarySourceCount": len(primary),
        "sourceRoles": sorted({item["sourceRole"] for item in sources}),
        "primarySourceIds": [item["id"] for item in primary],
    }


def primary_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in registry.get("sources", []) if source.get("sourceRole") in PRIMARY_ROLES]


def source_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in registry.get("sources", [])}


def ticket_id_from_row(row: dict[str, Any]) -> str | None:
    for key in TICKET_ID_KEYS:
        value = str(row.get(key, "")).strip()
        if value.isdigit():
            return value
    return None


def keywords_from_row(row: dict[str, Any]) -> set[str]:
    raw = str(row.get("keywords") or row.get("Keywords") or "")
    return {item.strip().lower() for item in raw.replace(",", " ").split() if item.strip()}


def status_from_row(row: dict[str, Any]) -> str:
    return str(row.get("status") or row.get("Status") or "").strip().lower()


def semantic_validation_for(source: dict[str, Any], rows: list[dict[str, Any]], acquisition_result: str) -> dict[str, Any]:
    expectations = source.get("semanticValidation") or {}
    findings: list[str] = []
    if acquisition_result != "success":
        return {"state": "failed", "findings": ["acquisition did not succeed"]}
    if not rows and expectations.get("allowEmpty"):
        return {"state": "passed", "findings": []}
    required_fields = set(source.get("expectedFields") or [])
    for index, row in enumerate(rows):
        missing = sorted(field for field in required_fields if field not in row)
        if missing:
            findings.append(f"row {index} missing fields: {', '.join(missing)}")
        keywords = keywords_from_row(row)
        for keyword in expectations.get("requiredKeywordsAll", []):
            if keyword not in keywords:
                findings.append(f"row {index} missing required keyword {keyword}")
        any_keywords = set(expectations.get("requiredKeywordsAny", []))
        if any_keywords and not any_keywords.intersection(keywords):
            findings.append(f"row {index} missing any expected keyword from {', '.join(sorted(any_keywords))}")
        for keyword in expectations.get("forbiddenKeywordsAny", []):
            if keyword in keywords:
                findings.append(f"row {index} contains forbidden keyword {keyword}")
        if status_from_row(row) in {str(item).lower() for item in expectations.get("statusNot", [])}:
            findings.append(f"row {index} has forbidden status {status_from_row(row)}")
    return {"state": "failed" if findings else "passed", "findings": findings}


def observation_result(source: dict[str, Any], observation: dict[str, Any] | None) -> dict[str, Any]:
    if not observation:
        return {
            "state": "missing",
            "semanticValidation": {"state": "failed", "findings": ["source observation missing"]},
            "observation": None,
        }
    rows = list(observation.get("rows") or [])
    acquisition_result = str(observation.get("acquisitionResult") or "failed")
    semantic = observation.get("semanticValidation")
    if not isinstance(semantic, dict):
        semantic = semantic_validation_for(source, rows, acquisition_result)
    state = "certified" if acquisition_result == "success" and semantic.get("state") == "passed" else "degraded"
    return {"state": state, "semanticValidation": semantic, "observation": observation}


def resource_revision(resource: dict[str, Any]) -> str:
    material = {
        "schema": "radar-core-trac-resource-material.v2",
        "id": resource["id"],
        "status": resource.get("upstreamState"),
        "title": resource.get("title"),
        "sourceMemberships": [
            {
                "sourceId": item["sourceId"],
                "freshness": item["freshness"],
                "presentInCurrentObservation": item["presentInCurrentObservation"],
                "semanticValidation": item["semanticValidation"],
            }
            for item in resource.get("sourceMemberships", [])
        ],
    }
    return f"resource-revision-v2-{canonical_hash(material)[:32]}"


def candidate_id(resource: dict[str, Any]) -> str:
    families = sorted({
        mapping["familyId"]
        for membership in resource.get("sourceMemberships", [])
        for mapping in membership.get("candidateFamilyMappings", [])
    })
    material = {
        "schema": "radar-core-trac-candidate-identity.v2",
        "resourceId": resource["id"],
        "families": families,
    }
    return f"candidate:v2:{canonical_hash(material)[:32]}"


def candidate_revision(candidate: dict[str, Any]) -> str:
    material = {
        "schema": "radar-core-trac-candidate-material.v2",
        "candidateId": candidate["candidateId"],
        "resourceRevisions": candidate["resourceRevisions"],
        "sourceMemberships": candidate["sourceMemberships"],
        "familyCandidates": candidate["familyCandidates"],
        "sourceHealth": [
            {
                "sourceId": item["sourceId"],
                "state": item["state"],
                "freshness": item["freshness"],
                "failure": item["failure"],
            }
            for item in candidate["sourceHealth"]
        ],
    }
    return f"candidate-revision-v2-{canonical_hash(material)[:32]}"


def row_title(row: dict[str, Any], fallback: str) -> str:
    return str(row.get("summary") or row.get("Summary") or fallback)


def row_url(ticket_id: str) -> str:
    return f"https://core.trac.wordpress.org/ticket/{ticket_id}"


def merge_membership(resource: dict[str, Any], source: dict[str, Any], observation: dict[str, Any], row: dict[str, Any], semantic: dict[str, Any]) -> None:
    membership = {
        "sourceId": source["id"],
        "sourceRole": source["sourceRole"],
        "semanticMeaning": source["semanticMeaning"],
        "observedAt": observation.get("observedAt"),
        "sourceRevision": observation.get("sourceRevision"),
        "sourceUrl": observation.get("exactUpstreamUrl") or source.get("csvUrl"),
        "artifactHash": observation.get("artifactHash"),
        "rowHash": canonical_hash(row),
        "freshness": "current",
        "presentInCurrentObservation": True,
        "semanticValidation": semantic,
        "candidateFamilyMappings": deepcopy(source.get("candidateFamilyMappings") or []),
        "limitations": list(source.get("limitations") or []),
    }
    memberships = [item for item in resource.get("sourceMemberships", []) if item["sourceId"] != source["id"]]
    memberships.append(membership)
    resource["sourceMemberships"] = sorted(memberships, key=lambda item: item["sourceId"])


def latest_observations(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for observation in observations:
        source_id = str(observation.get("sourceId") or "")
        if not source_id:
            continue
        current = result.get(source_id)
        if current is None or str(observation.get("observedAt") or "") > str(current.get("observedAt") or ""):
            result[source_id] = observation
    return result


def preserve_previous_memberships(
    resources: dict[str, dict[str, Any]],
    previous_model: dict[str, Any] | None,
    unhealthy_source_ids: set[str],
) -> None:
    if not previous_model:
        return
    for previous in previous_model.get("resources", []):
        retained = []
        for membership in previous.get("sourceMemberships", []):
            if membership.get("sourceId") in unhealthy_source_ids:
                stale = deepcopy(membership)
                stale["freshness"] = "last-known-good"
                stale["presentInCurrentObservation"] = False
                retained.append(stale)
        if not retained:
            continue
        if previous["id"] not in resources:
            resource = deepcopy(previous)
            resource["sourceMemberships"] = []
            resources[previous["id"]] = resource
        else:
            resource = resources[previous["id"]]
        existing_source_ids = {item["sourceId"] for item in resource.get("sourceMemberships", [])}
        for membership in retained:
            if membership["sourceId"] not in existing_source_ids:
                resource.setdefault("sourceMemberships", []).append(membership)
        resource["sourceMemberships"] = sorted(resource.get("sourceMemberships", []), key=lambda item: item["sourceId"])


def source_health_record(source: dict[str, Any], result: dict[str, Any], previous_model: dict[str, Any] | None) -> dict[str, Any]:
    observation = result.get("observation")
    previous_has_source = False
    if previous_model:
        previous_has_source = any(
            membership.get("sourceId") == source["id"]
            for resource in previous_model.get("resources", [])
            for membership in resource.get("sourceMemberships", [])
        )
    if result["state"] == "certified":
        state = "certified"
        freshness = "fresh"
        failure = None
    elif previous_has_source:
        state = "degraded"
        freshness = "stale"
        failure = "SOURCE_OBSERVATION_FAILED_LAST_KNOWN_GOOD_RETAINED"
    else:
        state = "failed"
        freshness = "none"
        failure = "SOURCE_OBSERVATION_FAILED"
    return {
        "sourceId": source["id"],
        "sourceRole": source["sourceRole"],
        "state": state,
        "freshness": freshness,
        "failure": failure,
        "observedAt": observation.get("observedAt") if observation else None,
        "rowCount": observation.get("rowCount") if observation else 0,
        "semanticValidation": result["semanticValidation"],
    }


def candidate_from_resource(resource: dict[str, Any], source_health: list[dict[str, Any]]) -> dict[str, Any] | None:
    family_map: dict[str, dict[str, Any]] = {}
    for membership in resource.get("sourceMemberships", []):
        for mapping in membership.get("candidateFamilyMappings", []):
            family_id = mapping["familyId"]
            existing = family_map.get(family_id)
            confidence = mapping.get("confidence", "medium")
            if not existing or confidence == "high":
                family_map[family_id] = {
                    "familyId": family_id,
                    "confidence": confidence,
                    "sourceMembershipIds": sorted({membership["sourceId"], *(existing or {}).get("sourceMembershipIds", [])}),
                    "explanation": f"{family_id} is supported by Core Trac source memberships.",
                }
    if not family_map:
        return None
    memberships = [
        {
            "sourceId": item["sourceId"],
            "sourceRole": item["sourceRole"],
            "freshness": item["freshness"],
            "presentInCurrentObservation": item["presentInCurrentObservation"],
            "semanticMeaning": item["semanticMeaning"],
        }
        for item in resource.get("sourceMemberships", [])
    ]
    candidate = {
        "schema": "radar-core-trac-candidate.v2",
        "version": 2,
        "candidateId": candidate_id(resource),
        "opportunityId": f"opportunity:v2:{resource['id']}:core-trac-source-intelligence",
        "resourceRefs": [{"id": resource["id"], "revision": resource["materialRevision"]}],
        "resourceRevisions": [resource["materialRevision"]],
        "relationships": [],
        "sourceFamilies": [CORE_TRAC_FAMILY],
        "sourceMemberships": memberships,
        "sourceRevision": resource.get("sourceRevision"),
        "observedAt": resource.get("observedAt"),
        "freshness": "stale" if any(item["freshness"] == "last-known-good" for item in memberships) else "fresh",
        "familyCandidates": sorted(family_map.values(), key=lambda item: item["familyId"]),
        "derivedPriority": {
            "tier": "priority" if any(item["confidence"] == "high" for item in family_map.values()) else "watch",
            "score": 80 if any(item["confidence"] == "high" for item in family_map.values()) else 55,
            "explanation": "Derived from source memberships and candidate-family mappings.",
        },
        "estimatedExecutionClass": "unknown",
        "whyNow": [
            item["semanticMeaning"]
            for item in resource.get("sourceMemberships", [])
            if item["sourceRole"] == "DIRECT_OPPORTUNITY"
        ] or ["Core Trac source memberships preserve current or last-known-good opportunity evidence."],
        "sourceHealth": source_health,
        "changeInformation": {
            "resourceRevision": resource["materialRevision"],
            "sourceMembershipCount": len(memberships),
        },
    }
    candidate["candidateRevision"] = candidate_revision(candidate)
    return candidate


def normalize_core_trac_observations(
    observations: list[dict[str, Any]],
    *,
    registry: dict[str, Any] | None = None,
    previous_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = registry or load_core_trac_source_registry()
    by_source = source_by_id(value)
    latest = latest_observations(observations)
    resources: dict[str, dict[str, Any]] = {}
    health: list[dict[str, Any]] = []
    unhealthy_source_ids: set[str] = set()

    for source in primary_sources(value):
        result = observation_result(source, latest.get(source["id"]))
        health_record = source_health_record(source, result, previous_model)
        health.append(health_record)
        if health_record["state"] != "certified":
            unhealthy_source_ids.add(source["id"])
            continue
        observation = result["observation"] or {}
        semantic = result["semanticValidation"]
        for row in observation.get("rows", []):
            ticket_id = ticket_id_from_row(row)
            if not ticket_id:
                continue
            resource = resources.setdefault(ticket_id, {
                "schema": "radar-core-trac-resource.v2",
                "version": 2,
                "id": f"core-trac:{ticket_id}",
                "sourceFamily": CORE_TRAC_FAMILY,
                "resourceType": "CORE_TRAC_TICKET",
                "identity": ticket_id,
                "canonicalUrl": row_url(ticket_id),
                "url": row_url(ticket_id),
                "title": row_title(row, f"Core Trac #{ticket_id}"),
                "upstreamState": str(row.get("status") or "unknown"),
                "sourceMemberships": [],
                "observedAt": observation.get("observedAt"),
                "sourceRevision": observation.get("sourceRevision"),
            })
            resource["title"] = row_title(row, resource["title"])
            resource["upstreamState"] = str(row.get("status") or resource["upstreamState"])
            resource["observedAt"] = max(str(resource.get("observedAt") or ""), str(observation.get("observedAt") or "")) or None
            resource["sourceRevision"] = observation.get("sourceRevision") or resource.get("sourceRevision")
            merge_membership(resource, source, observation, row, semantic)

    preserve_previous_memberships(resources, previous_model, unhealthy_source_ids)
    ordered_resources = []
    for key in sorted(resources, key=lambda value_: int(value_.replace("core-trac:", "")) if value_.replace("core-trac:", "").isdigit() else value_):
        resource = resources[key]
        resource["materialRevision"] = resource_revision(resource)
        resource["revision"] = resource["materialRevision"]
        ordered_resources.append(resource)
    candidates = [
        candidate
        for resource in ordered_resources
        for candidate in [candidate_from_resource(resource, health)]
        if candidate
    ]
    return {
        "schema": "radar-core-trac-source-model.v2",
        "version": 2,
        "sourceFamily": CORE_TRAC_FAMILY,
        "registryRevision": registry_revision(value),
        "sourceHealth": sorted(health, key=lambda item: item["sourceId"]),
        "resources": ordered_resources,
        "candidates": sorted(candidates, key=lambda item: item["candidateId"]),
        "health": {
            "state": "certified" if all(item["state"] == "certified" for item in health) else "degraded",
            "failure": None if all(item["state"] == "certified" for item in health) else "ONE_OR_MORE_CORE_TRAC_SOURCES_DEGRADED",
        },
    }


def observation_fixture(
    source_id: str,
    rows: list[dict[str, Any]],
    *,
    observed_at: str = "2026-10-06T12:00:00Z",
    acquisition_result: str = "success",
) -> dict[str, Any]:
    return {
        "runId": "core-trac-v2-fixture-run",
        "scheduledSlot": "2026-10-06T12:00:00Z",
        "observedAt": observed_at,
        "startedAt": observed_at,
        "completedAt": observed_at,
        "sourceId": source_id,
        "exactUpstreamUrl": source_id,
        "artifactHash": canonical_hash({"sourceId": source_id, "rows": rows}),
        "rowCount": len(rows),
        "rows": rows,
        "acquisitionResult": acquisition_result,
        "sourceRevision": f"fixture-source-revision-{canonical_hash(rows)[:12]}",
        "publication": {"state": "fixture"},
    }
