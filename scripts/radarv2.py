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
GUTENBERG_SOURCE = ROOT / "data" / "sources" / "gutenberg-github.json"
CORE_TRAC_FAMILY = "CORE_TRAC"
WORDPRESS_DEVELOP_FAMILY = "WORDPRESS_DEVELOP_GITHUB"
GUTENBERG_FAMILY = "GUTENBERG"
UNKNOWN_OBSERVATION = "unknown"

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

LEGACY_SIGNAL_FAMILIES = [
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

CONTRIBUTION_FAMILY_REGISTRY = [
    ("CORE_CODE_REVIEW", "Core code review", "Review a public Core code change or API behavior."),
    ("CORE_PATCH_TEST", "Core patch test", "Test an existing public Core patch or pull request."),
    ("CORE_BUG_REPRODUCTION", "Core bug reproduction", "Reproduce and diagnose a public Core bug report."),
    ("CORE_REGRESSION_TEST", "Core regression test", "Add or verify missing regression coverage for Core."),
    ("CORE_PATCH_IMPLEMENTATION", "Core patch implementation", "Prepare or improve a public Core patch."),
    ("CORE_AUTOMATED_TEST", "Core automated test", "Add or review automated Core test coverage."),
    ("CORE_BUG_GARDENING", "Core bug gardening", "Clarify, triage, or refresh a public Core bug."),
    ("CORE_INLINE_DOCS", "Core inline docs", "Review or improve Core inline technical documentation."),
    ("GUTENBERG_CODE_REVIEW", "Gutenberg code review", "Review a public Gutenberg code change."),
    ("GUTENBERG_TEST", "Gutenberg test", "Test a public Gutenberg issue or pull request."),
    ("GUTENBERG_REPRODUCTION", "Gutenberg reproduction", "Reproduce and diagnose a public Gutenberg issue."),
    ("GUTENBERG_PATCH", "Gutenberg patch", "Prepare or improve a public Gutenberg patch."),
    ("ACCESSIBILITY_TEST", "Accessibility test", "Test public accessibility behavior or impact."),
    ("BETA_RC_TEST", "Beta or release-candidate test", "Verify public beta or release-candidate behavior."),
    ("PERFORMANCE_INVESTIGATION", "Performance investigation", "Investigate public performance-sensitive behavior."),
    ("DOCS_REVIEW", "Documentation review", "Review public documentation or technical guidance."),
    ("HANDBOOK_UPDATE", "Handbook update", "Update public handbook material."),
    ("PATHWAY_REVIEW", "Pathway review", "Review public contribution pathway material."),
    ("LEARN_TECHNICAL_REVIEW", "Learn technical review", "Review public Learn WordPress technical material."),
    ("THEME_CHECK_CODE", "Theme check code", "Review or improve public Theme Check code."),
    ("THEME_CHECK_TRIAGE", "Theme check triage", "Triage public Theme Check issues."),
    ("THEME_REVIEW", "Theme review", "Review a public theme contribution."),
]

CONTRIBUTION_FAMILIES = [family_id for family_id, _, _ in CONTRIBUTION_FAMILY_REGISTRY]

SCORE_DIMENSIONS = [
    "upstreamDemandStrength",
    "expectedUpstreamImpact",
    "jamesAffinity",
    "noveltyConfidence",
    "evidenceFeasibility",
    "timeliness",
    "estimatedExecutionCost",
    "deliveryReputationalRisk",
]

WAVE2_SOURCE_FAMILIES = [
    "MAKE_TEST_RELEASE_SIGNALS",
    "CONTRIBUTOR_PATHWAYS",
    "CORE_DEVELOPER_DOCS",
    "ACCESSIBILITY_REQUESTS",
    "THEME_CHECK_GITHUB",
    "MAKE_THEMES_REQUESTS",
    "WORDPRESS_RELEASES",
]

WAVE2_SOURCE_LABELS = {
    "MAKE_TEST_RELEASE_SIGNALS": "Make Test calls for testing and release signals",
    "CONTRIBUTOR_PATHWAYS": "public Contributor Pathways material",
    "CORE_DEVELOPER_DOCS": "Core and developer documentation opportunities",
    "ACCESSIBILITY_REQUESTS": "public accessibility contribution and test requests",
    "THEME_CHECK_GITHUB": "Theme Check issues and pull requests",
    "MAKE_THEMES_REQUESTS": "Make Themes public testing and review requests",
    "WORDPRESS_RELEASES": "WordPress beta, release-candidate, and development builds",
}

WAVE2_SOURCE_PATHS = {
    family_name: ROOT / "data" / "sources" / f"{family_name.lower().replace('_', '-')}.json"
    for family_name in WAVE2_SOURCE_FAMILIES
}


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


def material_revision(preimage: dict[str, Any], prefix: str) -> str:
    return f"{prefix}-{canonical_hash(preimage)[:32]}"


def deterministic_hash(preimage: dict[str, Any]) -> str:
    return canonical_hash(preimage)


def resource_payload(
    *,
    source_family: str,
    resource_type: str,
    identity: str,
    canonical_url: str,
    title: str,
    upstream_state: str,
    observed_time: str | None,
    source_family_snapshot_id: str,
    source_revision: str | None,
    provenance: list[dict[str, Any]],
    completeness: str,
    limitations: list[str],
    observed_fields: dict[str, Any],
) -> dict[str, Any]:
    identity_value = resource_id(source_family, identity)
    revision_preimage = {
        "schema": "radar-resource-material-state.v2",
        "id": identity_value,
        "sourceFamily": source_family,
        "resourceType": resource_type,
        "canonicalUrl": canonical_url,
        "upstreamState": upstream_state,
        "sourceRevision": source_revision,
        "observedFields": observed_fields,
    }
    material = material_revision(revision_preimage, "resource-revision-v2")
    resource = {
        "schema": "radar-resource.v2",
        "version": 2,
        "id": identity_value,
        "sourceFamily": source_family,
        "resourceType": resource_type,
        "identity": identity,
        "canonicalUrl": canonical_url,
        "url": canonical_url,
        "title": title,
        "upstreamState": upstream_state,
        "state": upstream_state,
        "materialRevision": material,
        "revision": material,
        "observedTime": observed_time,
        "sourceFamilySnapshotId": source_family_snapshot_id,
        "sourceRevision": source_revision,
        "provenance": provenance,
        "completeness": completeness,
        "limitations": limitations,
        "observedFields": observed_fields,
    }
    resource["deterministicHash"] = deterministic_hash(resource)
    return resource


def core_trac_resource(record: dict[str, Any], source_family: dict[str, Any] | None = None) -> dict[str, Any]:
    ticket = record["ticket"]
    family = source_family or {}
    source_identity = record.get("discovery", {}).get("sources", [{}])[0].get("source_identity")
    provenance = []
    for source in record.get("discovery", {}).get("sources", []):
        provenance.append({
            "source": "core.trac.wordpress.org/query",
            "querySlug": source.get("query_slug"),
            "sourceIdentity": source.get("source_identity"),
            "track": source.get("track"),
        })
    if not provenance:
        provenance = [{"source": "core.trac.wordpress.org/query", "sourceIdentity": source_identity}]
    return resource_payload(
        source_family=CORE_TRAC_FAMILY,
        resource_type="CORE_TRAC_TICKET",
        identity=ticket["id"],
        canonical_url=ticket["url"],
        title=ticket["summary"],
        upstream_state=ticket.get("status") or "unknown",
        observed_time=family.get("observedTime"),
        source_family_snapshot_id=family.get("snapshotId") or UNKNOWN_OBSERVATION,
        source_revision=family.get("sourceRevision") or ticket.get("modified") or record["opportunityRevision"],
        provenance=provenance,
        completeness=family.get("completeness") or "PARTIAL",
        limitations=[
            "Core Trac CSV fields are observed; full ticket discussion, attachments, and changesets require bounded enrichment before action.",
        ],
        observed_fields={
            "component": ticket.get("component"),
            "milestone": ticket.get("milestone"),
            "keywords": ticket.get("keywords", []),
            "owner": ticket.get("owner"),
            "resolution": ticket.get("resolution"),
        },
    )


def load_wordpress_develop_source(path: Path = WORDPRESS_DEVELOP_SOURCE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_gutenberg_source(path: Path = GUTENBERG_SOURCE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_wave2_sources(paths: dict[str, Path] | None = None) -> dict[str, dict[str, Any] | None]:
    configured = paths or WAVE2_SOURCE_PATHS
    result: dict[str, dict[str, Any] | None] = {}
    for family_name in WAVE2_SOURCE_FAMILIES:
        path = configured.get(family_name)
        result[family_name] = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None
    return result


def github_ticket_index(source_snapshot: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not source_snapshot:
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for resource in source_snapshot.get("resources", []):
        references = resource.get("ticketReferences")
        if isinstance(references, list):
            ticket_ids = [str(item) for item in references if str(item).isdigit()]
        else:
            ticket_ids = []
        for ticket_id in ticket_ids:
            index.setdefault(ticket_id, []).append(resource)
    return index


def github_resource(resource: dict[str, Any], source_family: dict[str, Any] | None = None, family_name: str = WORDPRESS_DEVELOP_FAMILY) -> dict[str, Any]:
    number = str(resource["number"])
    family = source_family or {}
    resource_type = str(resource.get("resourceType") or "GITHUB_RESOURCE")
    identity = number if family_name == WORDPRESS_DEVELOP_FAMILY else f"{'pull' if resource_type.endswith('_PR') else 'issue'}/{number}"
    limitations = [
        "GitHub snapshot is bounded by the declared public source scope; absence from the window is not closure, merge, or supersession.",
    ]
    if resource.get("ambiguousTicketReferences"):
        limitations.append("Bare GitHub issue-style numeric references are recorded as ambiguous and are not treated as Core Trac links.")
    source_slug = "WordPress/wordpress-develop" if family_name == WORDPRESS_DEVELOP_FAMILY else "WordPress/gutenberg"
    return resource_payload(
        source_family=family_name,
        resource_type=resource_type,
        identity=identity,
        canonical_url=resource["url"],
        title=resource.get("title") or f"{source_slug} #{number}",
        upstream_state=resource.get("state") or "unknown",
        observed_time=family.get("observedTime") or resource.get("updatedAt"),
        source_family_snapshot_id=family.get("snapshotId") or UNKNOWN_OBSERVATION,
        source_revision=resource.get("head", {}).get("sha") or resource.get("updatedAt"),
        provenance=[{
            "source": f"api.github.com/repos/{source_slug}",
            "sourceIdentity": identity,
            "scope": "bounded-open-updated-desc-window",
        }],
        completeness=family.get("completeness") or "PARTIAL",
        limitations=limitations,
        observed_fields={
            "bodyExcerptHash": canonical_hash({"body": (resource.get("body") or "")[:2000]}),
            "labels": resource.get("labels", []),
            "comments": resource.get("comments"),
            "requestedReviewers": resource.get("requestedReviewers", []),
            "requestedTeams": resource.get("requestedTeams", []),
            "milestone": resource.get("milestone"),
            "base": resource.get("base", {}),
            "head": resource.get("head", {}),
            "draft": resource.get("draft"),
            "changedFiles": resource.get("changedFiles"),
            "lastMaterialActivity": resource.get("updatedAt"),
            "ticketReferences": resource.get("ticketReferences", []),
            "ambiguousTicketReferences": resource.get("ambiguousTicketReferences", []),
        },
    )


def wave2_resource(resource: dict[str, Any], source_family: dict[str, Any] | None, family_name: str) -> dict[str, Any]:
    family = source_family or {}
    receipt = family.get("retrievalReceipt") or {}
    return resource_payload(
        source_family=family_name,
        resource_type=str(resource.get("resourceType") or "PUBLIC_SOURCE_RESOURCE"),
        identity=str(resource["nativeIdentity"]),
        canonical_url=str(resource["url"]),
        title=str(resource.get("title") or resource["nativeIdentity"]),
        upstream_state=str(resource.get("state") or "unknown"),
        observed_time=family.get("observedTime") or resource.get("updatedAt"),
        source_family_snapshot_id=family.get("snapshotId") or UNKNOWN_OBSERVATION,
        source_revision=resource.get("sourceRevision") or family.get("sourceRevision"),
        provenance=[{
            "source": family.get("authoritativeSource"),
            "sourceIdentity": resource["nativeIdentity"],
            "retrievalReceiptId": receipt.get("receiptId"),
            "retrievalReceiptHash": receipt.get("canonicalHash"),
        }],
        completeness=family.get("completeness") or "PARTIAL",
        limitations=list(family.get("limitations") or []),
        observed_fields={
            "nativeId": resource.get("nativeId"),
            "number": resource.get("number"),
            "createdAt": resource.get("createdAt"),
            "updatedAt": resource.get("updatedAt"),
            "labels": resource.get("labels", []),
            "assignees": resource.get("assignees", []),
            "requestedReviewers": resource.get("requestedReviewers", []),
            "requestedTeams": resource.get("requestedTeams", []),
            "draft": resource.get("draft"),
            "bodyHash": resource.get("bodyHash"),
            "bodyExcerpt": resource.get("bodyExcerpt"),
            "outboundLinks": resource.get("outboundLinks", []),
            "candidateSignals": resource.get("candidateSignals", []),
        },
    )


def source_resource(resource: dict[str, Any], source_family: dict[str, Any] | None, family_name: str) -> dict[str, Any]:
    if family_name in {WORDPRESS_DEVELOP_FAMILY, GUTENBERG_FAMILY}:
        return github_resource(resource, source_family, family_name)
    return wave2_resource(resource, source_family, family_name)


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
        elif public_name == "full_ticket_discussion":
            result[public_name] = "PARTIAL" if coverage.get(source_key) else "NONE"
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


def opportunity_id(canonical_resource: dict[str, Any], contribution_family: str, missing_increment: str) -> str:
    slug = contribution_family.lower().replace("_", "-")
    increment_slug = re.sub(r"[^a-z0-9]+", "-", missing_increment.lower()).strip("-")[:48] or "missing-increment"
    return f"opportunity:v2:{canonical_resource['id']}:{slug}:{increment_slug}"


def missing_increment_label(record: dict[str, Any], state: str) -> str:
    family = record["qualification"]["recommendedContributionClass"]
    if state == "NO_CLEAR_CONTRIBUTION":
        return "No clear public contribution increment from certified evidence"
    labels = {
        "TEST_EXISTING_PR": "Test the current linked pull request or patch",
        "ADD_REGRESSION_TEST": "Add missing regression test coverage",
        "REPRODUCE_BUG": "Reproduce and diagnose the reported behavior",
        "VERIFY_EXISTING_PATCH": "Verify the existing public patch",
        "REVIEW_EXISTING_PR": "Review the linked public pull request",
        "REVIEW_API_EDGE_CASE": "Review API edge-case behavior",
        "BENCHMARK_PERFORMANCE_CHANGE": "Benchmark the performance-sensitive change",
        "VERIFY_PHP_COMPATIBILITY": "Verify PHP compatibility impact",
        "ACCESSIBILITY_UI_VERIFY": "Verify accessibility or UI behavior",
        "DOCUMENT_TECHNICAL_BEHAVIOR": "Document the technical behavior",
        "FOLLOW_UP_AFTER_UPSTREAM_CHANGE": "Reread and follow up after upstream change",
        "STALE_BUT_ACTIONABLE": "Refresh stale but actionable public evidence",
        "VERIFY_FIX_AFTER_CHANGE": "Verify the fix after upstream change",
        "ISOLATE_REGRESSION": "Isolate the regression source",
        "ADD_UNIT_TEST": "Add missing unit test coverage",
        "ADD_INTEGRATION_TEST": "Add missing integration test coverage",
        "REVIEW_BACKWARD_COMPATIBILITY": "Review backward compatibility impact",
        "RELEASE_CANDIDATE_VERIFY": "Verify release-candidate behavior",
    }
    return labels.get(family, record["qualification"]["reason"])


def registered_family_for(source_family: str, signal_family: str) -> str | None:
    if signal_family == "NO_CLEAR_CONTRIBUTION":
        return None
    if signal_family in {"ACCESSIBILITY_UI_VERIFY"}:
        return "ACCESSIBILITY_TEST"
    if signal_family in {"BENCHMARK_PERFORMANCE_CHANGE"}:
        return "PERFORMANCE_INVESTIGATION"
    if signal_family in {"DOCUMENT_TECHNICAL_BEHAVIOR"}:
        return "DOCS_REVIEW" if source_family != CORE_TRAC_FAMILY else "CORE_INLINE_DOCS"
    if signal_family in {"RELEASE_CANDIDATE_VERIFY"}:
        return "BETA_RC_TEST"
    if source_family == GUTENBERG_FAMILY:
        mapping = {
            "TEST_EXISTING_PR": "GUTENBERG_TEST",
            "VERIFY_EXISTING_PATCH": "GUTENBERG_TEST",
            "ADD_REGRESSION_TEST": "GUTENBERG_TEST",
            "ADD_UNIT_TEST": "GUTENBERG_TEST",
            "ADD_INTEGRATION_TEST": "GUTENBERG_TEST",
            "REPRODUCE_BUG": "GUTENBERG_REPRODUCTION",
            "ISOLATE_REGRESSION": "GUTENBERG_REPRODUCTION",
            "REVIEW_EXISTING_PR": "GUTENBERG_CODE_REVIEW",
            "REVIEW_API_EDGE_CASE": "GUTENBERG_CODE_REVIEW",
            "REVIEW_BACKWARD_COMPATIBILITY": "GUTENBERG_CODE_REVIEW",
            "VERIFY_PHP_COMPATIBILITY": "GUTENBERG_CODE_REVIEW",
            "STALE_BUT_ACTIONABLE": "GUTENBERG_TEST",
            "FOLLOW_UP_AFTER_UPSTREAM_CHANGE": "GUTENBERG_TEST",
            "VERIFY_FIX_AFTER_CHANGE": "GUTENBERG_TEST",
        }
    else:
        mapping = {
            "TEST_EXISTING_PR": "CORE_PATCH_TEST",
            "VERIFY_EXISTING_PATCH": "CORE_PATCH_TEST",
            "ADD_REGRESSION_TEST": "CORE_REGRESSION_TEST",
            "ADD_UNIT_TEST": "CORE_AUTOMATED_TEST",
            "ADD_INTEGRATION_TEST": "CORE_AUTOMATED_TEST",
            "REPRODUCE_BUG": "CORE_BUG_REPRODUCTION",
            "ISOLATE_REGRESSION": "CORE_BUG_REPRODUCTION",
            "REVIEW_EXISTING_PR": "CORE_CODE_REVIEW",
            "REVIEW_API_EDGE_CASE": "CORE_CODE_REVIEW",
            "REVIEW_BACKWARD_COMPATIBILITY": "CORE_CODE_REVIEW",
            "VERIFY_PHP_COMPATIBILITY": "CORE_CODE_REVIEW",
            "STALE_BUT_ACTIONABLE": "CORE_BUG_GARDENING",
            "FOLLOW_UP_AFTER_UPSTREAM_CHANGE": "CORE_BUG_GARDENING",
            "VERIFY_FIX_AFTER_CHANGE": "CORE_PATCH_TEST",
        }
    return mapping.get(signal_family)


def family_candidates(source_family: str, signal_family: str, confidence: str, reason: str) -> list[dict[str, Any]]:
    family = registered_family_for(source_family, signal_family)
    if not family:
        return []
    return [{
        "familyId": family,
        "confidence": confidence,
        "sourceSignal": signal_family,
        "sourceEvidence": [reason],
        "explanation": f"Public evidence maps the observed {signal_family} signal to {family}.",
    }]


def score_item(value: str, confidence: str, source_evidence: list[str], explanation: str) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "sourceEvidence": source_evidence,
        "explanation": explanation,
    }


def opportunity_score_vector(opportunity: dict[str, Any]) -> dict[str, Any]:
    qualification = opportunity["qualification"]
    ranking = opportunity["ranking"]
    dimensions = ranking.get("dimensions", {})
    evidence = [
        qualification.get("reason") or "Public source evidence supports the current candidate state.",
        *qualification.get("whyNow", []),
    ]
    actionability = dimensions.get("actionability", "unknown")
    confidence = dimensions.get("confidence", qualification.get("confidence", "unknown"))
    duplication = dimensions.get("duplicationRisk", qualification.get("duplicationRisk", "unknown"))
    effort = dimensions.get("effort", "unknown")
    freshness = dimensions.get("freshness", "unknown")
    return {
        "schema": "radar-score-vector.v1",
        "version": 1,
        "dimensions": {
            "upstreamDemandStrength": score_item(actionability, confidence, evidence, "Derived from public need, labels, keywords, state, and actionability signals."),
            "expectedUpstreamImpact": score_item(dimensions.get("usefulnessSignal", "unknown"), confidence, evidence, "Estimated only from public usefulness signals; no private execution judgment is included."),
            "jamesAffinity": score_item("unknown", "low", [], "Radar does not own final person-specific usefulness decisions."),
            "noveltyConfidence": score_item(dimensions.get("noveltySignal", "known-public-signal"), confidence, evidence, "Reflects whether the candidate is source-native or linked to existing public evidence."),
            "evidenceFeasibility": score_item(dimensions.get("evidenceCompleteness", "unknown"), confidence, evidence, "Derived from observed public source coverage."),
            "timeliness": score_item(dimensions.get("timeliness", ranking.get("tier", "unknown")), confidence, evidence, "Derived from public freshness and ranking tier."),
            "estimatedExecutionCost": score_item(effort, confidence, evidence, "Estimated from public scope and known setup burden signals."),
            "deliveryReputationalRisk": score_item(duplication, confidence, evidence, "Derived from duplicate/already-covered risk and public uncertainty."),
        },
        "derivedPriority": {
            "score": ranking.get("score"),
            "tier": ranking.get("tier"),
            "explanation": "Derived priority is for ordering only and cannot override eligibility, safety, or source-integrity gates.",
            "reasons": ranking.get("deterministicReasons", []),
        },
    }


def attach_candidate_model(opportunity: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(opportunity))
    signal_family = updated["contributionFamily"]
    source_family = updated["canonicalResource"]["sourceFamily"]
    confidence = updated["qualification"].get("confidence", "unknown")
    reason = updated["qualification"].get("reason", "")
    updated.setdefault("legacySignalFamily", signal_family)
    updated.setdefault("familyCandidates", family_candidates(source_family, signal_family, confidence, reason))
    updated["scoreVector"] = opportunity_score_vector(updated)
    updated["eligibilityGate"] = {
        "state": "failed" if updated["qualification"]["state"] in {"NO_CLEAR_CONTRIBUTION", "LIKELY_ALREADY_COVERED"} else "passed",
        "sourceIntegrity": "passed",
        "safety": "passed",
        "explanation": "Candidate eligibility is based only on public source evidence and suppression signals.",
    }
    return updated


def v2_opportunity(
    record: dict[str, Any],
    github_index: dict[str, list[dict[str, Any]]],
    families_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ticket_id = record["ticket"]["id"]
    linked_github = [github_resource(item, families_by_source.get(WORDPRESS_DEVELOP_FAMILY)) for item in github_index.get(ticket_id, [])]
    canonical = core_trac_resource(record, families_by_source.get(CORE_TRAC_FAMILY))
    state = qualification_state(record, linked_github)
    dimensions = qualification_dimensions(record, state)
    missing_increment = missing_increment_label(record, state)
    contribution_family = record["qualification"]["recommendedContributionClass"]
    identity = opportunity_id(canonical, contribution_family, missing_increment)
    revision_material = {
        "schema": "radar-opportunity-v2-material-state.v1",
        "legacyRevision": record["opportunityRevision"],
        "canonicalResource": canonical["revision"],
        "supportingResources": [
            {"id": item["id"], "revision": item["revision"], "state": item["state"]}
            for item in linked_github
        ],
        "qualificationState": state,
        "contributionFamily": contribution_family,
        "missingIncrement": missing_increment,
        "sourceCoverage": source_coverage(record["qualification"], linked_github),
        "dimensions": dimensions,
    }
    return {
        "schema": "radar-opportunity.v2",
        "version": 2,
        "id": identity,
        "revision": f"opportunity-revision-v2-{canonical_hash(revision_material)[:32]}",
        "legacyV1": {
            "opportunityKey": record["opportunityKey"],
            "opportunityRevision": record["opportunityRevision"],
            "ticketId": ticket_id,
        },
        "identity": {
            "canonicalResourceId": canonical["id"],
            "contributionFamily": contribution_family,
            "missingIncrement": missing_increment,
        },
        "canonicalResource": canonical,
        "supportingResources": linked_github,
        "area": record["ticket"].get("component") or "Unknown",
        "contributionFamily": contribution_family,
        "likelyMissingIncrement": missing_increment,
        "requiresLiveRevalidation": True,
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


def parse_github_time(value: str | None) -> int:
    if not value:
        return 9999
    from datetime import datetime, timezone

    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return max(0, (now - observed).days)


def label_set(resource: dict[str, Any]) -> set[str]:
    return {str(label).lower() for label in resource.get("labels", [])}


def contains_any(values: set[str], needles: tuple[str, ...]) -> bool:
    joined = " ".join(sorted(values))
    return any(needle in joined for needle in needles)


def native_signal(resource: dict[str, Any], family_name: str) -> dict[str, Any] | None:
    labels = label_set(resource)
    title_body = f"{resource.get('title') or ''} {resource.get('body') or ''}".lower()
    resource_type = str(resource.get("resourceType") or "")
    age_days = parse_github_time(resource.get("updatedAt"))
    is_pr = resource_type.endswith("_PR")
    if is_pr and resource.get("draft"):
        return {
            "state": "NO_CLEAR_CONTRIBUTION",
            "family": "NO_CLEAR_CONTRIBUTION",
            "increment": "No clear public contribution increment for draft pull request",
            "confidence": "low",
            "reason": "The public pull request is still marked draft.",
            "actionability": "low",
        }
    if contains_any(labels, ("needs unit test", "needs tests", "needs testing", "needs e2e", "test needed")) and is_pr:
        return {
            "state": "CLEAR_OPPORTUNITY",
            "family": "TEST_EXISTING_PR",
            "increment": "Test the current public pull request",
            "confidence": "high",
            "reason": "Public labels indicate testing is needed for the current pull request.",
            "actionability": "high",
        }
    if contains_any(labels, ("needs review", "needs technical review", "needs code review")) or resource.get("requestedReviewers") or resource.get("requestedTeams"):
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "REVIEW_EXISTING_PR" if is_pr else "REVIEW_API_EDGE_CASE",
            "increment": "Review the current public change",
            "confidence": "medium",
            "reason": "Public reviewer or review-needed metadata is present.",
            "actionability": "medium",
        }
    if "needs accessibility feedback" in " ".join(labels) or "accessibility" in title_body:
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "ACCESSIBILITY_UI_VERIFY",
            "increment": "Verify accessibility impact from the public issue or pull request",
            "confidence": "medium",
            "reason": "Public labels or text indicate accessibility review may be useful.",
            "actionability": "medium",
        }
    if "performance" in title_body or contains_any(labels, ("performance",)):
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "BENCHMARK_PERFORMANCE_CHANGE",
            "increment": "Benchmark the public performance-sensitive change",
            "confidence": "medium",
            "reason": "Public title or labels indicate performance-sensitive work.",
            "actionability": "medium",
        }
    if "rest api" in title_body or " api " in f" {title_body} " or contains_any(labels, ("rest api", "api")):
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "REVIEW_API_EDGE_CASE",
            "increment": "Review API edge-case behavior",
            "confidence": "medium",
            "reason": "Public title or labels indicate API-sensitive work.",
            "actionability": "medium",
        }
    if contains_any(labels, ("type bug", "[type] bug", "bug")) and not is_pr:
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "REPRODUCE_BUG",
            "increment": "Reproduce and diagnose the public bug report",
            "confidence": "medium",
            "reason": "Public issue labels indicate a bug that may need reproduction or diagnosis.",
            "actionability": "medium",
        }
    if age_days >= 21 and (resource.get("comments") or 0) > 0:
        return {
            "state": "POSSIBLE_OPPORTUNITY",
            "family": "STALE_BUT_ACTIONABLE",
            "increment": "Refresh stale but active public discussion",
            "confidence": "medium",
            "reason": f"The public resource has discussion but has not been materially updated for {age_days} days.",
            "actionability": "medium",
        }
    if family_name == GUTENBERG_FAMILY and contains_any(labels, ("needs design", "needs accessibility feedback")):
        return {
            "state": "NEEDS_MORE_EVIDENCE",
            "family": "NO_CLEAR_CONTRIBUTION",
            "increment": "Needs more public evidence before a contribution increment is clear",
            "confidence": "low",
            "reason": "Public labels show a need for input, but Radar has not observed enough evidence to define a concrete contribution.",
            "actionability": "low",
        }
    return None


