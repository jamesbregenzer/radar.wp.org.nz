from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from contribution_returns import normalize_contribution_return_feed
from core_trac_v2 import (
    load_core_trac_source_registry,
    normalize_core_trac_observations,
    observation_fixture,
    source_registry_summary,
)


def row(ticket_id: str, keywords: str, summary: str = "Fixture ticket", status: str = "new") -> dict[str, str]:
    return {
        "id": ticket_id,
        "summary": summary,
        "status": status,
        "component": "Build/Test Tools",
        "owner": "",
        "type": "defect (bug)",
        "priority": "normal",
        "milestone": "6.9",
        "version": "trunk",
        "keywords": keywords,
        "time": "2026-10-06T00:00:00Z",
        "changetime": "2026-10-06T00:00:00Z",
        "comments": "4",
        "_comments": "4",
    }


class CoreTracV2SourceModelTests(unittest.TestCase):
    def test_source_registry_preserves_v2_semantics_without_legacy_sources(self):
        registry = load_core_trac_source_registry()
        summary = source_registry_summary(registry)
        sources = {source["id"]: source for source in registry["sources"]}

        self.assertEqual(summary["primarySourceCount"], 17)
        self.assertEqual(summary["legacyV1CompatibilitySourceCount"], 0)
        self.assertIn("core-trac-report-15-has-patch-needs-testing", sources)
        self.assertEqual(sources["core-trac-report-15-has-patch-needs-testing"]["semanticValidation"]["requiredKeywordsAll"], ["has-patch", "needs-testing"])
        self.assertNotIn("legacy-v1-general-needs-testing", sources)

    def test_overlapping_reports_dedupe_to_one_resource_with_all_memberships(self):
        observations = [
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("123", "has-patch needs-testing")]),
            observation_fixture("core-trac-report-13-has-patch", [row("123", "has-patch")]),
            observation_fixture("core-trac-report-22-active-tickets", [row("123", "has-patch needs-testing")]),
            observation_fixture("core-trac-report-18-release-blockers", [row("123", "has-patch needs-testing")]),
        ]

        model = normalize_core_trac_observations(observations)
        resource = next(item for item in model["resources"] if item["id"] == "core-trac:123")
        membership_ids = {item["sourceId"] for item in resource["sourceMemberships"]}

        self.assertEqual(len([item for item in model["resources"] if item["id"] == "core-trac:123"]), 1)
        self.assertEqual(membership_ids, {
            "core-trac-report-15-has-patch-needs-testing",
            "core-trac-report-13-has-patch",
            "core-trac-report-22-active-tickets",
            "core-trac-report-18-release-blockers",
        })
        self.assertEqual(len([candidate for candidate in model["candidates"] if candidate["resourceRefs"][0]["id"] == "core-trac:123"]), 1)

    def test_one_failed_shard_does_not_invalidate_successful_observations(self):
        observations = [
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("200", "has-patch needs-testing")]),
            observation_fixture("core-trac-report-16-needs-patch", [row("201", "needs-patch")], acquisition_result="failed"),
        ]

        model = normalize_core_trac_observations(observations)
        health = {item["sourceId"]: item for item in model["sourceHealth"]}

        self.assertIn("core-trac:200", {item["id"] for item in model["resources"]})
        self.assertNotIn("core-trac:201", {item["id"] for item in model["resources"]})
        self.assertEqual(health["core-trac-report-15-has-patch-needs-testing"]["state"], "certified")
        self.assertEqual(health["core-trac-report-16-needs-patch"]["state"], "failed")
        self.assertEqual(model["health"]["state"], "degraded")

    def test_failed_refresh_preserves_last_known_good_source_membership_as_stale(self):
        previous = normalize_core_trac_observations([
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("300", "has-patch needs-testing")]),
        ])

        current = normalize_core_trac_observations([
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [], acquisition_result="failed"),
        ], previous_model=previous)

        resource = next(item for item in current["resources"] if item["id"] == "core-trac:300")
        membership = next(item for item in resource["sourceMemberships"] if item["sourceId"] == "core-trac-report-15-has-patch-needs-testing")

        self.assertEqual(membership["freshness"], "last-known-good")
        self.assertFalse(membership["presentInCurrentObservation"])

    def test_candidate_identity_is_stable_but_revision_changes_with_material_resource_change(self):
        first = normalize_core_trac_observations([
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("400", "has-patch needs-testing", "Original summary")], observed_at="2026-10-06T12:00:00Z"),
        ])
        noisy = normalize_core_trac_observations([
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("400", "has-patch needs-testing", "Original summary")], observed_at="2026-10-06T13:00:00Z"),
        ])
        changed = normalize_core_trac_observations([
            observation_fixture("core-trac-report-15-has-patch-needs-testing", [row("400", "has-patch needs-testing", "Changed summary")], observed_at="2026-10-06T14:00:00Z"),
        ])

        self.assertEqual(first["candidates"][0]["candidateId"], noisy["candidates"][0]["candidateId"])
        self.assertEqual(first["candidates"][0]["candidateId"], changed["candidates"][0]["candidateId"])
        self.assertEqual(first["candidates"][0]["candidateRevision"], noisy["candidates"][0]["candidateRevision"])
        self.assertNotEqual(first["candidates"][0]["candidateRevision"], changed["candidates"][0]["candidateRevision"])

    def test_source_disappearance_does_not_unsafe_delete_candidate(self):
        previous = normalize_core_trac_observations([
            observation_fixture("core-trac-report-16-needs-patch", [row("500", "needs-patch")]),
        ])
        current = normalize_core_trac_observations([], previous_model=previous)

        self.assertIn("core-trac:500", {item["id"] for item in current["resources"]})
        self.assertTrue(current["candidates"])
        self.assertEqual(current["candidates"][0]["freshness"], "stale")

    def test_contribution_return_ingestion_projects_public_delivery_and_outcome(self):
        payload = {
            "schema": "radar-contribution-return-feed.v1",
            "version": 1,
            "sourceRevision": "fixture-return-feed",
            "returns": [
                {
                    "id": "fabric-public-delivery-core-54034",
                    "publicDeliveryUrl": "https://core.trac.wordpress.org/ticket/54034#comment:20",
                    "publicOutcomeUrl": "https://core.trac.wordpress.org/ticket/54034#comment:20",
                    "sourceResourceRef": {"id": "core-trac:54034"},
                    "sourceFamily": "CORE_TRAC",
                    "publicContributionType": "test-report",
                    "observedPublicDeliveryAt": "2026-10-06T12:00:00Z",
                    "verifiedPublicOutcomeAt": "2026-10-06T13:00:00Z",
                    "verificationSource": "core-trac-public-reread",
                    "outcomeFlags": {"accepted": True, "merged": False, "closed": False, "reopened": False, "propsObserved": False, "followUpNeeded": False},
                    "publicSummary": "Published public test evidence for #54034.",
                    "sourceRevision": "core-trac:54034:comment:20",
                },
                {
                    "id": "fabric-public-delivery-core-40339",
                    "publicDeliveryUrl": "https://core.trac.wordpress.org/ticket/40339#comment:4",
                    "sourceResourceRef": {"id": "core-trac:40339"},
                    "sourceFamily": "CORE_TRAC",
                    "publicContributionType": "review",
                    "observedPublicDeliveryAt": "2026-10-06T12:30:00Z",
                    "verificationSource": "core-trac-public-reread",
                    "outcomeFlags": {"accepted": False, "merged": False, "closed": False, "reopened": False, "propsObserved": False, "followUpNeeded": True},
                    "publicSummary": "Published public review for #40339.",
                    "sourceRevision": "core-trac:40339:comment:4",
                },
            ],
        }

        projection = normalize_contribution_return_feed(payload)
        by_ticket = {item["ticketId"]: item for item in projection["contributions"]}

        self.assertEqual(set(by_ticket), {"54034", "40339"})
        self.assertEqual(len(projection["outcomes"]), 2)
        self.assertTrue(any(outcome["outcomeFlags"]["accepted"] for outcome in projection["outcomes"]))


if __name__ == "__main__":
    unittest.main()
