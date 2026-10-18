#!/usr/bin/env python3
"""Turn timestamped Radar observations into the single Fabric candidate feed."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "core-trac-v2-source-registry.json"
SCORING_PATH = ROOT / "config" / "scoring.json"
SCHEMA = "radar-candidate-feed.v2"
SOURCE_INDEX_SOURCE_ID = "THEME_CHECK_GITHUB"
SOURCE_INDEX_MAX_CANDIDATES = 256
SOURCE_INDEX_MAX_BYTES = 512 * 1024
OBSERVABILITY_SOURCE_FAMILIES = {
    "CORE_TRAC",
    "MAKE_TEST_RELEASE_SIGNALS",
    "CONTRIBUTOR_PATHWAYS",
    "CORE_DEVELOPER_DOCS",
    "ACCESSIBILITY_REQUESTS",
    "THEME_CHECK_GITHUB",
    "MAKE_THEMES_REQUESTS",
    "WORDPRESS_RELEASES",
}
EXCLUSION_REASONS = (
    "missing_identity",
    "reconciliation_only",
    "non_actionable_status",
    "no_family_signal",
    "acquisition_failed",
    "semantic_validation_failed",
)
CORE_FAMILY = "CORE_TRAC"
DIRECT = "DIRECT_OPPORTUNITY"
SIGNAL = "SIGNAL"
RECONCILIATION = "RECONCILIATION"
NON_ACTIONABLE_STATUSES = {"closed", "resolved", "fixed", "invalid", "wontfix", "wont-fix"}
REQUIRED_ROW_FIELDS = {"id", "summary", "status"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any, length: int = 32) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()[:length]


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def load_scoring(path: Path = SCORING_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != "radar-scoring-v2":
        raise ValueError("unsupported scoring configuration")
    return value


def validate_observability_categories(path: Path = ROOT / "config" / "wave2-sources.json") -> None:
    configured = {str(item.get("sourceFamily") or "") for item in json.loads(path.read_text(encoding="utf-8")).get("sources", [])}
    missing = sorted(configured - OBSERVABILITY_SOURCE_FAMILIES)
    if missing:
        raise ValueError(f"source categories lack explicit count/exclusion handling: {', '.join(missing)}")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def latest_by_source(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for observation in observations:
        source_id = str(observation.get("sourceId") or "").strip()
        if not source_id:
            continue
        current = latest.get(source_id)
        if current is None or (parse_time(observation.get("observedAt")) or datetime.min.replace(tzinfo=timezone.utc)) > (parse_time(current.get("observedAt")) or datetime.min.replace(tzinfo=timezone.utc)):
            latest[source_id] = observation
    return latest


def row_identity(row: dict[str, Any], source: dict[str, Any]) -> str | None:
    for key in (source.get("identityField"), "id", "ticket", "ticket_id", "number", "slug", "url"):
        if key and str(row.get(key, "")).strip():
            return str(row[key]).strip()
    return None


def row_keywords(row: dict[str, Any]) -> set[str]:
    value = row.get("keywords", row.get("labels", ""))
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return {item for item in str(value or "").replace(",", " ").split() if item}


def validate_rows(source: dict[str, Any], rows: list[dict[str, Any]], result: str) -> dict[str, Any]:
    rules = source.get("semanticValidation") or {}
    if result != "success":
        return {"state": "failed", "findings": ["acquisition did not succeed"]}
    if not rows and rules.get("allowEmpty", False):
        return {"state": "passed", "findings": []}
    findings: list[str] = []
    expected = set(source.get("expectedFields") or [])
    forbidden_statuses = {str(item).lower() for item in rules.get("statusNot", [])}
    for index, row in enumerate(rows):
        missing = sorted(field for field in expected if field in REQUIRED_ROW_FIELDS and field not in row)
        if missing:
            findings.append(f"row {index} missing fields: {', '.join(missing)}")
        if "keywords" in row:
            keywords = row_keywords(row)
            missing_all = [item for item in rules.get("requiredKeywordsAll", []) if item.lower() not in keywords]
            if missing_all:
                findings.append(f"row {index} missing required keywords: {', '.join(missing_all)}")
            any_keywords = {item.lower() for item in rules.get("requiredKeywordsAny", [])}
            if any_keywords and not any_keywords.intersection(keywords):
                findings.append(f"row {index} missing any expected keyword")
            forbidden = [item for item in rules.get("forbiddenKeywordsAny", []) if item.lower() in keywords]
            if forbidden:
                findings.append(f"row {index} contains forbidden keyword: {', '.join(forbidden)}")
        if str(row.get("status", "")).lower() in forbidden_statuses:
            findings.append(f"row {index} has forbidden status: {row.get('status')}")
    return {"state": "passed" if not findings else "failed", "findings": findings}


def source_definition(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    for source in registry.get("sources", []):
        if source.get("id") == observation.get("sourceId"):
            return source
    return {
        "id": observation["sourceId"],
        "sourceFamily": observation.get("sourceFamily", "UNKNOWN"),
        "sourceRole": observation.get("sourceRole", DIRECT),
        "semanticMeaning": observation.get("semanticMeaning", "Public source observation."),
        "candidateFamilyMappings": observation.get("candidateFamilyMappings", []),
        "semanticValidation": observation.get("semanticValidation", {}),
        "identityField": observation.get("identityField"),
        "resourceType": observation.get("resourceType", "PUBLIC_RESOURCE"),
        "sourceCompleteness": observation.get("sourceCompleteness"),
    }


def source_health(source: dict[str, Any], observation: dict[str, Any] | None, prior: dict[str, Any] | None, coverage_by_family: dict[str, str] | None = None) -> dict[str, Any]:
    result = str((observation or {}).get("acquisitionResult", "failed"))
    semantic = validate_rows(source, list((observation or {}).get("rows") or []), result)
    healthy = result == "success" and semantic.get("state") == "passed"
    had_prior = bool(prior and prior.get("rows"))
    return {
        "sourceId": source["id"],
        "sourceFamily": source.get("sourceFamily", CORE_FAMILY if source["id"].startswith("core-trac-") else "UNKNOWN"),
        "sourceRole": source.get("sourceRole", DIRECT),
        "state": "healthy" if healthy else ("degraded" if had_prior else "failed"),
        "freshness": "fresh" if healthy else ("stale" if had_prior else "none"),
        "observedAt": (observation or {}).get("observedAt") or (prior or {}).get("observedAt"),
        "sourceRevision": (observation or {}).get("sourceRevision") or (prior or {}).get("sourceRevision"),
        "acquisitionResult": result,
        "coverage": (observation or {}).get("sourceCompleteness") or (prior or {}).get("sourceCompleteness") or source.get("sourceCompleteness") or (coverage_by_family or {}).get(source.get("sourceFamily") or (CORE_FAMILY if source["id"].startswith("core-trac-") else "UNKNOWN"), "UNKNOWN"),
        "failure": None if healthy else ("SOURCE_OBSERVATION_FAILED_LAST_KNOWN_GOOD_RETAINED" if had_prior else "SOURCE_OBSERVATION_FAILED"),
        "semanticValidation": semantic,
    }


def material_resource(resource: dict[str, Any]) -> str:
    material = {key: resource[key] for key in ("id", "title", "url", "upstreamState", "sourceMemberships")}
    return f"resource-revision-v2-{digest(material)}"


def membership(source: dict[str, Any], observation: dict[str, Any], row: dict[str, Any], semantic: dict[str, Any], freshness: str = "fresh", present: bool = True) -> dict[str, Any]:
    return {
        "sourceId": source["id"],
        "sourceFamily": source.get("sourceFamily", CORE_FAMILY),
        "sourceRole": source.get("sourceRole", DIRECT),
        "semanticMeaning": source.get("semanticMeaning", "Public source observation."),
        "sourceUrl": observation.get("exactUpstreamUrl") or source.get("csvUrl") or source.get("htmlUrl"),
        "sourceRevision": observation.get("sourceRevision"),
        "observedAt": observation.get("observedAt"),
        "freshness": freshness,
        "presentInCurrentObservation": present,
        "semanticValidation": semantic,
        "candidateFamilyMappings": deepcopy(source.get("candidateFamilyMappings") or observation.get("candidateFamilyMappings") or row.get("candidateFamilyMappings") or []),
        "evidence": deepcopy(row),
        "limitations": list(source.get("limitations") or []),
    }


def build_feed(payload: dict[str, Any], registry: dict[str, Any] | None = None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    validate_observability_categories()
    scoring = load_scoring()
    observations = list(payload.get("observations") or [])
    coverage_by_family = {
        str(item.get("sourceFamily")): str(item.get("completeness") or "UNKNOWN")
        for item in json.loads((ROOT / "config" / "wave2-sources.json").read_text(encoding="utf-8")).get("sources", [])
        if item.get("sourceFamily")
    }
    coverage_by_family.setdefault(CORE_FAMILY, "PARTIAL")
    prior_observations = list((payload.get("previous") or {}).get("observations") or [])
    if previous:
        prior_observations.extend(previous.get("observations") or [])
    current = latest_by_source(observations)
    prior = latest_by_source(prior_observations)
    definitions = {source["id"]: source for source in registry.get("sources", [])}
    definitions.update({item["sourceId"]: source_definition(item, registry) for item in observations if item.get("sourceId")})
    definitions.update({item["sourceId"]: source_definition(item, registry) for item in prior_observations if item.get("sourceId")})
    health = []
    resources: dict[str, dict[str, Any]] = {}
    for source_id in sorted(definitions):
        source = definitions[source_id]
        observation = current.get(source_id)
        old = prior.get(source_id)
        result = str((observation or {}).get("acquisitionResult", "failed"))
        rows = list((observation or {}).get("rows") or [])
        semantic = validate_rows(source, rows, result)
        health_record = source_health(source, observation, old, coverage_by_family)
        usable = result == "success" and semantic.get("state") == "passed"
        evidence_observation = observation if usable else (old if old and health_record["freshness"] == "stale" else None)
        acquired_counts = (observation or {}).get("acquisitionCounts") or {}
        fetched_rows = acquired_counts.get("fetchedRows", len(rows) if result == "success" else 0)
        identity_rows = rows if usable else list((old or {}).get("rows") or []) if evidence_observation is not None else []
        deduplicated_resources = acquired_counts.get("deduplicatedResources")
        if deduplicated_resources is None:
            deduplicated_resources = len({row_identity(row, source) for row in identity_rows if row_identity(row, source)})
        observational_category_count = acquired_counts.get("observationalCategories")
        if observational_category_count is None:
            observational_category_count = sum(
                len((row.get("resource") or {}).get("observationalCategories") or row.get("observationalCategories") or [])
                for row in identity_rows
            )
        health_record["counts"] = {
            "fetchedRows": int(fetched_rows),
            "deduplicatedResources": int(deduplicated_resources),
            "emittedFamilySignals": 0,
            "observationalCategories": int(observational_category_count),
            "excludedByReason": {reason: 0 for reason in EXCLUSION_REASONS},
        }
        if observation is None or result != "success":
            health_record["counts"]["excludedByReason"]["acquisition_failed"] = 1
        elif observation is not None and semantic.get("state") != "passed":
            health_record["counts"]["excludedByReason"]["semantic_validation_failed"] = 1
        health.append(health_record)
        if not evidence_observation:
            continue
        evidence_rows = list(evidence_observation.get("rows") or [])
        evidence_semantic = semantic if usable else validate_rows(source, evidence_rows, "success")
        for row in evidence_rows:
            identity = row_identity(row, source)
            exclusions = health_record["counts"]["excludedByReason"]
            if not identity:
                exclusions["missing_identity"] += 1
                continue
            if source.get("sourceRole") == RECONCILIATION:
                exclusions["reconciliation_only"] += 1
                continue
            if str(row.get("status") or row.get("state") or "").strip().lower() in NON_ACTIONABLE_STATUSES:
                exclusions["non_actionable_status"] += 1
                continue
            if not (source.get("candidateFamilyMappings") or evidence_observation.get("candidateFamilyMappings") or row.get("candidateFamilyMappings")):
                exclusions["no_family_signal"] += 1
            family = source.get("sourceFamily") or evidence_observation.get("sourceFamily") or "UNKNOWN"
            resource_id = f"{str(family).lower().replace('_', '-')}:" + identity
            url = row.get("url") or row.get("htmlUrl") or (f"https://core.trac.wordpress.org/ticket/{identity}" if family == CORE_FAMILY else None)
            resource = resources.setdefault(resource_id, {
                "id": resource_id,
                "sourceFamily": family,
                "resourceType": source.get("resourceType", "CORE_TRAC_TICKET" if family == CORE_FAMILY else "PUBLIC_RESOURCE"),
                "identity": identity,
                "url": url,
                "title": str(row.get("summary") or row.get("title") or f"{family} {identity}"),
                "upstreamState": str(row.get("status") or row.get("state") or "unknown"),
                "sourceMemberships": [],
                "observedAt": evidence_observation.get("observedAt"),
            })
            resource["sourceMemberships"] = [m for m in resource["sourceMemberships"] if m["sourceId"] != source_id]
            resource["sourceMemberships"].append(membership(source, evidence_observation, row, evidence_semantic, health_record["freshness"], usable))
            resource["sourceMemberships"].sort(key=lambda item: item["sourceId"])
            resource["observedAt"] = max(resource.get("observedAt") or "", evidence_observation.get("observedAt") or "") or None

    for resource in resources.values():
        for membership_item in resource["sourceMemberships"]:
            source_health_item = next(item for item in health if item["sourceId"] == membership_item["sourceId"])
            source_health_item["counts"]["emittedFamilySignals"] += len({
                mapping.get("familyId") for mapping in membership_item.get("candidateFamilyMappings", []) if mapping.get("familyId")
            })

    candidates = []
    reference_time = payload.get("referenceTime") or max((item.get("observedAt") or "" for item in observations), default=None)
    for resource in resources.values():
        mappings: dict[str, dict[str, Any]] = {}
        for item in resource["sourceMemberships"]:
            for mapping in item.get("candidateFamilyMappings", []):
                family_id = mapping.get("familyId")
                if not family_id:
                    continue
                current_mapping = mappings.get(family_id)
                confidence = mapping.get("confidence", "medium")
                if not current_mapping or (confidence == "high" and current_mapping["confidence"] != "high"):
                    mappings[family_id] = {"familyId": family_id, "confidence": confidence, "sourceIds": []}
                mappings[family_id]["sourceIds"] = sorted(set(mappings[family_id]["sourceIds"]) | {item["sourceId"]})
        if not mappings:
            continue
        resource["sourceMemberships"].sort(key=lambda item: item["sourceId"])
        resource["revision"] = material_resource(resource)
        direct_count = sum(item["sourceRole"] == DIRECT for item in resource["sourceMemberships"])
        high_count = sum(item["confidence"] == "high" for item in mappings.values())
        stale = any(item["freshness"] == "stale" for item in resource["sourceMemberships"])
        keywords = set().union(*(row_keywords(item["evidence"]) for item in resource["sourceMemberships"]))
        score = scoring["base"]
        score += scoring["bonuses"]["direct_opportunity"] if direct_count else 0
        score += min(high_count, scoring["bonuses"]["high_confidence_family_cap"]) * scoring["bonuses"]["high_confidence_family"]
        score += min(len(resource["sourceMemberships"]), scoring["bonuses"]["corroborating_membership_cap"]) * scoring["bonuses"]["corroborating_membership"]
        reasons = [f"{direct_count} direct opportunity source membership(s)", f"{len(mappings)} approved contribution family candidate(s)"]
        if "needs-testing" in keywords or "needs-patch" in keywords:
            score += scoring["bonuses"]["explicit_need"]; reasons.append("explicit current contribution need")
        if stale:
            score -= scoring["penalties"]["stale"]; reasons.append("last-known-good evidence is stale")
        tier = "priority" if score >= scoring["tier_thresholds"]["priority"] else "standard" if score >= scoring["tier_thresholds"]["standard"] else "watch"
        candidate_id = f"candidate:v2:{digest({'resourceId': resource['id'], 'families': sorted(mappings)})}"
        candidate = {
            "id": candidate_id,
            "candidateId": candidate_id,
            "opportunityId": f"opportunity:v2:{resource['id']}",
            "resourceRefs": [{"id": resource["id"], "revision": resource["revision"]}],
            "relationships": [],
            "sourceFamily": resource["sourceFamily"],
            "sourceRevision": max((item.get("sourceRevision") or "" for item in resource["sourceMemberships"]), default=None) or None,
            "observedAt": resource.get("observedAt"),
            "resource": {key: resource[key] for key in ("id", "resourceType", "identity", "url", "title", "upstreamState", "revision")},
            "sourceMemberships": resource["sourceMemberships"],
            "familyCandidates": [mappings[key] for key in sorted(mappings)],
            "freshness": {"state": "stale" if stale else "fresh", "observedAt": resource.get("observedAt"), "referenceTime": reference_time},
            "whyNow": [item["semanticMeaning"] for item in resource["sourceMemberships"] if item["sourceRole"] == DIRECT] or ["Public source signal retained for context."],
            "score": {"value": score, "reasons": reasons},
            "derivedPriority": {"tier": tier, "score": score},
            "sourceHealth": [item for item in health if item["sourceId"] in {m["sourceId"] for m in resource["sourceMemberships"]}],
        }
        candidate["revision"] = f"candidate-revision-v2-{digest(candidate)}"
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["derivedPriority"]["score"], item["id"]))
    for index, item in enumerate(candidates, start=1):
        item["derivedPriority"]["order"] = index
    output = {
        "schema": SCHEMA,
        "version": 2,
        "referenceTime": reference_time,
        "candidateCount": len(candidates),
        "sourceHealth": sorted(health, key=lambda item: item["sourceId"]),
        "candidates": candidates,
    }
    output["feedRevision"] = f"candidate-feed-revision-v2-{digest(output)}"
    return output


def build_source_index(feed: dict[str, Any], source_id: str = SOURCE_INDEX_SOURCE_ID) -> bytes:
    """Return a deterministic, bounded candidate-feed snapshot for one source."""
    if feed.get("schema") != SCHEMA or feed.get("version") != 2 or not isinstance(feed.get("candidates"), list):
        raise ValueError("cannot index an invalid candidate feed")
    if feed.get("candidateCount") != len(feed["candidates"]):
        raise ValueError("cannot index a candidate feed with an invalid count")
    candidates = [candidate for candidate in feed["candidates"]
                  if any(item.get("sourceId") == source_id for item in candidate.get("sourceMemberships", []))]
    if len(candidates) > SOURCE_INDEX_MAX_CANDIDATES:
        raise ValueError("source candidate index exceeds the safe record limit")
    index = {
        "schema": SCHEMA,
        "version": 2,
        "sourceIndex": {"schema": "radar-source-candidate-index.v1", "sourceId": source_id},
        "referenceTime": feed.get("referenceTime"),
        "candidateCount": len(candidates),
        "sourceHealth": [item for item in feed.get("sourceHealth", []) if item.get("sourceId") == source_id],
        "candidates": candidates,
    }
    index["feedRevision"] = f"candidate-feed-revision-v2-{digest(index)}"
    encoded = (canonical_json(index) + "\n").encode("utf-8")
    if len(encoded) > SOURCE_INDEX_MAX_BYTES:
        raise ValueError("source candidate index exceeds the safe byte limit")
    return encoded


def load_input(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    observations = []
    for child in sorted(path.rglob("*.json")):
        value = json.loads(child.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("sourceId"):
            observations.append(value)
        elif isinstance(value, dict):
            observations.extend(value.get("observations") or [])
    return {"schema": "radar-raw-observation-set.v2", "version": 2, "observations": observations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="observation JSON file or timestamped observation directory")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "data" / "candidate-feed.json")
    parser.add_argument("--previous", type=Path, help="optional previous observation set for last-known-good retention")
    args = parser.parse_args()
    previous = load_input(args.previous) if args.previous else None
    output = build_feed(load_input(args.input), previous=previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