def native_source_coverage(resource: dict[str, Any], signal: dict[str, Any]) -> dict[str, str]:
    labels = "COMPLETE" if resource.get("labels") else "NONE"
    discussion_observation = resource.get("discussion") or {}
    review_observation = resource.get("reviews") or {}
    checks_observation = resource.get("checks") or {}
    diff_observation = resource.get("diffIdentity") or {}
    discussion = "COMPLETE" if discussion_observation.get("observed") and not discussion_observation.get("truncated") else "PARTIAL" if discussion_observation.get("observed") else "NONE"
    review = "COMPLETE" if review_observation.get("observed") and not review_observation.get("truncated") else "PARTIAL" if review_observation.get("observed") else "NONE"
    checks = "COMPLETE" if checks_observation.get("observed") and not checks_observation.get("truncated") else "PARTIAL" if checks_observation.get("observed") else "NONE"
    diff = "COMPLETE" if diff_observation.get("observed") and not diff_observation.get("truncated") else "PARTIAL" if diff_observation.get("observed") else "NONE"
    return {
        "source_metadata": "COMPLETE",
        "github_labels": labels,
        "public_discussion": discussion,
        "review_request": review,
        "head_base": "COMPLETE" if resource.get("head") or resource.get("base") else "NONE",
        "ci_test_evidence": checks,
        "diff_identity": diff,
        "relationship_context": "NONE",
    }


