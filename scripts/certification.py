#!/usr/bin/env python3
"""Canonical Radar data construction, certification, and offline verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
    parse_datetime,
    trac_url,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"
CERTIFIED_CURRENT = ROOT / "data" / "certified" / "current"
QUERIES_CONFIG = ROOT / "config" / "queries.json"
SCORING_CONFIG = ROOT / "config" / "scoring.json"

SCHEMA_FILES = {
    "collection.v1": "collection.v1.schema.json",
    "contribution-state.v1": "contribution-state.v1.schema.json",
    "snapshot.v1": "snapshot.v1.schema.json",
    "opportunity.v1": "opportunity.v1.schema.json",
    "radar-machine-feed.v1": "radar-machine-feed.v1.schema.json",
    "supply-diagnostics.v1": "supply-diagnostics.v1.schema.json",
    "verified-contribution-outcomes.v1": "verified-contribution-outcomes.v1.schema.json",
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
        item = {
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
        }
        if evidence.source_url:
            item["source_url"] = evidence.source_url
        if evidence.source_receipt_path:
            item["source_receipt_path"] = repository_artifact_path(selection, evidence.source_receipt_path)
        if evidence.acquisition_id:
            item["acquisition_id"] = evidence.acquisition_id
        if evidence.parsing_version:
            item["parsing_version"] = evidence.parsing_version
        if evidence.acquisition_execution:
            item["acquisition_execution"] = evidence.acquisition_execution
        query_evidence.append(item)
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


PUBLIC_CONTRIBUTION_CLASSES = {
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
    "NO_CLEAR_CONTRIBUTION",
}


def _truthy_ticket_signal(ticket: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = ticket.get(key)
        if value in (True, "true", "yes", "1", 1):
            return True
        if isinstance(value, str) and value.strip() and value.strip().lower() not in {"false", "no", "0", "none", "unknown"}:
            return True
    return False


def _ticket_text(ticket: dict[str, Any], *keys: str) -> str:
    return " ".join(str(ticket.get(key) or "").lower() for key in keys)


def _derive_public_source_coverage(
    *,
    ticket: dict[str, Any],
    keywords: set[str],
    has_patch: bool,
    open_pr: bool,
) -> dict[str, bool]:
    """Summarize which public evidence families informed the hypothesis."""
    return {
        "trac_ticket": True,
        "trac_keywords_status_component": bool(keywords or ticket.get("status") or ticket.get("component") or ticket.get("milestone")),
        "public_patch_or_attachment": has_patch or _truthy_ticket_signal(ticket, "patch_url", "attachment_url", "attachment_count", "public_patch_available"),
        "wordpress_develop_pr": open_pr,
        "public_pr_discussion_or_review": _truthy_ticket_signal(ticket, "public_review_request", "public_pr_review", "review_request", "discussion_request"),
        "changed_files_or_diff": _truthy_ticket_signal(ticket, "changed_files", "diff_summary", "diff_files", "public_diff_available"),
        "public_test_or_ci_evidence": _truthy_ticket_signal(ticket, "public_ci_state", "test_evidence", "tested_environment_count", "public_test_report"),
        "related_or_referenced_ticket": _truthy_ticket_signal(ticket, "related_ticket", "referenced_ticket", "related_tickets"),
    }


def _derive_recommended_contribution(
    *,
    ticket: dict[str, Any],
    signals: str,
    keywords: set[str],
    freshness_state: str,
    age_days: int | None,
    has_patch: bool,
    needs_testing: bool,
    unit_tests: bool,
    visual: bool,
    accessibility: bool,
    documentation: bool,
    performance: bool,
    php_runtime: bool,
    reproduction: bool,
    dev_feedback: bool,
    feedback: bool,
) -> tuple[str, str, str]:
    """Return public opportunity intelligence, not an instruction to contribute."""
    status = str(ticket.get("status") or "").lower()
    has_resolution = bool(ticket.get("resolution"))
    open_pr = _truthy_ticket_signal(ticket, "github_pr", "github_pr_url", "pr_url", "pull_request")
    review_request = _truthy_ticket_signal(ticket, "public_review_request", "review_request", "public_pr_review")
    coverage_complete = _truthy_ticket_signal(ticket, "upstream_coverage_complete", "coverage_complete", "fully_covered")
    obsolete = any(marker in signals for marker in ("obsolete", "superseded", "duplicate", "wontfix", "invalid"))
    pr_head = str(ticket.get("pr_head_sha") or ticket.get("head_sha") or "").strip()
    tested_head = str(ticket.get("last_tested_sha") or ticket.get("tested_head_sha") or "").strip()
    upstream_changed = bool(pr_head and tested_head and pr_head != tested_head) or _truthy_ticket_signal(ticket, "pr_head_changed", "upstream_changed_after_test")
    benchmark_present = _truthy_ticket_signal(ticket, "benchmark_evidence", "performance_measurement", "query_count_evidence")
    rest_edge = any(marker in signals for marker in (
        "rest api", "rest-api", "wp rest", "api", "parent:0", "parent 0", "explicit parent",
        "omitted", "explicitly supplied", "null", "false", "0 semantics", "state transition",
        "create/update", "create update", "schema", "serialization", "parent/child",
    ))
    test_stale = freshness_state == "stale" or _truthy_ticket_signal(ticket, "stale_test_evidence", "test_stale")

    if status in {"closed", "fixed", "wontfix", "duplicate", "invalid"} or has_resolution or coverage_complete or obsolete:
        return (
            "NO_CLEAR_CONTRIBUTION",
            "high",
            "Public evidence indicates the ticket is resolved, superseded, fully covered, or otherwise unlikely to need a nonduplicative contribution.",
        )
    if upstream_changed:
        return (
            "FOLLOW_UP_AFTER_UPSTREAM_CHANGE",
            "high",
            "Public evidence shows the PR or patch changed after prior evaluation, so stale verification may be useful again.",
        )
    if open_pr and needs_testing:
        confidence = "high" if not test_stale else "medium"
        return (
            "TEST_EXISTING_PR",
            confidence,
            "A public PR or patch exists and current public ticket signals still ask for testing or verification.",
        )
    if unit_tests:
        return (
            "ADD_REGRESSION_TEST",
            "high" if has_patch else "medium",
            "Public ticket signals call for regression or unit-test coverage around behavior that is not yet sufficiently covered.",
        )
    if rest_edge:
        return (
            "REVIEW_API_EDGE_CASE",
            "high" if has_patch or dev_feedback else "medium",
            "The public ticket evidence points to an API or state-transition edge case where precise expected-versus-actual analysis could help.",
        )
    if performance:
        return (
            "BENCHMARK_PERFORMANCE_CHANGE",
            "medium" if not benchmark_present else "low",
            "The ticket includes a performance-sensitive claim where measured evidence is needed before treating the change as proven.",
        )
    if accessibility or (visual and any(marker in signals for marker in ("focus", "keyboard", "screen reader", "aria", "accessible name"))):
        return (
            "ACCESSIBILITY_UI_VERIFY",
            "high" if has_patch or needs_testing else "medium",
            "The public ticket describes accessibility or UI behavior where browser, keyboard, or semantic verification could add useful evidence.",
        )
    if php_runtime:
        return (
            "VERIFY_PHP_COMPATIBILITY",
            "medium",
            "The ticket includes PHP/runtime compatibility signals that need exact-version confirmation or focused regression coverage.",
        )
    if documentation:
        return (
            "DOCUMENT_TECHNICAL_BEHAVIOR",
            "medium",
            "Public signals point to documentation, inline docs, or DocBlock behavior that can be reviewed against current source behavior.",
        )
    if reproduction:
        return (
            "REPRODUCE_BUG",
            "high",
            "The ticket appears to need exact reproduction, a minimal fixture, or clearer expected-versus-actual behavior.",
        )
    if has_patch and freshness_state == "stale":
        return (
            "STALE_BUT_ACTIONABLE",
            "medium",
            "A public patch exists, but public freshness signals suggest it needs current applicability or relevance review before ordinary testing.",
        )
    if open_pr and (review_request or dev_feedback):
        return (
            "REVIEW_EXISTING_PR",
            "medium",
            "A public PR appears to need review or an answer to an open public discussion point.",
        )
    if has_patch:
        return (
            "VERIFY_EXISTING_PATCH",
            "medium" if age_days is None or age_days > 90 else "high",
            "A public patch exists and the safest useful next step is verifying whether it still addresses the current ticket state.",
        )
    if needs_testing or feedback:
        return (
            "REPRODUCE_BUG",
            "medium",
            "Public ticket signals ask for testing or feedback, but no stronger patch or PR-specific hypothesis is visible in the certified data.",
        )
    return (
        "NO_CLEAR_CONTRIBUTION",
        "medium",
        "The certified public signals do not yet identify a concrete, nonduplicative contribution beyond continued monitoring.",
    )


def derive_opportunity_profile(
    *,
    ticket: dict[str, Any],
    discovery: dict[str, Any],
    radar_state: dict[str, Any],
    reference_time: datetime,
) -> dict[str, Any]:
    """Derive a conservative contribution route from certified Trac signals.

    The profile is advisory. It tells downstream contributors what kind of
    useful work may exist, but it never replaces a fresh upstream duplicate
    and eligibility check.
    """
    keywords = {str(item).lower() for item in ticket.get("keywords", [])}
    tracks = {str(item).lower() for item in discovery.get("tracks", [])}
    component = str(ticket.get("component") or "").lower()
    summary = str(ticket.get("summary") or "").lower()
    ticket_type = str(ticket.get("type") or "").lower()
    optional_public_text = _ticket_text(
        ticket,
        "github_pr_url",
        "pr_url",
        "public_review_request",
        "public_ci_state",
        "changed_files",
        "diff_summary",
        "related_ticket",
        "public_discussion",
    )
    signals = " ".join(sorted(keywords | tracks | {component, summary, ticket_type, optional_public_text}))

    accessibility = "accessibility" in signals or "a11y" in signals
    documentation = any(marker in signals for marker in ("documentation", "docs", "docblock", "inline docs", "docs-focus"))
    unit_tests = any(marker in signals for marker in ("needs-unit-tests", "needs unit tests", "unit test", "phpunit", "qunit"))
    visual = any(marker in signals for marker in (
        "ui", "visual", "browser", "responsive", "mobile", "editor", "block", "wp-admin", "toolbar", "modal",
    ))
    responsive = any(marker in signals for marker in ("responsive", "mobile", "small screen", "viewport"))
    performance = "performance" in signals
    build_tooling = any(marker in signals for marker in ("build/test tools", "build tooling", "grunt", "npm", "webpack", "playwright"))
    php_runtime = any(marker in signals for marker in ("php 8", "php8", "deprecated", "fatal error", "warning", "notice", "compatibility"))
    fragile_tests = any(marker in signals for marker in ("test failure", "failing test", "flaky", "fragile", "intermittent"))
    reproduction = any(marker in signals for marker in ("needs-reproduction", "needs reproduction", "reproduce", "steps to reproduce"))
    has_patch = "has-patch" in keywords or "has patch" in signals
    needs_patch = "needs-patch" in keywords or "needs patch" in signals
    needs_testing = "needs-testing" in keywords or "needs testing" in signals
    feedback = any(marker in keywords for marker in ("dev-feedback", "reporter-feedback"))
    dev_feedback = "dev-feedback" in keywords or "2nd-opinion" in keywords or "second-opinion" in keywords
    good_first_bug = "good-first-bug" in keywords or "good first bug" in signals
    open_pr = _truthy_ticket_signal(ticket, "github_pr", "github_pr_url", "pr_url", "pull_request")

    modified = parse_datetime(str(ticket.get("modified") or ""))
    age_days = max(0, (reference_time - modified.astimezone(timezone.utc)).days) if modified else None
    if age_days is None:
        freshness_state = "unknown"
    elif age_days <= 14:
        freshness_state = "fresh"
    elif age_days <= 90:
        freshness_state = "recent"
    else:
        freshness_state = "stale"

    if accessibility:
        opportunity_class = "accessibility-testing"
        expected_type = "accessibility-review"
        profiles = ["build.wordpress", "browser.accessibility-smoke"]
        hypothesis = "Provide focused accessibility verification against the current patch or ticket state, including semantic browser evidence that can change maintainer confidence."
    elif documentation:
        opportunity_class = "documentation-review"
        expected_type = "documentation-review"
        profiles = ["docs.static-review"]
        hypothesis = "Review the exact documentation or DocBlock concern and contribute a narrow confirmation, correction, or patch only if current upstream text still needs it."
    elif unit_tests:
        opportunity_class = "unit-test-review" if has_patch else "regression-test-only"
        expected_type = "regression-test-review" if has_patch else "regression-test-authoring"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Use the official WordPress test suite to verify or author focused regression coverage for the current ticket behavior."
    elif fragile_tests:
        opportunity_class = "failing-fragile-test-reproduction"
        expected_type = "test-failure-reproduction"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Reproduce the reported test instability or failure on exact revisions and report bounded evidence instead of proposing broad infrastructure changes."
    elif performance:
        opportunity_class = "performance-validation"
        expected_type = "performance-evidence"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Run bounded performance-oriented verification or code review where current ticket evidence shows a concrete measurable concern."
    elif php_runtime:
        opportunity_class = "php-runtime-compatibility"
        expected_type = "runtime-compatibility-review"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Verify the exact PHP/runtime compatibility claim on supported environments and contribute focused evidence or a bounded fix."
    elif build_tooling:
        opportunity_class = "build-tooling"
        expected_type = "tooling-reproduction"
        profiles = ["build.wordpress"]
        hypothesis = "Reproduce the build/tooling issue with the official repository workflow and report exact command/output evidence."
    elif responsive:
        opportunity_class = "responsive-mobile-testing"
        expected_type = "browser-test-report"
        profiles = ["build.wordpress", "browser.wordpress-admin"]
        hypothesis = "Capture exact desktop/mobile behavior for the current patch or ticket state and explain whether it resolves the responsive issue."
    elif visual:
        opportunity_class = "browser-ui-testing"
        expected_type = "browser-test-report"
        profiles = ["build.wordpress", "browser.wordpress-admin"]
        hypothesis = "Exercise the visible UI/browser flow on exact base and head revisions and provide nonduplicative evidence with screenshots only when useful."
    elif has_patch and freshness_state == "stale":
        opportunity_class = "stale-patch-refresh"
        expected_type = "patch-refresh"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Determine whether the stale patch still applies or needs a minimal refresh before maintainers can evaluate it."
    elif needs_patch:
        opportunity_class = "bounded-needs-patch"
        expected_type = "patch"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Investigate the current bug and prepare a narrowly scoped patch only if the ticket evidence supports a bounded implementation."
    elif reproduction:
        opportunity_class = "maintainer-requested-reproduction"
        expected_type = "reproduction-report"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Reproduce the maintainer-requested behavior on exact revisions and contribute a clear pass/fail report."
    elif dev_feedback:
        opportunity_class = "dev-feedback-review"
        expected_type = "2nd-opinion-review"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Answer the current dev-feedback question with exact code/test evidence rather than repeating generic testing."
    elif good_first_bug and has_patch:
        opportunity_class = "meaningful-good-first-bug"
        expected_type = "patch-review"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Use the good-first-bug scope only when there is a technically meaningful patch or verification question to resolve."
    elif has_patch and freshness_state in {"fresh", "recent"}:
        opportunity_class = "recent-patch-verification"
        expected_type = "patch-review"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Review or test the current patch while it is fresh enough that maintainer context is likely still active."
    elif has_patch or needs_testing or feedback:
        opportunity_class = "needs-testing-verification"
        expected_type = "test-report"
        profiles = ["build.wordpress", "phpunit.focused"]
        hypothesis = "Produce a focused, nonduplicative test report for the current ticket state, with exact revisions and result evidence."
    else:
        opportunity_class = "scoped-investigation"
        expected_type = "scoped-investigation"
        profiles = ["build.wordpress"]
        hypothesis = "Perform a bounded current-state investigation before deciding whether any public contribution is useful."

    if accessibility:
        visual_relevance = "useful"
        visual_reason = "A focused screenshot may help locate the accessibility state, but semantic browser evidence remains primary."
    elif visual:
        visual_relevance = "useful"
        visual_reason = "The ticket describes a visible or interaction state where exact-revision screenshots may help maintainers."
    else:
        visual_relevance = "not-relevant"
        visual_reason = "The available ticket signals do not indicate that a screenshot would add material evidence."

    duplication_reasons: list[str] = []
    comments = ticket.get("comment_count")
    if isinstance(comments, int) and comments > 30:
        duplication_reasons.append("large-discussion-requires-fresh-read")
    if radar_state.get("status") in {"tested", "commented", "committed"}:
        duplication_reasons.append("radar-records-prior-contribution")
    duplication_level = "high" if duplication_reasons else "low"

    blockers: list[str] = []
    status = str(ticket.get("status") or "").lower()
    if status in {"closed", "fixed", "wontfix", "duplicate", "invalid"} or ticket.get("resolution"):
        blockers.append("ticket-not-open")
    if radar_state.get("status") == "reject":
        blockers.append("radar-review-rejected")
    if has_patch and freshness_state == "stale":
        blockers.append("patch-refresh-required-before-verification")
    eligibility_state = "blocked" if blockers else "requires-upstream-validation"

    weight = "large" if opportunity_class in {"bounded-needs-patch", "stale-patch-refresh", "performance-validation"} else (
        "medium" if len(profiles) > 1 else "small"
    )
    skills = ["wordpress-core"]
    if "phpunit.focused" in profiles:
        skills.append("phpunit")
    if any(profile.startswith("browser.") for profile in profiles):
        skills.append("browser-testing")
    if accessibility:
        skills.append("accessibility")
    if documentation:
        skills.append("documentation")

    recommended_class, confidence, public_reason = _derive_recommended_contribution(
        ticket=ticket,
        signals=signals,
        keywords=keywords,
        freshness_state=freshness_state,
        age_days=age_days,
        has_patch=has_patch,
        needs_testing=needs_testing,
        unit_tests=unit_tests,
        visual=visual,
        accessibility=accessibility,
        documentation=documentation,
        performance=performance,
        php_runtime=php_runtime,
        reproduction=reproduction,
        dev_feedback=dev_feedback,
        feedback=feedback,
    )
    source_coverage = _derive_public_source_coverage(ticket=ticket, keywords=keywords, has_patch=has_patch, open_pr=open_pr)
    if recommended_class == "NO_CLEAR_CONTRIBUTION" and "ticket-not-open" not in blockers:
        blockers.append("no-clear-nonduplicative-contribution")
        eligibility_state = "blocked"

    return {
        "opportunity_class": opportunity_class,
        "expected_contribution_type": expected_type,
        "contribution_hypothesis": hypothesis,
        "recommendedContributionClass": recommended_class,
        "confidence": confidence,
        "reason": public_reason,
        "evidenceFreshness": {
            "state": freshness_state,
            "modifiedAt": ticket.get("modified"),
            "ageDays": age_days,
        },
        "source_coverage": source_coverage,
        "required_evidence_profiles": profiles,
        "visual_evidence": {"relevance": visual_relevance, "reason": visual_reason},
        "relevant_skills": skills,
        "upstream_freshness": {
            "state": freshness_state,
            "modified_at": ticket.get("modified"),
            "age_days": age_days,
        },
        "duplication_risk": {"level": duplication_level, "reasons": duplication_reasons},
        "likely_hwp_channel": "core-trac-comment",
        "engineering_weight": weight,
        "eligibility": {"state": eligibility_state, "blockers": blockers},
        "supply_quality": {
            "current_ticket_state_required": True,
            "fresh_upstream_read_required": True,
            "nonduplication_check_required": True,
            "current_patch_identity_required": has_patch,
            "missing_patch_head_base": has_patch,
            "screenshot_candidate": visual_relevance in {"required", "useful"},
            "backend_only_candidate": not visual and any(profile in profiles for profile in ("phpunit.focused", "build.wordpress")),
        },
    }


def counted(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"key": key, "count": counter[key]} for key in sorted(counter)]


def age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 14:
        return "0-14-days"
    if age_days <= 60:
        return "15-60-days"
    if age_days <= 180:
        return "61-180-days"
    if age_days <= 730:
        return "181-730-days"
    return "over-730-days"


def build_supply_diagnostics(
    opportunity_set: dict[str, Any],
    collection: dict[str, Any],
    snapshot_id: str,
) -> dict[str, Any]:
    by_class: Counter[str] = Counter()
    by_recommended_class: Counter[str] = Counter()
    by_confidence: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    stale: Counter[str] = Counter()
    duplicate: Counter[str] = Counter()
    missing_environment: Counter[str] = Counter()
    missing_patch_identity: Counter[str] = Counter()
    lifecycle: Counter[str] = Counter()
    ages: Counter[str] = Counter()
    screenshot = 0
    backend_only = 0
    already_satisfied = 0

    for record in opportunity_set["opportunities"]:
        qualification = record["qualification"]
        opportunity_class = qualification["opportunity_class"]
        by_class[opportunity_class] += 1
        by_recommended_class[qualification["recommendedContributionClass"]] += 1
        by_confidence[qualification["confidence"]] += 1
        lifecycle[qualification["eligibility"]["state"]] += 1
        for blocker in qualification["eligibility"]["blockers"]:
            rejected[blocker] += 1
        freshness = qualification["upstream_freshness"]
        ages[age_bucket(freshness["age_days"])] += 1
        if freshness["state"] == "stale":
            stale[opportunity_class] += 1
        if qualification["duplication_risk"]["level"] in {"medium", "high"}:
            duplicate[qualification["duplication_risk"]["level"]] += 1
        if not qualification["required_evidence_profiles"]:
            missing_environment[opportunity_class] += 1
        if qualification["supply_quality"]["missing_patch_head_base"]:
            missing_patch_identity[opportunity_class] += 1
        if qualification["supply_quality"]["screenshot_candidate"]:
            screenshot += 1
        if qualification["supply_quality"]["backend_only_candidate"]:
            backend_only += 1
        if record.get("radar_state", {}).get("status") in {"tested", "commented", "committed"} or record.get("radar_state", {}).get("received_props") is True:
            already_satisfied += 1

    query_rows = {
        item["query_slug"]: item["row_count"]
        for item in collection["query_evidence"]
    }
    diagnostics = {
        "schema": "supply-diagnostics.v1",
        "version": 1,
        "collection_id": collection["collection_id"],
        "snapshot_id": snapshot_id,
        "opportunity_count": len(opportunity_set["opportunities"]),
        "query_rows": query_rows,
        "qualified_candidates_by_class": counted(by_class),
        "recommended_contribution_classes": counted(by_recommended_class),
        "recommended_contribution_confidence": counted(by_confidence),
        "rejected_candidates_by_reason": counted(rejected),
        "stale_candidates_by_class": counted(stale),
        "duplicate_candidates_by_risk": counted(duplicate),
        "missing_reproducible_environments_by_class": counted(missing_environment),
        "missing_patch_head_base_by_class": counted(missing_patch_identity),
        "already_satisfied_count": already_satisfied,
        "screenshot_suitable_count": screenshot,
        "backend_only_evidence_count": backend_only,
        "candidate_aging": counted(ages),
        "bottleneck_by_lifecycle_stage": counted(lifecycle),
    }
    failures = validate_named(diagnostics, "supply-diagnostics.v1")
    if failures:
        raise CertificationError("; ".join(failures))
    return diagnostics


def opportunity_key(ticket_id: str) -> str:
    return f"core-trac:{ticket_id}"


def opportunity_revision(material_state: dict[str, Any]) -> str:
    return f"opportunity-revision-v1-{canonical_hash(material_state)[:32]}"


def opportunity_material_state(
    *,
    ticket_id: str,
    ticket: dict[str, Any],
    discovery: dict[str, Any],
    ranking: dict[str, Any],
    radar_state: dict[str, Any],
) -> dict[str, Any]:
    """Return only material fields that should wake a controller.

    This intentionally excludes generated timestamps, collection identity,
    snapshot identity, source artifact paths, and other publication noise.
    """
    return {
        "schema": "opportunity-material-state.v1",
        "version": 1,
        "ticket": {
            "id": ticket_id,
            "status": ticket["status"],
            "resolution": ticket["resolution"],
            "milestone": ticket["milestone"],
            "keywords": ticket["keywords"],
            "modified": ticket["modified"],
            "component": ticket["component"],
            "owner": ticket["owner"],
        },
        "discovery": {
            "tracks": discovery["tracks"],
            "sources": [
                {
                    "query_slug": source["query_slug"],
                    "source_identity": source["source_identity"],
                    "track": source["track"],
                }
                for source in discovery["sources"]
            ],
        },
        "ranking": {
            "score": ranking["score"],
            "tier": ranking["tier"],
            "scoring_version": ranking["scoring_version"],
            "breakdown": ranking["breakdown"],
            "complexity_markers": ranking["complexity_markers"],
        },
        "radar_state": radar_state,
    }


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
    ticket = {
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
    }
    discovery = {
        "sources": sources,
        "tracks": sorted({source["track"] for source in sources}),
    }
    ranking = {
        "score": opportunity.score,
        "tier": tier,
        "tier_label": tier_label,
        "scoring_version": scoring_version,
        "reasons": list(opportunity.reasons),
        "breakdown": _score_breakdown(opportunity.reasons),
        "complexity_markers": complexity,
    }
    qualification = derive_opportunity_profile(
        ticket=ticket,
        discovery=discovery,
        radar_state=radar_state,
        reference_time=parse_datetime(selection.identity) or datetime(1970, 1, 1, tzinfo=timezone.utc),
    )
    material = opportunity_material_state(
        ticket_id=opportunity.ticket_id,
        ticket=ticket,
        discovery=discovery,
        ranking=ranking,
        radar_state=radar_state,
    )
    return {
        "schema": "opportunity.v1",
        "version": 1,
        "opportunityKey": opportunity_key(opportunity.ticket_id),
        "opportunityRevision": opportunity_revision(material),
        "ticket": ticket,
        "discovery": discovery,
        "ranking": ranking,
        "radar_state": radar_state,
        "qualification": qualification,
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
        "schema_versions": sorted(SCHEMA_FILES),
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
    code: str = "OK",
    stages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "execution-result.v1",
        "version": 1,
        "operation": operation,
        "status": status,
        "code": code,
        "started_at": context.generated_iso,
        "completed_at": context.generated_iso,
        "reference_time": context.generated_iso,
        "input_identities": inputs or [],
        "output_identities": outputs or [],
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "retry_safe": True,
        "stage_results": stages or [],
    }


@dataclass(frozen=True)
class CertificationBundle:
    collection: dict[str, Any]
    opportunities: dict[str, Any]
    diagnostics: dict[str, Any]
    snapshot: dict[str, Any]
    manifest_sha256: str
    result: dict[str, Any]

    def files(self) -> dict[str, bytes]:
        return {
            "collection.json": canonical_json(self.collection),
            "opportunities.json": canonical_json(self.opportunities),
            "supply-diagnostics.json": canonical_json(self.diagnostics),
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
    diagnostics = build_supply_diagnostics(opportunity_set, collection, snapshot_id)
    collection_bytes = canonical_json(collection)
    opportunity_bytes = canonical_json(opportunity_set)
    diagnostics_bytes = canonical_json(diagnostics)
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
            {"path": "supply-diagnostics.json", "sha256": sha256_bytes(diagnostics_bytes)},
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
    return CertificationBundle(collection, opportunity_set, diagnostics, snapshot, manifest_hash, result)


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
            inputs=[selection.identity], errors=[str(error)], code="CERTIFICATION_FAILED",
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
    required = ("collection.json", "opportunities.json", "supply-diagnostics.json", "snapshot.json", "snapshot.sha256")
    missing = [name for name in required if not (current_dir / name).exists()]
    if missing:
        raise CertificationError(f"missing certified artifacts: {', '.join(missing)}")
    collection = json.loads((current_dir / "collection.json").read_text(encoding="utf-8"))
    opportunities = json.loads((current_dir / "opportunities.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((current_dir / "supply-diagnostics.json").read_text(encoding="utf-8"))
    snapshot = json.loads((current_dir / "snapshot.json").read_text(encoding="utf-8"))
    errors = validate_named(collection, "collection.v1", schemas_dir) + validate_named(snapshot, "snapshot.v1", schemas_dir) + validate_named(diagnostics, "supply-diagnostics.v1", schemas_dir)
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
    if diagnostics.get("snapshot_id") != snapshot.get("snapshot_id") or diagnostics.get("collection_id") != collection.get("collection_id"):
        errors.append("diagnostics identity mismatch")
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
    if diagnostics.get("opportunity_count") != snapshot.get("opportunity_count"):
        errors.append("diagnostics opportunity count mismatch")
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
