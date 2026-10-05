#!/usr/bin/env python3
"""Generate deterministic Static Assets projections from certified Radar data."""

from __future__ import annotations

import json
from pathlib import Path

from certification import CERTIFIED_CURRENT, canonical_json, file_sha256, validate_named, verify_certified
from radarv2 import WORDPRESS_DEVELOP_SOURCE, load_wordpress_develop_source, payload_hashes, project_v2

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "docs" / "radar" / "api" / "v1"
API_V2_DIR = ROOT / "docs" / "radar" / "api" / "v2"
CONTRIBUTION_STATE = ROOT / "data" / "contributions" / "contribution-state.json"


def load_contribution_state(path: Path = CONTRIBUTION_STATE) -> dict:
    if not path.exists():
        return {"schema": "contribution-state.v1", "version": 1, "contributions": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_named(payload, "contribution-state.v1")
    if errors:
        raise RuntimeError("contribution-state.v1 validation failed: " + "; ".join(errors))
    return payload


def contribution_projection(contribution_state: dict) -> dict:
    records = []
    for contribution in contribution_state.get("contributions", []):
        if contribution.get("lifecycle_state") not in {"PUBLIC_DELIVERY_VERIFIED", "UPSTREAM_ACCEPTED", "FOLLOWUP_REQUIRED"}:
            continue
        record = {
            "ticketId": str(contribution["ticket_id"]),
            "opportunityKey": contribution["opportunityKey"],
            "publicUrl": contribution["public_url"],
            "contributionType": contribution["contributionType"],
            "testedHeadSha": contribution["testedHeadSha"],
            "testedBaseSha": contribution["testedBaseSha"],
            "verifiedAt": contribution["verifiedAt"],
            "lifecycleState": contribution["lifecycle_state"],
        }
        if contribution.get("changeset"):
            record["changeset"] = str(contribution["changeset"])
        if contribution.get("received_props") is True:
            record["props"] = True
        records.append(record)
    return {
        "schema": "verified-contribution-outcomes.v1",
        "version": 1,
        "contributions": records,
    }


def machine_feed_payload(snapshot: dict, opportunity_set: dict, contribution_state: dict) -> dict:
    contributions = contribution_projection(contribution_state)["contributions"]
    feed = {
        "schema": "radar-machine-feed.v1",
        "version": 1,
        "snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "collection_id": snapshot["collection_id"],
            "dataset_sha256": snapshot["dataset_sha256"],
            "reference_time": snapshot["reference_time"],
            "source_revision": snapshot.get("source_revision"),
            "scoring_version": snapshot["scoring_version"],
            "opportunity_count": snapshot["opportunity_count"],
        },
        "opportunities": [
            {
                "ticketId": record["ticket"]["id"],
                "opportunityKey": record["opportunityKey"],
                "opportunityRevision": record["opportunityRevision"],
                "rank": index + 1,
                "tier": record["ranking"]["tier"],
                "score": record["ranking"]["score"],
                "qualification": {
                    "opportunityClass": record["qualification"]["opportunity_class"],
                    "recommendedContributionClass": record["qualification"]["recommendedContributionClass"],
                    "confidence": record["qualification"]["confidence"],
                    "reason": record["qualification"]["reason"],
                    "evidenceFreshness": record["qualification"]["evidenceFreshness"],
                    "sourceCoverage": record["qualification"]["source_coverage"],
                    "expectedContributionType": record["qualification"]["expected_contribution_type"],
                    "contributionHypothesis": record["qualification"]["contribution_hypothesis"],
                    "requiredEvidenceProfiles": record["qualification"]["required_evidence_profiles"],
                    "visualEvidenceRelevance": record["qualification"]["visual_evidence"]["relevance"],
                    "relevantSkills": record["qualification"]["relevant_skills"],
                    "upstreamFreshness": record["qualification"]["upstream_freshness"]["state"],
                    "duplicationRisk": record["qualification"]["duplication_risk"]["level"],
                    "likelyHwpChannel": record["qualification"]["likely_hwp_channel"],
                    "engineeringWeight": record["qualification"]["engineering_weight"],
                    "screenshotCandidate": record["qualification"]["supply_quality"]["screenshot_candidate"],
                    "backendOnlyCandidate": record["qualification"]["supply_quality"]["backend_only_candidate"],
                    "missingPatchHeadBase": record["qualification"]["supply_quality"]["missing_patch_head_base"],
                    "eligibilityState": record["qualification"]["eligibility"]["state"],
                    "blockers": record["qualification"]["eligibility"]["blockers"],
                },
            }
            for index, record in enumerate(opportunity_set["opportunities"])
        ],
        "verifiedContributions": contributions,
    }
    errors = validate_named(feed, "radar-machine-feed.v1")
    if errors:
        raise RuntimeError("radar-machine-feed.v1 validation failed: " + "; ".join(errors))
    return feed