def native_opportunity(resource: dict[str, Any], family_record: dict[str, Any], family_name: str) -> dict[str, Any] | None:
    signal = native_signal(resource, family_name)
    if not signal:
        return None
    canonical = github_resource(resource, family_record, family_name)
    state = signal["state"]
    contribution_family = signal["family"]
    missing_increment = signal["increment"]
    dimensions = {
        "actionability": signal["actionability"],
        "usefulnessSignal": signal["confidence"],
        "evidenceCompleteness": "medium" if state in {"CLEAR_OPPORTUNITY", "POSSIBLE_OPPORTUNITY"} else "low",
        "freshness": family_record.get("freshness") or "stale",
        "duplicationRisk": "medium",
        "noveltySignal": "source-native",
        "effort": "medium",
        "timeliness": "near-term" if state == "CLEAR_OPPORTUNITY" else "watch",
        "confidence": signal["confidence"],
    }
    coverage = native_source_coverage(resource, signal)
    revision_material = {
        "schema": "radar-native-opportunity-v2-material-state.v1",
        "canonicalResource": canonical["revision"],
        "qualificationState": state,
        "contributionFamily": contribution_family,
        "missingIncrement": missing_increment,
        "sourceCoverage": coverage,
        "dimensions": dimensions,
    }
    limitations = [
        "GitHub-native opportunity is based on bounded public metadata; live source reread is required before acting.",
        "CI, review discussion, and timeline evidence are not fully certified in this discovery-stage snapshot.",
    ]
    if state in {"NEEDS_MORE_EVIDENCE", "NO_CLEAR_CONTRIBUTION"}:
        limitations.append("Radar observed a public signal but not enough evidence for a clear contribution path.")
    return {
        "schema": "radar-opportunity.v2",
        "version": 2,
        "id": opportunity_id(canonical, contribution_family, missing_increment),
        "revision": f"opportunity-revision-v2-{canonical_hash(revision_material)[:32]}",
        "legacyV1": None,
        "identity": {
            "canonicalResourceId": canonical["id"],
            "contributionFamily": contribution_family,
            "missingIncrement": missing_increment,
        },
        "canonicalResource": canonical,
        "supportingResources": [],
        "area": family_name,
        "contributionFamily": contribution_family,
        "likelyMissingIncrement": missing_increment,
        "requiresLiveRevalidation": True,
        "qualification": {
            "state": state,
            "confidence": signal["confidence"],
            "reason": signal["reason"],
            "whyNow": [signal["reason"]],
            "evidenceObserved": observed_native_evidence(resource),
            "evidenceMissing": ["full review discussion", "current CI or test result", "authoritative current reread"],
            "duplicationRisk": "medium",
            "noveltySignal": "Source-native public signal not dependent on Core Trac identity.",
            "dimensions": dimensions,
            "limitations": limitations,
        },
        "sourceCoverage": coverage,
        "freshness": {"state": family_record.get("freshness") or "stale", "sourceFamily": family_name},
        "ranking": {
            "score": native_score(state, signal["confidence"]),
            "tier": "priority" if state == "CLEAR_OPPORTUNITY" else "watch",
            "deterministicReasons": [signal["reason"]],
            "dimensions": dimensions,
        },
    }


