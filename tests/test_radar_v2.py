from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from radarv2 import github_ticket_index, load_gutenberg_source, load_wordpress_develop_source, project_v2


class RadarV2ProjectionTests(unittest.TestCase):
    def payloads(self, wordpress_develop=None, gutenberg=None, wave2_sources=None):
        snapshot = json.loads((ROOT / "data" / "certified" / "current" / "snapshot.json").read_text())
        collection = json.loads((ROOT / "data" / "certified" / "current" / "collection.json").read_text())
        opportunities = json.loads((ROOT / "data" / "certified" / "current" / "opportunities.json").read_text())
        contributions = json.loads((ROOT / "docs" / "radar" / "api" / "v1" / "contributions.json").read_text())
        return project_v2(
            snapshot=snapshot,
            collection=collection,
            opportunities=opportunities,
            contributions=contributions,
            wordpress_develop=wordpress_develop,
            gutenberg=gutenberg,
            wave2_sources=wave2_sources,
        )

    def contribution_return_projection(self):
        return {
            "schema": "radar-contribution-return-projection.v1",
            "version": 1,
            "sourceRevision": "fixture-public-return-feed",
            "contributions": [
                {
                    "id": "radar-contribution-v2-54034",
                    "returnId": "public-core-trac-54034-comment-20",
                    "resourceRef": {"id": "core-trac:54034"},
                    "sourceFamily": "CORE_TRAC",
                    "ticketId": "54034",
                    "publicUrl": "https://core.trac.wordpress.org/ticket/54034#comment:20",
                    "contributionType": "test-report",
                    "observedPublicDeliveryAt": "2026-10-06T00:13:53Z",
                    "verifiedPublicOutcomeAt": None,
                    "verificationSource": "core-trac-public-reread",
                    "publicSummary": "Public contribution evidence exists for #54034.",
                    "sourceRevision": "core-trac:54034:comment:20",
                    "outcomeFlags": {"accepted": False, "merged": False, "closed": False, "reopened": False, "propsObserved": False, "followUpNeeded": False},
                },
                {
                    "id": "radar-contribution-v2-40339",
                    "returnId": "public-core-trac-40339-comment-4",
                    "resourceRef": {"id": "core-trac:40339"},
                    "sourceFamily": "CORE_TRAC",
                    "ticketId": "40339",
                    "publicUrl": "https://core.trac.wordpress.org/ticket/40339#comment:4",
                    "contributionType": "patch-review",
                    "observedPublicDeliveryAt": "2026-10-06T03:45:20Z",
                    "verifiedPublicOutcomeAt": None,
                    "verificationSource": "core-trac-public-reread",
                    "publicSummary": "Public contribution evidence exists for #40339.",
                    "sourceRevision": "core-trac:40339:comment:4",
                    "outcomeFlags": {"accepted": False, "merged": False, "closed": False, "reopened": False, "propsObserved": False, "followUpNeeded": False},
                },
            ],
            "outcomes": [],
        }

    def test_v2_projection_is_repeatable(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        self.assertEqual(self.payloads(source, gutenberg), self.payloads(source, gutenberg))

    def test_change_event_ids_ignore_snapshot_timestamp_noise(self):
        source = load_wordpress_develop_source()
        snapshot = json.loads((ROOT / "data" / "certified" / "current" / "snapshot.json").read_text())
        collection = json.loads((ROOT / "data" / "certified" / "current" / "collection.json").read_text())
        opportunities = json.loads((ROOT / "data" / "certified" / "current" / "opportunities.json").read_text())
        contributions = json.loads((ROOT / "docs" / "radar" / "api" / "v1" / "contributions.json").read_text())
        first = project_v2(
            snapshot=snapshot,
            collection=collection,
            opportunities=opportunities,
            contributions=contributions,
            wordpress_develop=source,
        )
        noisy_snapshot = dict(snapshot)
        noisy_snapshot["snapshot_id"] = "snapshot-v1-ffffffffffffffffffffffff"
        noisy_snapshot["reference_time"] = "2026-10-06T17:00:00"
        second = project_v2(
            snapshot=noisy_snapshot,
            collection=collection,
            opportunities=opportunities,
            contributions=contributions,
            wordpress_develop=source,
        )
        first_events = json.loads(first["changes.json"])["events"]
        second_events = json.loads(second["changes.json"])["events"]
        self.assertEqual([item["id"] for item in first_events], [item["id"] for item in second_events])

    def test_v2_reports_github_degradation_without_blocking_trac(self):
        payloads = self.payloads(None)
        health = json.loads(payloads["health.json"])
        families = {item["sourceFamily"]: item for item in health["sourceFamilies"]}
        self.assertEqual(families["CORE_TRAC"]["health"]["state"], "certified")
        self.assertEqual(families["WORDPRESS_DEVELOP_GITHUB"]["health"]["state"], "degraded")
        self.assertEqual(families["GUTENBERG"]["health"]["state"], "degraded")
        self.assertEqual(health["status"], "degraded")

    def test_v2_opportunities_include_public_model_fields(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        opportunities = json.loads(self.payloads(source, gutenberg)["opportunities.json"])
        first = opportunities["opportunities"][0]
        self.assertTrue(first["id"].startswith("opportunity:v2:"))
        self.assertTrue(first["revision"].startswith("opportunity-revision-v2-"))
        self.assertTrue(first["legacyV1"]["opportunityKey"].startswith("core-trac:"))
        self.assertEqual(first["canonicalResource"]["sourceFamily"], "CORE_TRAC")
        self.assertTrue(first["canonicalResource"]["id"].startswith("core-trac:"))
        self.assertEqual(first["identity"]["canonicalResourceId"], first["canonicalResource"]["id"])
        self.assertTrue(first["requiresLiveRevalidation"])
        self.assertIn(first["qualification"]["state"], {
            "CLEAR_OPPORTUNITY",
            "POSSIBLE_OPPORTUNITY",
            "NEEDS_MORE_EVIDENCE",
            "UPSTREAM_CHANGED",
            "LIKELY_ALREADY_COVERED",
            "NO_CLEAR_CONTRIBUTION",
        })
        self.assertTrue(first["qualification"]["whyNow"])
        self.assertIn("ticket_fields", first["sourceCoverage"])
        self.assertIn("confidence", first["ranking"]["dimensions"])
        self.assertIn("familyCandidates", first)
        self.assertIn("scoreVector", first)
        self.assertIn("sourceFreshness", first)
        self.assertIn("resourceFreshness", first)
        self.assertEqual(first["freshness"], first["resourceFreshness"])
        self.assertEqual(first["sourceFreshness"]["state"], "fresh")
        self.assertIn("jamesAffinity", first["scoreVector"]["dimensions"])
        self.assertEqual(first["scoreVector"]["dimensions"]["jamesAffinity"]["value"], "unknown")

    def test_v2_separates_source_freshness_from_resource_freshness(self):
        snapshot = json.loads((ROOT / "data" / "certified" / "current" / "snapshot.json").read_text())
        collection = json.loads((ROOT / "data" / "certified" / "current" / "collection.json").read_text())
        contributions = json.loads((ROOT / "docs" / "radar" / "api" / "v1" / "contributions.json").read_text())
        fixture = {
            "schema": "opportunity-set.v1",
            "version": 1,
            "opportunities": [
                {
                    "opportunityKey": "core-trac:70000",
                    "opportunityRevision": "opportunity-revision-v1-fixture",
                    "ticket": {
                        "id": "70000",
                        "url": "https://core.trac.wordpress.org/ticket/70000",
                        "summary": "Old unchanged ticket",
                        "status": "new",
                        "component": "General",
                        "milestone": "Awaiting Review",
                        "keywords": ["has-patch", "needs-testing"],
                        "owner": None,
                        "resolution": None,
                        "modified": "01/12/2021 02:33:28 AM",
                    },
                    "qualification": {
                        "recommendedContributionClass": "VERIFY_EXISTING_PATCH",
                        "confidence": "high",
                        "reason": "A public patch exists.",
                        "eligibility": {"blockers": [], "state": "requires-upstream-validation"},
                        "evidenceFreshness": {"state": "fresh", "modifiedAt": "01/12/2021 02:33:28 AM", "ageDays": 0},
                        "source_coverage": {
                            "trac_keywords_status_component": True,
                            "trac_ticket": True,
                            "public_patch_or_attachment": True,
                            "wordpress_develop_pr": False,
                            "public_pr_discussion_or_review": False,
                            "changed_files_or_diff": False,
                            "public_test_or_ci_evidence": False,
                            "related_or_referenced_ticket": False,
                        },
                        "duplication_risk": {"level": "low", "reasons": []},
                        "engineering_weight": "medium",
                    },
                    "ranking": {"score": 100, "tier": "strong", "reasons": ["fixture"]},
                }
            ],
        }
        payloads = project_v2(snapshot=snapshot, collection=collection, opportunities=fixture, contributions=contributions)
        opportunity = json.loads(payloads["opportunities.json"])["opportunities"][0]
        candidate = json.loads(payloads["candidate-feed.json"])["candidates"][0]

        self.assertEqual(opportunity["sourceFreshness"]["state"], "fresh")
        self.assertEqual(opportunity["resourceFreshness"]["state"], "stale")
        self.assertGreater(opportunity["resourceFreshness"]["ageDays"], 1000)
        self.assertEqual(candidate["sourceFreshness"]["state"], "fresh")
        self.assertEqual(candidate["resourceFreshness"]["state"], "stale")
        self.assertEqual(candidate["freshness"]["state"], "stale")

    def test_contribution_return_coverage_suppresses_known_public_contributions(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        snapshot = json.loads((ROOT / "data" / "certified" / "current" / "snapshot.json").read_text())
        collection = json.loads((ROOT / "data" / "certified" / "current" / "collection.json").read_text())
        opportunities = json.loads((ROOT / "data" / "certified" / "current" / "opportunities.json").read_text())
        contributions = json.loads((ROOT / "docs" / "radar" / "api" / "v1" / "contributions.json").read_text())
        payloads = project_v2(
            snapshot=snapshot,
            collection=collection,
            opportunities=opportunities,
            contributions=contributions,
            wordpress_develop=source,
            gutenberg=gutenberg,
            contribution_returns=self.contribution_return_projection(),
        )
        by_ticket = {
            item["legacyV1"]["ticketId"]: item
            for item in json.loads(payloads["opportunities.json"])["opportunities"]
            if item.get("legacyV1") and item["legacyV1"]["ticketId"] in {"54034", "40339"}
        }

        self.assertEqual(set(by_ticket), {"54034", "40339"})
        for ticket_id, opportunity in by_ticket.items():
            with self.subTest(ticket_id=ticket_id):
                self.assertEqual(opportunity["qualification"]["state"], "LIKELY_ALREADY_COVERED")
                self.assertEqual(opportunity["ranking"]["tier"], "suppressed")
                self.assertEqual(opportunity["ranking"]["score"], 0)
                self.assertEqual(opportunity["qualification"]["dispositionReview"]["state"], "REVIEW_DISPOSITION")
                self.assertEqual(opportunity["qualification"]["dispositionReview"]["suggestedDisposition"], "NO_ACTION")
                self.assertTrue(opportunity["qualification"]["dispositionReview"]["requiresLiveReread"])

    def test_v2_resources_and_relationships_are_public_graph_artifacts(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        payloads = self.payloads(source, gutenberg)
        resources = json.loads(payloads["resources.json"])
        relationships = json.loads(payloads["relationships.json"])
        self.assertEqual(resources["schema"], "radar-resource-set.v2")
        self.assertEqual(resources["resourceCount"], len(resources["resources"]))
        self.assertTrue(any(item["sourceFamily"] == "CORE_TRAC" for item in resources["resources"]))
        self.assertTrue(all(item["materialRevision"].startswith("resource-revision-v2-") for item in resources["resources"]))
        self.assertEqual(relationships["schema"], "radar-relationship-set.v2")
        self.assertEqual(relationships["relationshipCount"], len(relationships["relationships"]))
        self.assertIn("REFERENCES", relationships["relationshipTypes"])

    def test_source_native_opportunities_do_not_require_core_trac_root(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        opportunities = json.loads(self.payloads(source, gutenberg)["opportunities.json"])["opportunities"]
        native = [item for item in opportunities if item["canonicalResource"]["sourceFamily"] in {"WORDPRESS_DEVELOP_GITHUB", "GUTENBERG"}]
        self.assertTrue(native)
        self.assertTrue(any(item["canonicalResource"]["sourceFamily"] == "GUTENBERG" for item in native))
        self.assertTrue(all(item["legacyV1"] is None for item in native))
        self.assertTrue(all(item["requiresLiveRevalidation"] for item in native))
        self.assertTrue(all(item["identity"]["canonicalResourceId"].startswith(("wordpress-develop-github:", "gutenberg:")) for item in native))

    def test_candidate_feed_is_public_source_neutral_and_not_final_qualification(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        payloads = self.payloads(source, gutenberg)
        candidates = json.loads(payloads["candidates.json"])
        registry = json.loads(payloads["contribution-families.json"])
        scoring = json.loads(payloads["scoring.json"])
        self.assertEqual(candidates["schema"], "radar-candidate-feed.v1")
        self.assertEqual(candidates["candidateCount"], len(candidates["candidates"]))
        self.assertTrue(candidates["candidateBoundary"]["publicCandidateOnly"])
        self.assertTrue(candidates["candidateBoundary"]["notFinalQualification"])
        self.assertTrue(candidates["candidateBoundary"]["notExecutableWork"])
        first = candidates["candidates"][0]
        self.assertTrue(first["id"].startswith("candidate:v1:"))
        self.assertEqual(first["candidateId"], first["id"])
        self.assertEqual(first["opportunityId"], first["opportunityRef"]["id"])
        self.assertIn("resourceRefs", first)
        self.assertIn("familyCandidates", first)
        self.assertIn("sourceFamilies", first)
        self.assertIn("sourceMemberships", first)
        self.assertIn("observedAt", first)
        self.assertIn("whyNow", first)
        self.assertIn("derivedPriority", first)
        self.assertIn("estimatedExecutionClass", first)
        self.assertIn("scoreVector", first)
        self.assertEqual(set(first["scoreVector"]["dimensions"]), {
            "upstreamDemandStrength",
            "expectedUpstreamImpact",
            "jamesAffinity",
            "noveltyConfidence",
            "evidenceFeasibility",
            "timeliness",
            "estimatedExecutionCost",
            "deliveryReputationalRisk",
        })
        self.assertEqual(registry["schema"], "radar-contribution-family-registry.v1")
        self.assertIn("CORE_CODE_REVIEW", {item["id"] for item in registry["families"]})
        self.assertIn("GUTENBERG_TEST", {item["id"] for item in registry["families"]})
        self.assertEqual(scoring["schema"], "radar-candidate-scoring-contract.v1")

    def test_bare_github_numbers_do_not_create_core_trac_edges(self):
        source = {
            "resources": [
                {"number": 1, "ticketReferences": ["60000"], "title": "Canonical link", "url": "https://github.com/WordPress/wordpress-develop/pull/1"},
                {"number": 2, "ticketReferences": [], "ambiguousTicketReferences": ["60001"], "title": "Fix #60001", "url": "https://github.com/WordPress/wordpress-develop/pull/2"},
            ]
        }
        index = github_ticket_index(source)
        self.assertIn("60000", index)
        self.assertNotIn("60001", index)

    def test_core_trac_source_family_includes_raw_acquisition_receipts(self):
        source = load_wordpress_develop_source()
        gutenberg = load_gutenberg_source()
        sources = json.loads(self.payloads(source, gutenberg)["sources.json"])
        core = next(item for item in sources["sourceFamilies"] if item["sourceFamily"] == "CORE_TRAC")
        self.assertEqual(core["sourceRegistry"]["primarySourceCount"], 17)
        self.assertEqual(core["sourceRegistry"]["legacyV1CompatibilitySourceCount"], 5)
        self.assertTrue(core["rawAcquisitions"])
        first = core["rawAcquisitions"][0]
        self.assertTrue(first["sourceUrl"].startswith("https://core.trac.wordpress.org/query?"))
        self.assertRegex(first["rawSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(first["acquisitionId"], r"^trac-csv-acquisition-v1-[0-9a-f]{24}$")
        self.assertTrue(first["sourceReceipt"].endswith(".source-receipt.json"))

    def test_wave2_source_projects_candidates_relationships_and_independent_health(self):
        source = {
            "sourceFamily": "CONTRIBUTOR_PATHWAYS",
            "snapshotId": "source-family-contributor-pathways-fixture",
            "sourceRevision": "fixture-revision",
            "observedTime": "2026-10-06T12:00:00Z",
            "certifiedTime": "2026-10-06T12:00:00Z",
            "completeness": "COMPLETE",
            "freshness": "fresh",
            "recordCount": 2,
            "candidateSignalCount": 1,
            "canonicalHash": "a" * 64,
            "authoritativeSource": "https://make.wordpress.org/handbook/pathways/",
            "machineReadableAccess": ["https://make.wordpress.org/wp-json/wp/v2/handbook/5832"],
            "rawAcquisitions": [],
            "retrievalReceipt": {"receiptId": "fixture", "canonicalHash": "b" * 64},
            "outcomeObservers": ["handbook revision"],
            "scope": "fixture subtree",
            "limitations": ["Fixture scope."],
            "health": {"state": "certified", "failure": None},
            "resources": [
                {
                    "resourceType": "WORDPRESS_HANDBOOK_PAGE",
                    "nativeIdentity": "wordpress_handbook_page/1",
                    "nativeId": 1,
                    "url": "https://make.wordpress.org/handbook/pathways/review/",
                    "title": "Review a Pathway Guide",
                    "state": "published",
                    "createdAt": "2026-01-01T00:00:00",
                    "updatedAt": "2026-10-01T00:00:00",
                    "sourceRevision": "2026-10-01T00:00:00",
                    "bodyHash": "c" * 64,
                    "bodyExcerpt": "Review a pathway guide.",
                    "labels": [],
                    "outboundLinks": ["https://make.wordpress.org/handbook/pathways/target"],
                    "candidateSignals": [{
                        "familyId": "PATHWAY_REVIEW",
                        "state": "CLEAR_OPPORTUNITY",
                        "confidence": "high",
                        "reason": "The guide explicitly asks contributors to review a pathway guide.",
                        "evidence": ["Review a Pathway Guide"],
                    }],
                },
                {
                    "resourceType": "WORDPRESS_HANDBOOK_PAGE",
                    "nativeIdentity": "wordpress_handbook_page/2",
                    "nativeId": 2,
                    "url": "https://make.wordpress.org/handbook/pathways/target/",
                    "title": "Target Guide",
                    "state": "published",
                    "createdAt": "2026-01-01T00:00:00",
                    "updatedAt": "2026-10-01T00:00:00",
                    "sourceRevision": "2026-10-01T00:00:00",
                    "bodyHash": "d" * 64,
                    "bodyExcerpt": "Target.",
                    "labels": [],
                    "outboundLinks": [],
                    "candidateSignals": [],
                },
            ],
        }
        payloads = self.payloads(wave2_sources={"CONTRIBUTOR_PATHWAYS": source})
        sources = json.loads(payloads["sources.json"])["sourceFamilies"]
        pathways = next(item for item in sources if item["sourceFamily"] == "CONTRIBUTOR_PATHWAYS")
        self.assertEqual(pathways["health"]["state"], "certified")
        self.assertEqual(pathways["candidateSignalCount"], 1)
        candidates = json.loads(payloads["candidates.json"])["candidates"]
        pathway_candidates = [
            item for item in candidates
            if item["sourceHealth"]["sourceFamily"] == "CONTRIBUTOR_PATHWAYS"
        ]
        self.assertEqual(len(pathway_candidates), 1)
        self.assertEqual(pathway_candidates[0]["familyCandidates"][0]["familyId"], "PATHWAY_REVIEW")
        relationships = json.loads(payloads["relationships.json"])["relationships"]
        self.assertTrue(any(
            item["sourceResourceId"].startswith("contributor-pathways:")
            and item["targetResourceId"].startswith("contributor-pathways:")
            for item in relationships
        ))


if __name__ == "__main__":
    unittest.main()