def generate_api_assets(current_dir: Path = CERTIFIED_CURRENT, output_dir: Path = API_DIR) -> list[Path]:
    verified = verify_certified(current_dir)
    snapshot = json.loads((current_dir / "snapshot.json").read_text(encoding="utf-8"))
    opportunity_set = json.loads((current_dir / "opportunities.json").read_text(encoding="utf-8"))
    contribution_state = load_contribution_state()
    contributions = contribution_projection(contribution_state)
    contribution_errors = validate_named(contributions, "verified-contribution-outcomes.v1")
    if contribution_errors:
        raise RuntimeError("verified-contribution-outcomes.v1 validation failed: " + "; ".join(contribution_errors))
    machine_feed = machine_feed_payload(snapshot, opportunity_set, contribution_state)
    health = {
        "schema": "radar-health.v1",
        "version": 1,
        "status": "healthy",
        "snapshot_id": snapshot["snapshot_id"],
        "collection_id": snapshot["collection_id"],
        "certification_state": snapshot["certification"]["state"],
        "reference_time": snapshot["reference_time"],
        "opportunity_count": snapshot["opportunity_count"],
        "scoring_version": snapshot["scoring_version"],
        "source_revision": snapshot.get("source_revision"),
        "dataset_sha256": snapshot["dataset_sha256"],
        "warnings": snapshot["certification"].get("warnings", []),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("snapshot.json", "collection.json", "opportunities.json", "snapshot.sha256"):
        destination = output_dir / name
        destination.write_bytes((current_dir / name).read_bytes())
        paths.append(destination)
    diagnostics_path = output_dir / "supply-diagnostics.json"
    diagnostics_path.write_bytes((current_dir / "supply-diagnostics.json").read_bytes())
    paths.append(diagnostics_path)
    contributions_path = output_dir / "contributions.json"
    contributions_path.write_bytes(canonical_json(contributions))
    paths.append(contributions_path)
    machine_feed_path = output_dir / "machine-feed.json"
    machine_feed_path.write_bytes(canonical_json(machine_feed))
    paths.append(machine_feed_path)
    health_path = output_dir / "health.json"
    health_path.write_bytes(canonical_json(health))
    paths.append(health_path)
    # Verification result is intentionally not published; it only gates output.
    if verified["status"] != "success" or any(not path.exists() for path in paths):
        raise RuntimeError("certified API projection failed")
    paths.extend(generate_v2_api_assets(snapshot, collection=json.loads((current_dir / "collection.json").read_text(encoding="utf-8")),
                                        opportunity_set=opportunity_set, contributions=contributions))
    return paths


def generate_v2_api_assets(
    snapshot: dict,
    collection: dict,
    opportunity_set: dict,
    contributions: dict,
    output_dir: Path = API_V2_DIR,
) -> list[Path]:
    wordpress_develop = load_wordpress_develop_source(WORDPRESS_DEVELOP_SOURCE)
    payloads = project_v2(
        snapshot=snapshot,
        collection=collection,
        opportunities=opportunity_set,
        contributions=contributions,
        wordpress_develop=wordpress_develop,
    )
    hashes = payload_hashes(payloads)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, body in sorted(payloads.items()):
        destination = output_dir / name
        destination.write_bytes(body)
        if file_sha256(destination) != hashes[name]:
            raise RuntimeError(f"v2 API projection hash mismatch for {name}")
        paths.append(destination)
    return paths


def main() -> int:
    for path in generate_api_assets():
        print(f"Wrote {path.relative_to(ROOT)} ({file_sha256(path)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