def observed_native_evidence(resource: dict[str, Any]) -> list[str]:
    evidence = ["public GitHub title", "public GitHub state", "public update timestamp"]
    if resource.get("labels"):
        evidence.append("public GitHub labels")
    if resource.get("comments"):
        evidence.append("public comment count")
    if resource.get("requestedReviewers") or resource.get("requestedTeams"):
        evidence.append("public review request metadata")
    if resource.get("head") or resource.get("base"):
        evidence.append("public head/base metadata")
    return evidence


def native_score(state: str, confidence: str) -> int:
    base = {"CLEAR_OPPORTUNITY": 80, "POSSIBLE_OPPORTUNITY": 55, "NEEDS_MORE_EVIDENCE": 25, "NO_CLEAR_CONTRIBUTION": 0}.get(state, 30)
    return base + {"high": 10, "medium": 5, "low": 0}.get(confidence, 0)


def native_opportunities(source_snapshot: dict[str, Any] | None, family_record: dict[str, Any], family_name: str) -> list[dict[str, Any]]:
    if not source_snapshot or family_record["health"]["state"] != "certified":
        return []
    result = []
    for resource in source_snapshot.get("resources", []):
        opportunity = native_opportunity(resource, family_record, family_name)
        if opportunity:
            result.append(opportunity)
    return result


def wave2_source_coverage(resource: dict[str, Any]) -> dict[str, str]:
    return {
        "source_metadata": "COMPLETE",
        "source_native_identity": "COMPLETE",
        "source_revision": "COMPLETE" if resource.get("sourceRevision") else "NONE",
        "public_content": "COMPLETE" if resource.get("bodyHash") else "NONE",
        "public_relationships": "PARTIAL" if resource.get("outboundLinks") else "NONE",
        "candidate_signal": "COMPLETE" if resource.get("candidateSignals") else "NONE",
        "authoritative_current_reread": "NONE",
    }


