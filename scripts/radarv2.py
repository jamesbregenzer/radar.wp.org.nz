#!/usr/bin/env python3
"""Source-neutral v2 Radar projections derived from certified public data."""

from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path
from typing import Any

from certification import canonical_hash, canonical_json, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]
WORDPRESS_DEVELOP_SOURCE = ROOT / "data" / "sources" / "wordpress-develop-github.json"

QUALIFICATION_STATES = {
    "CLEAR_OPPORTUNITY",
    "POSSIBLE_OPPORTUNITY",
    "NEEDS_MORE_EVIDENCE",
    "UPSTREAM_CHANGED",
    "LIKELY_ALREADY_COVERED",
    "NO_CLEAR_CONTRIBUTION",
}

SOURCE_COVERAGE_KEYS = {
    "ticket_fields": "trac_keywords_status_component",
    "full_ticket_discussion": "trac_ticket",
    "patches_attachments": "public_patch_or_attachment",
    "linked_pr": "wordpress_develop_pr",
    "pr_discussion_reviews": "public_pr_discussion_or_review",
    "head_diff": "changed_files_or_diff",
    "ci_test_evidence": "public_test_or_ci_evidence",
    "related_referenced_tickets": "related_or_referenced_ticket",
    "release_context": None,
}

CONTRIBUTION_FAMILIES = [
    "TEST_EXISTING_PR",
    "ADD_REGRESSION_TEST",
    "REPRODUCE_BUG",
    "VERIFY_EXISTING_PATCH",
    "REVIEW_EXISTING_PR",
    "REVIEW_API_EDGE_CASE",
    "BENCHMARK_PERFORMANCE_CHANGE",
    "VERIFY_PHP_COMPATIBILITY",
    "ACCESSIBILITY_UI_VERIFY",
    "DOCUMENT_TECHNICAL_BEHAVIOR",
    "FOLLOW_UP_AFTER_UPSTREAM_CHANGE",
    "STALE_BUT_ACTIONABLE",
    "VERIFY_FIX_AFTER_CHANGE",
    "ISOLATE_REGRESSION",
    "ADD_UNIT_TEST",
    "ADD_INTEGRATION_TEST",
    "REVIEW_BACKWARD_COMPATIBILITY",
    "RELEASE_CANDIDATE_VERIFY",
    "NO_CLEAR_CONTRIBUTION",
]


def source_family_id(value: str) -> str:
    return value.lower().replace("_", "-")


def coverage_state(covered: bool | None) -> str:
    if covered is True:
        return "COMPLETE"
    if covered is False:
        return "NONE"
    return "STALE"


def resource_id(source_family: str, identity: str) -> str:
    return f"{source_family_id(source_family)}:{identity}"


def core_trac_resource(record: dict[str, Any]) -> dict[str, Any]:
    ticket = record["ticket"]
    return {
        "id": resource_id("CORE_TRAC", ticket["id"]),
        "sourceFamily": "CORE_TRAC",
        "resourceType": "CORE_TRAC_TICKET",
        "identity": ticket["id"],
        "url": ticket["url"],
        "title": ticket["summary"],
        "state": ticket.get("status") or "unknown",
        "revision": ticket.get("modified") or record["opportunityRevision"],
        "observedFields": {
            "component": ticket.get("component"),
            "milestone": ticket.get("milestone"),
            "keywords": ticket.get("keywords", []),
            "owner": ticket.get("owner"),
            "resolution": ticket.get("resolution"),
        },
    }