def wave2_opportunity(
    resource: dict[str, Any],
    family_record: dict[str, Any],
    family_name: str,
    signal: dict[str, Any],
) -> dict[str, Any]:
    canonical = wave2_resource(resource, family_record, family_name)
    state = str(signal["state"])
    contribution_family = str(signal["familyId"])
    reason = str(signal["reason"])
    confidence = str(signal["confidence"])
    coverage = wave2_source_coverage(resource)
    missing_increment = reason
    dimensions = {
        "actionability": "high" if state == "CLEAR_OPPORTUNITY" else "medium",
        "usefulnessSignal": confidence,
        "evidenceCompleteness": "medium",
        "freshness": family_record.get("freshness") or "stale",
        "duplicationRisk": "medium",
        "noveltySignal": "source-native",
        "effort": "unknown",
        "timeliness": "near-term" if state == "CLEAR_OPPORTUNITY" else "watch",
        "confidence": confidence,
    }
    revision_material = {
        "schema": "radar-wave2-opportunity-v2-material-state.v1",
        "canonicalResource": canonical["revision"],
        "qualificationState": state,
        "contributionFamily": contribution_family,
        "missingIncrement": missing_increment,
        "sourceCoverage": coverage,
        "dimensions": dimensions,
    }
    return {
        "schema": "radar-opportunity.v2",
        "version": 2,
        "id": opportunity_id(canonical, contribution_family, missing_increment),
        "revision": f"opportunity-revision-v2-{canonical_hash(revision_material)[:32]}",
        "legacyV1": None,
        "legacySignalFamily": None,
        "identity": {
            "canonicalResourceId": canonical["id"],
            "contributionFamily": contribution_family,
            "missingIncrement": missing_increment,
        },
        "canonicalResource": canonical,
        "supportingResources": [],
        "area": family_name,
        "contributionFamily": contribution_family,
        "familyCandidates": [{
            "familyId": contribution_family,
            "confidence": confidence,
            "sourceSignal": "SOURCE_NATIVE_REQUEST",
            "sourceEvidence": list(signal.get("evidence") or []),
            "explanation": reason,
        }],
        "likelyMissingIncrement": missing_increment,
        "requiresLiveRevalidation": True,
        "qualification": {
            "state": state,
            "confidence": confidence,
            "reason": reason,
            "whyNow": [reason],
            "evidenceObserved": [
                "source-native public identity",
                "immutable raw acquisition receipt",
                "public material revision",
                *list(signal.get("evidence") or []),
            ],
            "evidenceMissing": [
                "authoritative current reread immediately before action",
                "complete thread or destination context when the source does not expose it",
            ],
            "duplicationRisk": "medium",
            "noveltySignal": "Source-native public request with a specific mapped contribution family.",
            "dimensions": dimensions,
            "limitations": [
                *list(family_record.get("limitations") or []),
                "Radar observes the public request but does not decide private qualification, scheduling, content drafting, or delivery authority.",
            ],
        },
        "sourceCoverage": coverage,
        "freshness": {"state": family_record.get("freshness") or "stale", "sourceFamily": family_name},
        "ranking": {
            "score": native_score(state, confidence),
            "tier": "priority" if state == "CLEAR_OPPORTUNITY" else "watch",
            "deterministicReasons": [reason],
            "dimensions": dimensions,
        },
    }


def wave2_opportunities(
    source_snapshot: dict[str, Any] | None,
    family_record: dict[str, Any],
    family_name: str,
) -> list[dict[str, Any]]:
    if not source_snapshot or family_record["health"]["state"] != "certified":
        return []
    result = []
    for resource in source_snapshot.get("resources", []):
        for signal_record in resource.get("candidateSignals", []):
            result.append(wave2_opportunity(resource, family_record, family_name, signal_record))
    return result


def apply_public_outcome_suppression(opportunities: list[dict[str, Any]], contributions: dict[str, Any]) -> list[dict[str, Any]]:
    covered = {
        str(item.get("opportunityKey"))
        for item in contributions.get("contributions", [])
        if item.get("lifecycleState") in {"PUBLIC_DELIVERY_VERIFIED", "UPSTREAM_ACCEPTED", "FOLLOWUP_REQUIRED"}
    }
    result = []
    for opportunity in opportunities:
        legacy = opportunity.get("legacyV1") or {}
        if legacy.get("opportunityKey") not in covered:
            result.append(opportunity)
            continue
        updated = json.loads(json.dumps(opportunity))
        updated["qualification"]["state"] = "LIKELY_ALREADY_COVERED"
        updated["qualification"]["confidence"] = "high"
        updated["qualification"]["reason"] = "A verified public contribution outcome already exists for this legacy opportunity."
        updated["qualification"]["whyNow"] = ["A verified public contribution outcome already exists; avoid redundant work unless live reread shows a new missing increment."]
        updated["qualification"]["limitations"].append("Suppressed by public contribution outcome evidence.")
        updated["qualification"]["duplicationRisk"] = "high"
        updated["ranking"]["score"] = 0
        updated["ranking"]["tier"] = "suppressed"
        updated["ranking"]["deterministicReasons"] = ["Public outcome evidence indicates this opportunity is likely already covered."]
        updated["ranking"]["dimensions"]["actionability"] = "low"
        updated["ranking"]["dimensions"]["duplicationRisk"] = "high"
        updated["ranking"]["dimensions"]["confidence"] = "high"
        revision_material = {
            "schema": "radar-opportunity-v2-outcome-suppression.v1",
            "id": updated["id"],
            "priorRevision": opportunity["revision"],
            "state": updated["qualification"]["state"],
            "coveredBy": sorted(covered),
        }
        updated["revision"] = f"opportunity-revision-v2-{canonical_hash(revision_material)[:32]}"
        result.append(updated)
    return result