def load_wordpress_develop_source(path: Path = WORDPRESS_DEVELOP_SOURCE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def github_ticket_index(source_snapshot: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not source_snapshot:
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for resource in source_snapshot.get("resources", []):
        references = resource.get("ticketReferences")
        if isinstance(references, list):
            ticket_ids = [str(item) for item in references if str(item).isdigit()]
        else:
            text = " ".join(str(resource.get(key) or "") for key in ("title", "url"))
            ticket_ids = sorted(set(re.findall(r"(?:ticket/|#)([0-9]{4,6})\b", text)))
        for ticket_id in ticket_ids:
            index.setdefault(ticket_id, []).append(resource)
    return index


def github_resource(resource: dict[str, Any]) -> dict[str, Any]:
    number = str(resource["number"])
    return {
        "id": resource_id("WORDPRESS_DEVELOP_GITHUB", number),
        "sourceFamily": "WORDPRESS_DEVELOP_GITHUB",
        "resourceType": "WORDPRESS_DEVELOP_PR",
        "identity": number,
        "url": resource["url"],
        "title": resource.get("title") or f"wordpress-develop PR #{number}",
        "state": resource.get("state") or "unknown",
        "revision": resource.get("head", {}).get("sha") or resource.get("updatedAt"),
        "observedFields": {
            "base": resource.get("base", {}),
            "head": resource.get("head", {}),
            "draft": resource.get("draft"),
            "changedFiles": resource.get("changedFiles"),
            "lastMaterialActivity": resource.get("updatedAt"),
        },
    }


def qualification_state(record: dict[str, Any], supporting_resources: list[dict[str, Any]]) -> str:
    qualification = record["qualification"]
    family = qualification["recommendedContributionClass"]
    blockers = set(qualification["eligibility"]["blockers"])
    confidence = qualification["confidence"]
    if family == "NO_CLEAR_CONTRIBUTION":
        return "NO_CLEAR_CONTRIBUTION"
    if "ticket-not-open" in blockers:
        return "UPSTREAM_CHANGED"
    if "no-clear-nonduplicative-contribution" in blockers:
        return "LIKELY_ALREADY_COVERED"
    if family == "FOLLOW_UP_AFTER_UPSTREAM_CHANGE":
        return "UPSTREAM_CHANGED"
    if not supporting_resources and qualification["source_coverage"].get("wordpress_develop_pr"):
        return "NEEDS_MORE_EVIDENCE"
    return "CLEAR_OPPORTUNITY" if confidence == "high" else "POSSIBLE_OPPORTUNITY"


def why_now(record: dict[str, Any], supporting_resources: list[dict[str, Any]]) -> list[str]:
    qualification = record["qualification"]
    ticket = record["ticket"]
    freshness = qualification["evidenceFreshness"]["state"]
    family = qualification["recommendedContributionClass"]
    reasons: list[str] = []
    if family == "FOLLOW_UP_AFTER_UPSTREAM_CHANGE":
        reasons.append("Public evidence indicates upstream work changed after prior evaluation.")
    if qualification["source_coverage"].get("public_patch_or_attachment"):
        if freshness == "stale":
            reasons.append("A public patch or attachment exists, but the evidence is stale and needs current verification.")
        else:
            reasons.append("A public patch or attachment exists and current ticket signals still support verification.")
    if supporting_resources:
        reasons.append("A linked wordpress-develop PR is visible in the certified public GitHub source snapshot.")
    if "needs-testing" in {str(item).lower() for item in ticket.get("keywords", [])}:
        reasons.append("The ticket still carries a public needs-testing signal.")
    if not reasons and family == "NO_CLEAR_CONTRIBUTION":
        reasons.append("Certified public evidence does not reveal a clear nonduplicative contribution now.")
    if not reasons:
        reasons.append(qualification["reason"])
    return reasons


def source_coverage(qualification: dict[str, Any], supporting_resources: list[dict[str, Any]]) -> dict[str, str]:
    coverage = qualification["source_coverage"]
    result: dict[str, str] = {}
    for public_name, source_key in SOURCE_COVERAGE_KEYS.items():
        if source_key is None:
            result[public_name] = "NONE"
        elif public_name == "linked_pr" and supporting_resources:
            result[public_name] = "COMPLETE"
        else:
            result[public_name] = coverage_state(bool(coverage.get(source_key)))
    return result


def qualification_dimensions(record: dict[str, Any], state: str) -> dict[str, Any]:
    qualification = record["qualification"]
    ranking = record["ranking"]
    freshness = qualification["evidenceFreshness"]
    duplication = qualification["duplication_risk"]
    actionability = "high" if state == "CLEAR_OPPORTUNITY" else "medium" if state in {"POSSIBLE_OPPORTUNITY", "UPSTREAM_CHANGED"} else "low"
    return {
        "actionability": actionability,
        "usefulnessSignal": qualification["confidence"],
        "evidenceCompleteness": "medium" if any(qualification["source_coverage"].values()) else "low",
        "freshness": freshness["state"],
        "duplicationRisk": duplication["level"],
        "effort": qualification["engineering_weight"],
        "timeliness": ranking["tier"],
        "confidence": qualification["confidence"],
    }


def v2_opportunity(record: dict[str, Any], github_index: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ticket_id = record["ticket"]["id"]
    linked_github = [github_resource(item) for item in github_index.get(ticket_id, [])]
    canonical = core_trac_resource(record)
    state = qualification_state(record, linked_github)
    dimensions = qualification_dimensions(record, state)
    revision_material = {
        "schema": "radar-opportunity-v2-material-state.v1",
        "legacyRevision": record["opportunityRevision"],
        "canonicalResource": canonical["revision"],
        "supportingResources": [
            {"id": item["id"], "revision": item["revision"], "state": item["state"]}
            for item in linked_github
        ],
        "qualificationState": state,
        "contributionFamily": record["qualification"]["recommendedContributionClass"],
        "sourceCoverage": source_coverage(record["qualification"], linked_github),
        "dimensions": dimensions,
    }
    return {
        "schema": "radar-opportunity.v2",
        "version": 2,
        "id": record["opportunityKey"],
        "revision": f"opportunity-revision-v2-{canonical_hash(revision_material)[:32]}",
        "legacyV1": {
            "opportunityKey": record["opportunityKey"],
            "opportunityRevision": record["opportunityRevision"],
            "ticketId": ticket_id,
        },
        "canonicalResource": canonical,
        "supportingResources": linked_github,
        "area": record["ticket"].get("component") or "Unknown",
        "contributionFamily": record["qualification"]["recommendedContributionClass"],
        "qualification": {
            "state": state,
            "confidence": record["qualification"]["confidence"],
            "reason": record["qualification"]["reason"],
            "whyNow": why_now(record, linked_github),
            "dimensions": dimensions,
            "limitations": limitations_for(record, linked_github),
        },
        "sourceCoverage": source_coverage(record["qualification"], linked_github),
        "freshness": record["qualification"]["evidenceFreshness"],
        "ranking": {
            "score": record["ranking"]["score"],
            "tier": record["ranking"]["tier"],
            "deterministicReasons": record["ranking"]["reasons"],
            "dimensions": dimensions,
        },
    }


def limitations_for(record: dict[str, Any], supporting_resources: list[dict[str, Any]]) -> list[str]:
    coverage = record["qualification"]["source_coverage"]
    limitations: list[str] = []
    if not coverage.get("public_pr_discussion_or_review") and not supporting_resources:
        limitations.append("No complete linked PR discussion or review evidence is certified for this opportunity.")
    if not coverage.get("changed_files_or_diff") and not supporting_resources:
        limitations.append("Changed-file or diff evidence is not certified for this opportunity.")
    if not coverage.get("public_test_or_ci_evidence"):
        limitations.append("Public CI or test evidence is not certified for this opportunity.")
    if record["qualification"]["eligibility"]["state"] != "eligible":
        limitations.append("Fresh upstream validation is still required before acting.")
    return limitations


def source_families(
    *,
    snapshot: dict[str, Any],
    collection: dict[str, Any],
    opportunities: dict[str, Any],
    wordpress_develop: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    trac_records = sum(item["row_count"] for item in collection["query_evidence"])
    trac_family = {
        "sourceFamily": "CORE_TRAC",
        "snapshotId": f"source-family-core-trac-{snapshot['collection_id'].replace('collection-v1-', '')}",
        "sourceRevision": collection["collection_id"],
        "observedTime": collection["reference_time"],
        "certifiedTime": snapshot["reference_time"],
        "completeness": "COMPLETE" if collection["state"] == "complete" else "PARTIAL",
        "freshness": "fresh",
        "recordCount": trac_records,
        "canonicalHash": snapshot["collection_sha256"],
        "limitations": [
            "Certification covers configured Core Trac CSV searches, not every WordPress Core ticket.",
            "Full ticket discussion and attachments are represented only when available in certified public fields.",
        ],
        "health": {
            "state": "certified" if collection["state"] == "complete" else "degraded",
            "failure": None if collection["state"] == "complete" else "Configured Trac collection is incomplete.",
        },
    }
    if wordpress_develop:
        github_family = {
            "sourceFamily": "WORDPRESS_DEVELOP_GITHUB",
            "snapshotId": wordpress_develop["snapshotId"],
            "sourceRevision": wordpress_develop["sourceRevision"],
            "observedTime": wordpress_develop["observedTime"],
            "certifiedTime": wordpress_develop["certifiedTime"],
            "completeness": wordpress_develop["completeness"],
            "freshness": wordpress_develop["freshness"],
            "recordCount": wordpress_develop["recordCount"],
            "canonicalHash": wordpress_develop["canonicalHash"],
            "limitations": wordpress_develop["limitations"],
            "health": wordpress_develop["health"],
        }
    else:
        github_family = {
            "sourceFamily": "WORDPRESS_DEVELOP_GITHUB",
            "snapshotId": "source-family-wordpress-develop-github-unavailable",
            "sourceRevision": None,
            "observedTime": None,
            "certifiedTime": snapshot["reference_time"],
            "completeness": "NONE",
            "freshness": "stale",
            "recordCount": 0,
            "canonicalHash": None,
            "limitations": ["No certified wordpress-develop GitHub source snapshot is available."],
            "health": {
                "state": "degraded",
                "failure": "WORDPRESS_DEVELOP_GITHUB_SOURCE_MISSING",
            },
        }
    return [trac_family, github_family]


def v2_snapshot_payload(
    snapshot: dict[str, Any],
    collection: dict[str, Any],
    v2_opportunities: list[dict[str, Any]],
    families: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "schema": "radar-snapshot.v2",
        "version": 2,
        "snapshotId": f"snapshot-v2-{snapshot['snapshot_id'].replace('snapshot-v1-', '')}",
        "legacyV1SnapshotId": snapshot["snapshot_id"],
        "collectionId": snapshot["collection_id"],
        "referenceTime": snapshot["reference_time"],
        "sourceRevision": snapshot.get("source_revision"),
        "opportunityCount": len(v2_opportunities),
        "sourceFamilies": families,
        "canonicalHashes": {
            "v1Dataset": snapshot["dataset_sha256"],
            "v1Collection": snapshot["collection_sha256"],
        },
    }
    body["canonicalHash"] = canonical_hash(body)
    return body


def changes_payload(snapshot: dict[str, Any], opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    events = []
    for opportunity in opportunities:
        state = opportunity["qualification"]["state"]
        event_class = "OPPORTUNITY_SUPPRESSED" if state == "NO_CLEAR_CONTRIBUTION" else "OPPORTUNITY_CHANGED"
        if opportunity["contributionFamily"] == "FOLLOW_UP_AFTER_UPSTREAM_CHANGE":
            event_class = "UPSTREAM_REACTIVATED"
        elif opportunity["supportingResources"]:
            event_class = "OPPORTUNITY_CHANGED"
        material = {
            "opportunity": opportunity["id"],
            "revision": opportunity["revision"],
            "class": event_class,
        }
        events.append({
            "id": f"change-v2-{canonical_hash(material)[:32]}",
            "eventClass": event_class,
            "opportunityId": opportunity["id"],
            "opportunityRevision": opportunity["revision"],
            "observedTime": snapshot["reference_time"],
            "summary": change_summary(event_class, opportunity),
            "resourceIds": [opportunity["canonicalResource"]["id"], *[item["id"] for item in opportunity["supportingResources"]]],
        })
    return {
        "schema": "radar-changes.v2",
        "version": 2,
        "snapshotId": f"snapshot-v2-{snapshot['snapshot_id'].replace('snapshot-v1-', '')}",
        "events": events,
    }


def change_summary(event_class: str, opportunity: dict[str, Any]) -> str:
    if event_class == "OPPORTUNITY_SUPPRESSED":
        return "Certified public evidence does not currently show a clear nonduplicative contribution path."
    if event_class == "UPSTREAM_REACTIVATED":
        return "Public upstream evidence changed and current follow-up may be useful."
    return "The opportunity is present in the current certified public observation set."


def taxonomy_payload() -> dict[str, Any]:
    return {
        "schema": "radar-taxonomy.v2",
        "version": 2,
        "qualificationStates": sorted(QUALIFICATION_STATES),
        "contributionFamilies": CONTRIBUTION_FAMILIES,
        "sourceFamilies": ["CORE_TRAC", "WORDPRESS_DEVELOP_GITHUB", "GUTENBERG", "WORDPRESS_TEST_RELEASE_SIGNALS"],
        "coverageStates": ["COMPLETE", "PARTIAL", "NONE", "STALE"],
    }


def diagnostics_payload(opportunities: list[dict[str, Any]], families: list[dict[str, Any]]) -> dict[str, Any]:
    qualification = Counter(item["qualification"]["state"] for item in opportunities)
    by_family = Counter(item["contributionFamily"] for item in opportunities)
    coverage = Counter()
    for opportunity in opportunities:
        for key, state in opportunity["sourceCoverage"].items():
            coverage[f"{key}:{state}"] += 1
    return {
        "schema": "radar-diagnostics.v2",
        "version": 2,
        "rawResourcesObserved": sum(family["recordCount"] for family in families),
        "uniqueOpportunities": len(opportunities),
        "qualificationDistribution": counted(qualification),
        "contributionFamilyDistribution": counted(by_family),
        "sourceFamilyDistribution": counted(Counter(family["sourceFamily"] for family in families)),
        "freshnessDistribution": counted(Counter(item["freshness"]["state"] for item in opportunities)),
        "evidenceCompleteness": counted(coverage),
        "suppressionReasons": counted(Counter(reason for item in opportunities for reason in item["qualification"]["limitations"] if item["qualification"]["state"] == "NO_CLEAR_CONTRIBUTION")),
    }


def counted(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"key": key, "count": counter[key]} for key in sorted(counter)]


def project_v2(
    *,
    snapshot: dict[str, Any],
    collection: dict[str, Any],
    opportunities: dict[str, Any],
    contributions: dict[str, Any],
    wordpress_develop: dict[str, Any] | None = None,
) -> dict[str, bytes]:
    github_index = github_ticket_index(wordpress_develop)
    v2_opportunities = [v2_opportunity(record, github_index) for record in opportunities["opportunities"]]
    families = source_families(
        snapshot=snapshot,
        collection=collection,
        opportunities=opportunities,
        wordpress_develop=wordpress_develop,
    )
    v2_snapshot = v2_snapshot_payload(snapshot, collection, v2_opportunities, families)
    health = {
        "schema": "radar-health.v2",
        "version": 2,
        "status": "healthy" if all(family["health"]["state"] == "certified" for family in families) else "degraded",
        "snapshotId": v2_snapshot["snapshotId"],
        "legacyV1SnapshotId": snapshot["snapshot_id"],
        "sourceFamilies": families,
        "opportunityCount": len(v2_opportunities),
    }
    sources = {
        "schema": "radar-sources.v2",
        "version": 2,
        "snapshotId": v2_snapshot["snapshotId"],
        "sourceFamilies": families,
    }
    opportunity_set = {
        "schema": "radar-opportunity-set.v2",
        "version": 2,
        "snapshotId": v2_snapshot["snapshotId"],
        "opportunities": v2_opportunities,
    }
    outcomes = {
        "schema": "radar-outcomes.v2",
        "version": 2,
        "snapshotId": v2_snapshot["snapshotId"],
        "outcomes": contributions.get("contributions", []),
        "limitations": ["Outcome attribution is conservative and based only on public contribution evidence."],
    }
    payloads = {
        "health.json": health,
        "sources.json": sources,
        "snapshot.json": v2_snapshot,
        "opportunities.json": opportunity_set,
        "changes.json": changes_payload(snapshot, v2_opportunities),
        "contributions.json": {
            "schema": "radar-contributions.v2",
            "version": 2,
            "snapshotId": v2_snapshot["snapshotId"],
            "contributions": contributions.get("contributions", []),
        },
        "outcomes.json": outcomes,
        "taxonomy.json": taxonomy_payload(),
        "diagnostics.json": diagnostics_payload(v2_opportunities, families),
    }
    return {name: canonical_json(payload) for name, payload in payloads.items()}


def payload_hashes(payloads: dict[str, bytes]) -> dict[str, str]:
    return {name: sha256_bytes(value) for name, value in sorted(payloads.items())}