def source_families(
    *,
    snapshot: dict[str, Any],
    collection: dict[str, Any],
    opportunities: dict[str, Any],
    wordpress_develop: dict[str, Any] | None,
    gutenberg: dict[str, Any] | None = None,
    wave2_sources: dict[str, dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    trac_records = sum(item["row_count"] for item in collection["query_evidence"])
    raw_acquisitions = [
        {
            "querySlug": item["query_slug"],
            "sourceUrl": item.get("source_url"),
            "retrievedAt": item.get("collected_at"),
            "rawArtifact": item.get("artifact_path"),
            "rawSha256": item.get("sha256"),
            "acquisitionId": item.get("acquisition_id"),
            "sourceReceipt": item.get("source_receipt_path"),
            "parserVersion": item.get("parsing_version"),
            "rowCount": item.get("row_count"),
            "execution": item.get("acquisition_execution"),
        }
        for item in collection["query_evidence"]
    ]
    trac_family = {
        "sourceFamily": CORE_TRAC_FAMILY,
        "snapshotId": f"source-family-core-trac-{snapshot['collection_id'].replace('collection-v1-', '')}",
        "sourceRevision": collection["collection_id"],
        "observedTime": collection["reference_time"],
        "certifiedTime": snapshot["reference_time"],
        "completeness": "COMPLETE" if collection["state"] == "complete" else "PARTIAL",
        "freshness": "fresh",
        "recordCount": trac_records,
        "canonicalHash": snapshot["collection_sha256"],
        "observation": {
            "runId": collection.get("collection_id"),
            "collectorVersion": collection.get("collector_version"),
            "sourceConfigRevision": snapshot.get("source_revision"),
            "artifactHash": snapshot["collection_sha256"],
            "certificationResult": collection["state"],
        },
        "rawAcquisitions": raw_acquisitions,
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
            "sourceFamily": WORDPRESS_DEVELOP_FAMILY,
            "snapshotId": wordpress_develop["snapshotId"],
            "sourceRevision": wordpress_develop["sourceRevision"],
            "observedTime": wordpress_develop["observedTime"],
            "certifiedTime": wordpress_develop["certifiedTime"],
            "completeness": wordpress_develop["completeness"],
            "freshness": wordpress_develop["freshness"],
            "recordCount": wordpress_develop["recordCount"],
            "canonicalHash": wordpress_develop["canonicalHash"],
            "observation": {
                "runId": wordpress_develop["snapshotId"],
                "collectorVersion": "collect-wordpress-develop-github.v1",
                "sourceConfigRevision": "open-pulls-updated-desc-bounded-window",
                "artifactHash": wordpress_develop["canonicalHash"],
                "certificationResult": wordpress_develop["health"]["state"],
                "scope": "open pull requests sorted by updated time",
                "limitReached": wordpress_develop["completeness"] == "PARTIAL",
            },
            "limitations": wordpress_develop["limitations"],
            "health": wordpress_develop["health"],
        }
    else:
        github_family = {
            "sourceFamily": WORDPRESS_DEVELOP_FAMILY,
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
    if gutenberg:
        gutenberg_family = {
            "sourceFamily": GUTENBERG_FAMILY,
            "snapshotId": gutenberg["snapshotId"],
            "sourceRevision": gutenberg["sourceRevision"],
            "observedTime": gutenberg["observedTime"],
            "certifiedTime": gutenberg["certifiedTime"],
            "completeness": gutenberg["completeness"],
            "freshness": gutenberg["freshness"],
            "recordCount": gutenberg["recordCount"],
            "canonicalHash": gutenberg["canonicalHash"],
            "observation": {
                "runId": gutenberg["snapshotId"],
                "collectorVersion": "collect-gutenberg-github.v1",
                "sourceConfigRevision": "issues-and-pulls-updated-desc-bounded-window",
                "artifactHash": gutenberg["canonicalHash"],
                "certificationResult": gutenberg["health"]["state"],
                "scope": "open issues and pull requests sorted by updated time",
                "limitReached": gutenberg["completeness"] == "PARTIAL",
            },
            "limitations": gutenberg["limitations"],
            "health": gutenberg["health"],
        }
    else:
        gutenberg_family = {
            "sourceFamily": GUTENBERG_FAMILY,
            "snapshotId": "source-family-gutenberg-unavailable",
            "sourceRevision": None,
            "observedTime": None,
            "certifiedTime": snapshot["reference_time"],
            "completeness": "NONE",
            "freshness": "stale",
            "recordCount": 0,
            "canonicalHash": None,
            "limitations": ["No certified Gutenberg GitHub source snapshot is available."],
            "health": {
                "state": "degraded",
                "failure": "GUTENBERG_SOURCE_MISSING",
            },
        }
    wave2 = []
    provided_wave2 = wave2_sources or {}
    for family_name in WAVE2_SOURCE_FAMILIES:
        source = provided_wave2.get(family_name)
        if source:
            wave2.append({
                "sourceFamily": family_name,
                "snapshotId": source["snapshotId"],
                "sourceRevision": source["sourceRevision"],
                "observedTime": source["observedTime"],
                "certifiedTime": source["certifiedTime"],
                "completeness": source["completeness"],
                "freshness": source["freshness"],
                "recordCount": source["recordCount"],
                "candidateSignalCount": source.get("candidateSignalCount", 0),
                "canonicalHash": source["canonicalHash"],
                "authoritativeSource": source.get("authoritativeSource"),
                "machineReadableAccess": source.get("machineReadableAccess", []),
                "rawAcquisitions": source.get("rawAcquisitions", []),
                "retrievalReceipt": source.get("retrievalReceipt"),
                "outcomeObservers": source.get("outcomeObservers", []),
                "requiredForCurrentCandidateFeed": False,
                "observation": {
                    "runId": source["snapshotId"],
                    "collectorVersion": "collect-wave2-sources.v1",
                    "sourceConfigRevision": source.get("scope"),
                    "artifactHash": source["canonicalHash"],
                    "certificationResult": source["health"]["state"],
                    "scope": source.get("scope"),
                    "limitReached": source["completeness"] == "PARTIAL",
                },
                "limitations": source["limitations"],
                "health": source["health"],
            })
        else:
            wave2.append({
                "sourceFamily": family_name,
                "snapshotId": f"source-family-{source_family_id(family_name)}-not-certified",
                "sourceRevision": None,
                "observedTime": None,
                "certifiedTime": snapshot["reference_time"],
                "completeness": "NONE",
                "freshness": "stale",
                "recordCount": 0,
                "canonicalHash": None,
                "requiredForCurrentCandidateFeed": False,
                "limitations": [
                    f"{WAVE2_SOURCE_LABELS[family_name]} adapter is not certified in this snapshot.",
                ],
                "health": {
                    "state": "not_certified",
                    "failure": "SOURCE_ADAPTER_NOT_CERTIFIED",
                },
            })
    return [trac_family, github_family, gutenberg_family, *wave2]


def resources_payload(
    snapshot_id: str,
    opportunities: list[dict[str, Any]],
    source_snapshots: dict[str, dict[str, Any] | None],
    families_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resources: dict[str, dict[str, Any]] = {}
    for opportunity in opportunities:
        resources[opportunity["canonicalResource"]["id"]] = opportunity["canonicalResource"]
        for supporting in opportunity["supportingResources"]:
            resources[supporting["id"]] = supporting

    for family_name, snapshot in source_snapshots.items():
        if snapshot:
            for item in snapshot.get("resources", []):
                resource = source_resource(item, families_by_source.get(family_name), family_name)
                resources.setdefault(resource["id"], resource)

    ordered = [resources[key] for key in sorted(resources)]
    return {
        "schema": "radar-resource-set.v2",
        "version": 2,
        "snapshotId": snapshot_id,
        "resourceCount": len(ordered),
        "resources": ordered,
    }


def relationship_id(source_id: str, relation_type: str, target_id: str, provenance: list[dict[str, Any]]) -> str:
    material = {
        "sourceResourceId": source_id,
        "relationType": relation_type,
        "targetResourceId": target_id,
        "provenance": provenance,
    }
    return f"relationship-v2-{canonical_hash(material)[:32]}"


def source_relationships(source_snapshot: dict[str, Any] | None, family_record: dict[str, Any] | None, family_name: str) -> list[dict[str, Any]]:
    if not source_snapshot or not family_record:
        return []
    by_number = {
        str(resource.get("number")): resource
        for resource in source_snapshot.get("resources", [])
        if str(resource.get("resourceType", "")).endswith("_ISSUE")
    }
    relations = []
    for resource in source_snapshot.get("resources", []):
        if not str(resource.get("resourceType", "")).endswith("_PR"):
            continue
        text = f"{resource.get('title') or ''} {resource.get('body') or ''}"
        for match in sorted(set(re.findall(r"(?i)\b(closes|fixes|resolves|references|see)?\s*#([0-9]{2,6})\b", text))):
            verb, number = match
            target = by_number.get(number)
            if not target:
                continue
            source_resource = github_resource(resource, family_record, family_name)
            target_resource = github_resource(target, family_record, family_name)
            relation_type = "IMPLEMENTS" if str(verb).lower() in {"closes", "fixes", "resolves"} else "REFERENCES"
            provenance = [{
                "source": "public-github-same-repository-reference",
                "evidence": f"Public {family_name} pull request text references issue #{number}.",
                "sourceFamilySnapshotId": family_record["snapshotId"],
            }]
            relations.append({
                "schema": "radar-resource-relationship.v2",
                "version": 2,
                "id": relationship_id(source_resource["id"], relation_type, target_resource["id"], provenance),
                "sourceResourceId": source_resource["id"],
                "relationType": relation_type,
                "targetResourceId": target_resource["id"],
                "provenance": provenance,
                "confidence": "medium",
                "limitations": [
                    "Same-repository GitHub numeric reference is used only within the observed repository source family.",
                ],
            })
    return relations


def public_url_aliases(value: str) -> set[str]:
    base = value.rstrip("/")
    aliases = {base}
    if "/pull/" in base:
        aliases.add(base.replace("/pull/", "/issues/"))
    if "/issues/" in base:
        aliases.add(base.replace("/issues/", "/pull/"))
    return aliases


def wave2_relationships(
    source_snapshots: dict[str, dict[str, Any] | None],
    families_by_source: dict[str, dict[str, Any]],
    opportunity_resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {item["id"]: item for item in opportunity_resources}
    for family_name, source_snapshot in source_snapshots.items():
        if not source_snapshot:
            continue
        for item in source_snapshot.get("resources", []):
            resource = source_resource(item, families_by_source.get(family_name), family_name)
            resources[resource["id"]] = resource
    by_url: dict[str, dict[str, Any]] = {}
    for resource in resources.values():
        for alias in public_url_aliases(str(resource.get("canonicalUrl") or "")):
            if alias:
                by_url.setdefault(alias, resource)
    relationships = []
    for resource in resources.values():
        if resource["sourceFamily"] not in WAVE2_SOURCE_FAMILIES:
            continue
        for outbound in resource.get("observedFields", {}).get("outboundLinks", []):
            target = next((by_url.get(alias) for alias in public_url_aliases(str(outbound)) if by_url.get(alias)), None)
            if not target or target["id"] == resource["id"]:
                continue
            provenance = [{
                "source": "public-source-link",
                "evidence": "The source-native public resource contains an explicit link to another observed public resource.",
                "sourceFamilySnapshotId": resource["sourceFamilySnapshotId"],
            }]
            relationships.append({
                "schema": "radar-resource-relationship.v2",
                "version": 2,
                "id": relationship_id(resource["id"], "REFERENCES", target["id"], provenance),
                "sourceResourceId": resource["id"],
                "relationType": "REFERENCES",
                "targetResourceId": target["id"],
                "provenance": provenance,
                "confidence": "high",
                "limitations": ["The relationship records an explicit public URL reference and does not merge source-native identities."],
            })
    return relationships


def relationships_payload(
    snapshot_id: str,
    opportunities: list[dict[str, Any]],
    source_snapshots: dict[str, dict[str, Any] | None],
    families_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    relationships: dict[str, dict[str, Any]] = {}
    opportunity_resources: dict[str, dict[str, Any]] = {}
    for opportunity in opportunities:
        canonical = opportunity["canonicalResource"]
        opportunity_resources[canonical["id"]] = canonical
        for supporting in opportunity["supportingResources"]:
            opportunity_resources[supporting["id"]] = supporting
            provenance = [{
                "source": "public-wordpress-develop-pull-request",
                "evidence": "canonical Core Trac ticket URL observed in the pull request source snapshot",
                "sourceFamilySnapshotId": supporting["sourceFamilySnapshotId"],
            }]
            relation = {
                "schema": "radar-resource-relationship.v2",
                "version": 2,
                "id": relationship_id(supporting["id"], "REFERENCES", canonical["id"], provenance),
                "sourceResourceId": supporting["id"],
                "relationType": "REFERENCES",
                "targetResourceId": canonical["id"],
                "provenance": provenance,
                "confidence": "high",
                "limitations": [
                    "Relationship is based on explicit public source reference; Radar does not infer identity from numeric coincidence.",
                ],
            }
            relationships[relation["id"]] = relation
    for family_name in (WORDPRESS_DEVELOP_FAMILY, GUTENBERG_FAMILY):
        for relation in source_relationships(source_snapshots.get(family_name), families_by_source.get(family_name), family_name):
            relationships[relation["id"]] = relation
    for relation in wave2_relationships(source_snapshots, families_by_source, list(opportunity_resources.values())):
        relationships[relation["id"]] = relation
    ordered = [relationships[key] for key in sorted(relationships)]
    return {
        "schema": "radar-relationship-set.v2",
        "version": 2,
        "snapshotId": snapshot_id,
        "relationshipTypes": [
            "IMPLEMENTS",
            "REFERENCES",
            "DUPLICATES",
            "SUPERSEDES",
            "RELATED_TO",
            "TESTS",
            "REVIEW_OF",
            "CI_FOR",
            "PATCH_FOR",
            "RELEASE_SIGNAL_FOR",
        ],
        "relationshipCount": len(ordered),
        "relationships": ordered,
    }


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


def changes_payload(snapshot: dict[str, Any], opportunities: list[dict[str, Any]], resources: dict[str, Any], relationships: dict[str, Any], families: list[dict[str, Any]]) -> dict[str, Any]:
    events = []
    for resource in resources["resources"]:
        material = {
            "resource": resource["id"],
            "revision": resource["materialRevision"],
            "class": "RESOURCE_FIRST_OBSERVED",
        }
        events.append({
            "id": f"change-v2-{canonical_hash(material)[:32]}",
            "eventClass": "RESOURCE_FIRST_OBSERVED",
            "resourceId": resource["id"],
            "resourceRevision": resource["materialRevision"],
            "observedTime": snapshot["reference_time"],
            "summary": "A public resource is present in the current certified observation set.",
            "resourceIds": [resource["id"]],
        })
    for relationship in relationships["relationships"]:
        material = {
            "relationship": relationship["id"],
            "class": "SUPPORTING_RESOURCE_ADDED",
        }
        events.append({
            "id": f"change-v2-{canonical_hash(material)[:32]}",
            "eventClass": "SUPPORTING_RESOURCE_ADDED",
            "relationshipId": relationship["id"],
            "observedTime": snapshot["reference_time"],
            "summary": "A public supporting-resource relationship is present in the current certified observation set.",
            "resourceIds": [relationship["sourceResourceId"], relationship["targetResourceId"]],
        })
    for family in families:
        if family["health"]["state"] != "certified":
            material = {
                "sourceFamily": family["sourceFamily"],
                "state": family["health"]["state"],
                "failure": family["health"].get("failure"),
                "class": "SOURCE_COVERAGE_DEGRADED",
            }
            events.append({
                "id": f"change-v2-{canonical_hash(material)[:32]}",
                "eventClass": "SOURCE_COVERAGE_DEGRADED",
                "sourceFamily": family["sourceFamily"],
                "observedTime": snapshot["reference_time"],
                "summary": "A source family is degraded or unavailable in the current public observation set.",
                "resourceIds": [],
            })
    for opportunity in opportunities:
        state = opportunity["qualification"]["state"]
        event_class = "OPPORTUNITY_SUPPRESSED" if state == "NO_CLEAR_CONTRIBUTION" else "OPPORTUNITY_BECAME_CLEAR"
        if opportunity["contributionFamily"] == "FOLLOW_UP_AFTER_UPSTREAM_CHANGE":
            event_class = "UPSTREAM_REACTIVATED"
        elif opportunity["supportingResources"]:
            event_class = "SUPPORTING_RESOURCE_ADDED"
        elif state == "POSSIBLE_OPPORTUNITY":
            event_class = "QUALIFICATION_CHANGED"
        elif state == "LIKELY_ALREADY_COVERED":
            event_class = "OPPORTUNITY_LIKELY_COVERED"
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
        "events": sorted(events, key=lambda item: (item["eventClass"], item["id"])),
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
        "legacySignalFamilies": LEGACY_SIGNAL_FAMILIES,
        "sourceFamilies": ["CORE_TRAC", "WORDPRESS_DEVELOP_GITHUB", "GUTENBERG", *WAVE2_SOURCE_FAMILIES],
        "coverageStates": ["COMPLETE", "PARTIAL", "NONE", "STALE"],
        "resourceRelationshipTypes": [
            "IMPLEMENTS",
            "REFERENCES",
            "DUPLICATES",
            "SUPERSEDES",
            "RELATED_TO",
            "TESTS",
            "REVIEW_OF",
            "CI_FOR",
            "PATCH_FOR",
            "RELEASE_SIGNAL_FOR",
        ],
        "changeEventClasses": [
            "RESOURCE_FIRST_OBSERVED",
            "RESOURCE_MATERIALLY_CHANGED",
            "PR_HEAD_CHANGED",
            "SUPPORTING_RESOURCE_ADDED",
            "PUBLIC_TEST_OR_REVIEW_ADDED",
            "QUALIFICATION_CHANGED",
            "OPPORTUNITY_BECAME_CLEAR",
            "OPPORTUNITY_LIKELY_COVERED",
            "OPPORTUNITY_SUPPRESSED",
            "UPSTREAM_REACTIVATED",
            "RESOURCE_CLOSED_OR_MERGED",
            "SOURCE_COVERAGE_DEGRADED",
        ],
    }


def diagnostics_payload(opportunities: list[dict[str, Any]], families: list[dict[str, Any]], resources: dict[str, Any], relationships: dict[str, Any]) -> dict[str, Any]:
    qualification = Counter(item["qualification"]["state"] for item in opportunities)
    by_family = Counter(item["contributionFamily"] for item in opportunities)
    resources_by_family = Counter(item["sourceFamily"] for item in resources["resources"])
    completeness = Counter(f"{item['sourceFamily']}:{item['completeness']}" for item in resources["resources"])
    coverage = Counter()
    for opportunity in opportunities:
        for key, state in opportunity["sourceCoverage"].items():
            coverage[f"{key}:{state}"] += 1
    return {
        "schema": "radar-diagnostics.v2",
        "version": 2,
        "rawResourcesObserved": resources["resourceCount"],
        "rawResourcesBySourceFamily": counted(resources_by_family),
        "resourceRelationshipCount": relationships["relationshipCount"],
        "clusterCount": len({item["identity"]["canonicalResourceId"] for item in opportunities}),
        "deduplication": {
            "opportunityCount": len(opportunities),
            "canonicalResourceCount": len({item["identity"]["canonicalResourceId"] for item in opportunities}),
            "supportingRelationshipCount": relationships["relationshipCount"],
        },
        "uniqueOpportunities": len(opportunities),
        "qualificationDistribution": counted(qualification),
        "contributionFamilyDistribution": counted(by_family),
        "sourceFamilyDistribution": counted(Counter(family["sourceFamily"] for family in families)),
        "freshnessDistribution": counted(Counter(item["freshness"]["state"] for item in opportunities)),
        "completenessDistribution": counted(completeness),
        "evidenceCompleteness": counted(coverage),
        "suppressionReasons": counted(Counter(reason for item in opportunities for reason in item["qualification"]["limitations"] if item["qualification"]["state"] == "NO_CLEAR_CONTRIBUTION")),
    }


def counted(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"key": key, "count": counter[key]} for key in sorted(counter)]


def contribution_family_registry_payload(snapshot_id: str) -> dict[str, Any]:
    aliases = {
        "CORE_CODE_REVIEW": ["REVIEW_EXISTING_PR", "REVIEW_API_EDGE_CASE", "REVIEW_BACKWARD_COMPATIBILITY"],
        "CORE_PATCH_TEST": ["TEST_EXISTING_PR", "VERIFY_EXISTING_PATCH", "VERIFY_FIX_AFTER_CHANGE"],
        "CORE_BUG_REPRODUCTION": ["REPRODUCE_BUG", "ISOLATE_REGRESSION"],
        "CORE_REGRESSION_TEST": ["ADD_REGRESSION_TEST"],
        "CORE_AUTOMATED_TEST": ["ADD_UNIT_TEST", "ADD_INTEGRATION_TEST"],
        "CORE_BUG_GARDENING": ["STALE_BUT_ACTIONABLE", "FOLLOW_UP_AFTER_UPSTREAM_CHANGE"],
        "CORE_INLINE_DOCS": ["DOCUMENT_TECHNICAL_BEHAVIOR"],
        "GUTENBERG_CODE_REVIEW": ["REVIEW_EXISTING_PR", "REVIEW_API_EDGE_CASE"],
        "GUTENBERG_TEST": ["TEST_EXISTING_PR", "VERIFY_EXISTING_PATCH", "ADD_REGRESSION_TEST", "STALE_BUT_ACTIONABLE"],
        "GUTENBERG_REPRODUCTION": ["REPRODUCE_BUG", "ISOLATE_REGRESSION"],
        "ACCESSIBILITY_TEST": ["ACCESSIBILITY_UI_VERIFY"],
        "BETA_RC_TEST": ["RELEASE_CANDIDATE_VERIFY"],
        "PERFORMANCE_INVESTIGATION": ["BENCHMARK_PERFORMANCE_CHANGE"],
        "DOCS_REVIEW": ["DOCUMENT_TECHNICAL_BEHAVIOR"],
    }
    return {
        "schema": "radar-contribution-family-registry.v1",
        "version": 1,
        "snapshotId": snapshot_id,
        "families": [
            {
                "id": family_id,
                "label": label,
                "description": description,
                "aliases": aliases.get(family_id, []),
                "extensible": True,
            }
            for family_id, label, description in CONTRIBUTION_FAMILY_REGISTRY
        ],
        "notes": [
            "WordPress labels, keywords, pathways, and legacy Radar signal classes are aliases or evidence signals; they are not required to be family IDs.",
            "Candidate family classification is public evidence-based and may expose multiple candidates when evidence is ambiguous.",
        ],
    }


def scoring_contract_payload(snapshot_id: str) -> dict[str, Any]:
    return {
        "schema": "radar-candidate-scoring-contract.v1",
        "version": 1,
        "snapshotId": snapshot_id,
        "dimensions": [
            {
                "id": name,
                "fields": ["value", "confidence", "sourceEvidence", "explanation"],
                "unknownPolicy": "Unknown values remain unknown and are not coerced into neutral scalar scores.",
            }
            for name in SCORE_DIMENSIONS
        ],
        "derivedPriority": {
            "purpose": "ordering",
            "gatePolicy": "A scalar priority cannot override failed eligibility, safety, or source-integrity gates.",
        },
        "excludedInputs": [
            "contribution quotas",
            "desired monthly velocity",
            "downstream execution lifecycle",
            "private delivery authority",
        ],
    }


def candidate_id_for(opportunity: dict[str, Any]) -> str:
    material = {
        "schema": "radar-candidate-identity.v1",
        "opportunityId": opportunity["id"],
        "opportunityRevision": opportunity["revision"],
    }
    return f"candidate:v1:{canonical_hash(material)[:32]}"


def candidate_from_opportunity(
    opportunity: dict[str, Any],
    relationships: dict[str, Any],
    families_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resource_ids = [opportunity["canonicalResource"]["id"], *[item["id"] for item in opportunity["supportingResources"]]]
    related = [
        relation
        for relation in relationships["relationships"]
        if relation["sourceResourceId"] in resource_ids or relation["targetResourceId"] in resource_ids
    ]
    source_family = opportunity["canonicalResource"]["sourceFamily"]
    family = families_by_source.get(source_family, {})
    return {
        "schema": "radar-candidate.v1",
        "version": 1,
        "id": candidate_id_for(opportunity),
        "opportunityRef": {
            "id": opportunity["id"],
            "revision": opportunity["revision"],
        },
        "resourceRefs": [{"id": resource_id} for resource_id in resource_ids],
        "relationships": related,
        "familyCandidates": opportunity.get("familyCandidates", []),
        "scoreVector": opportunity["scoreVector"],
        "derivedRanking": opportunity["ranking"],
        "eligibilityGate": opportunity["eligibilityGate"],
        "sourceRevision": opportunity["canonicalResource"].get("sourceRevision"),
        "freshness": opportunity["freshness"],
        "sourceHealth": {
            "sourceFamily": source_family,
            "state": family.get("health", {}).get("state", "unknown"),
            "snapshotId": family.get("snapshotId"),
        },
        "changeInformation": {
            "opportunityRevision": opportunity["revision"],
            "resourceRevision": opportunity["canonicalResource"]["revision"],
            "materialState": opportunity["qualification"]["state"],
        },
        "candidateExplanation": {
            "reason": opportunity["qualification"].get("reason"),
            "whyNow": opportunity["qualification"].get("whyNow", []),
            "limitations": opportunity["qualification"].get("limitations", []),
        },
    }


def candidate_feed_payload(
    snapshot_id: str,
    opportunities: list[dict[str, Any]],
    relationships: dict[str, Any],
    families_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates = [
        candidate_from_opportunity(opportunity, relationships, families_by_source)
        for opportunity in opportunities
        if opportunity["qualification"]["state"] != "NO_CLEAR_CONTRIBUTION"
    ]
    return {
        "schema": "radar-candidate-feed.v1",
        "version": 1,
        "snapshotId": snapshot_id,
        "candidateCount": len(candidates),
        "candidateBoundary": {
            "publicCandidateOnly": True,
            "notFinalQualification": True,
            "notExecutableWork": True,
            "noSchedulingOrDeliveryAuthority": True,
        },
        "candidates": candidates,
    }


def project_v2(
    *,
    snapshot: dict[str, Any],
    collection: dict[str, Any],
    opportunities: dict[str, Any],
    contributions: dict[str, Any],
    wordpress_develop: dict[str, Any] | None = None,
    gutenberg: dict[str, Any] | None = None,
    wave2_sources: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, bytes]:
    configured_wave2 = wave2_sources or {}
    github_index = github_ticket_index(wordpress_develop)
    families = source_families(
        snapshot=snapshot,
        collection=collection,
        opportunities=opportunities,
        wordpress_develop=wordpress_develop,
        gutenberg=gutenberg,
        wave2_sources=configured_wave2,
    )
    families_by_source = {family["sourceFamily"]: family for family in families}
    trac_opportunities = [
        v2_opportunity(record, github_index, families_by_source)
        for record in opportunities["opportunities"]
    ]
    native_wordpress = native_opportunities(wordpress_develop, families_by_source[WORDPRESS_DEVELOP_FAMILY], WORDPRESS_DEVELOP_FAMILY)
    native_gutenberg = native_opportunities(gutenberg, families_by_source[GUTENBERG_FAMILY], GUTENBERG_FAMILY)
    native_wave2 = [
        opportunity
        for family_name in WAVE2_SOURCE_FAMILIES
        for opportunity in wave2_opportunities(configured_wave2.get(family_name), families_by_source[family_name], family_name)
    ]
    v2_opportunities = [
        attach_candidate_model(item)
        for item in apply_public_outcome_suppression(sorted(
        [*trac_opportunities, *native_wordpress, *native_gutenberg, *native_wave2],
        key=lambda item: (-item["ranking"]["score"], item["id"]),
        ), contributions)
    ]
    v2_snapshot = v2_snapshot_payload(snapshot, collection, v2_opportunities, families)
    source_snapshots = {
        WORDPRESS_DEVELOP_FAMILY: wordpress_develop,
        GUTENBERG_FAMILY: gutenberg,
        **configured_wave2,
    }
    resources = resources_payload(v2_snapshot["snapshotId"], v2_opportunities, source_snapshots, families_by_source)
    relationships = relationships_payload(v2_snapshot["snapshotId"], v2_opportunities, source_snapshots, families_by_source)
    candidates = candidate_feed_payload(v2_snapshot["snapshotId"], v2_opportunities, relationships, families_by_source)
    required_families = [family for family in families if family.get("requiredForCurrentCandidateFeed") is not False]
    health = {
        "schema": "radar-health.v2",
        "version": 2,
        "status": "healthy" if all(family["health"]["state"] == "certified" for family in required_families) else "degraded",
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
        "resources.json": resources,
        "relationships.json": relationships,
        "candidates.json": candidates,
        "candidate-feed.json": candidates,
        "contribution-families.json": contribution_family_registry_payload(v2_snapshot["snapshotId"]),
        "scoring.json": scoring_contract_payload(v2_snapshot["snapshotId"]),
        "opportunities.json": opportunity_set,
        "changes.json": changes_payload(snapshot, v2_opportunities, resources, relationships, families),
        "contributions.json": {
            "schema": "radar-contributions.v2",
            "version": 2,
            "snapshotId": v2_snapshot["snapshotId"],
            "contributions": contributions.get("contributions", []),
        },
        "outcomes.json": outcomes,
        "taxonomy.json": taxonomy_payload(),
        "diagnostics.json": diagnostics_payload(v2_opportunities, families, resources, relationships),
    }
    return {name: canonical_json(payload) for name, payload in payloads.items()}


def payload_hashes(payloads: dict[str, bytes]) -> dict[str, str]:
    return {name: sha256_bytes(value) for name, value in sorted(payloads.items())}
