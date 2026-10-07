from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process import SCHEMA, build_feed, load_scoring


FIXTURE = ROOT / "tests" / "fixtures" / "raw" / "v2" / "observations.json"


class ProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(FIXTURE.read_text())

    def test_overlapping_trac_sources_produce_one_resource_and_candidate(self):
        feed = build_feed(self.payload)
        trac = [item for item in feed["candidates"] if item["resource"]["id"] == "core-trac:123"]
        self.assertEqual(len(trac), 1)
        self.assertEqual({item["sourceId"] for item in trac[0]["sourceMemberships"]}, {
            "core-trac-report-13-has-patch", "core-trac-report-15-has-patch-needs-testing"
        })

    def test_memberships_preserve_role_meaning_and_row_signal(self):
        candidate = next(item for item in build_feed(self.payload)["candidates"] if item["resource"]["id"] == "core-trac:123")
        membership = next(item for item in candidate["sourceMemberships"] if item["sourceId"].endswith("15-has-patch-needs-testing"))
        self.assertEqual(membership["sourceRole"], "DIRECT_OPPORTUNITY")
        self.assertIn("patch", membership["semanticMeaning"])
        self.assertEqual(membership["evidence"]["id"], "123")

    def test_direct_non_trac_mapping_is_a_candidate(self):
        candidate = next(item for item in build_feed(self.payload)["candidates"] if item["resource"]["id"] == "accessibility-requests:a-1")
        self.assertEqual(candidate["familyCandidates"][0]["familyId"], "ACCESSIBILITY_TEST")

    def test_failed_source_does_not_suppress_healthy_source_and_retains_stale_evidence(self):
        feed = build_feed(self.payload)
        self.assertTrue(any(item["resource"]["id"] == "core-trac:123" for item in feed["candidates"]))
        stale = next(item for item in feed["candidates"] if item["resource"]["id"] == "core-trac:456")
        self.assertEqual(stale["freshness"]["state"], "stale")
        self.assertEqual(stale["sourceMemberships"][0]["freshness"], "stale")
        failed = next(item for item in feed["sourceHealth"] if item["sourceId"] == "core-trac-report-16-needs-patch")
        self.assertEqual(failed["state"], "degraded")
        self.assertEqual(failed["freshness"], "stale")

    def test_score_and_order_are_deterministic(self):
        first = build_feed(self.payload)
        second = build_feed(json.loads(json.dumps(self.payload)))
        self.assertEqual(first, second)
        scores = [item["derivedPriority"]["score"] for item in first["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_v2_scoring_config_is_loaded(self):
        scoring = load_scoring()
        self.assertEqual(scoring["version"], "radar-scoring-v2")
        self.assertEqual(scoring["base"], 50)
        self.assertIn("direct_opportunity", scoring["bonuses"])

    def test_report_overlap_bonus_is_capped(self):
        def observation(source_id):
            return {"observedAt": "2026-10-07T11:00:00Z", "sourceId": source_id, "sourceFamily": "TEST_SOURCE", "sourceRole": "DIRECT_OPPORTUNITY", "semanticMeaning": "Fixture signal.", "candidateFamilyMappings": [{"familyId": "TEST_FAMILY", "confidence": "high"}], "acquisitionResult": "success", "rows": [{"id": "same", "title": "Same opportunity", "status": "open"}]}
        one = build_feed({"referenceTime": "2026-10-07T12:00:00Z", "observations": [observation("one")]})
        many = build_feed({"referenceTime": "2026-10-07T12:00:00Z", "observations": [observation(str(index)) for index in range(8)]})
        self.assertEqual(one["candidates"][0]["score"]["value"], 83)
        self.assertEqual(many["candidates"][0]["score"]["value"], 86)

    def test_closed_resources_are_excluded(self):
        payload = {"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": "generic-source", "sourceFamily": "GENERIC", "sourceRole": "DIRECT_OPPORTUNITY", "candidateFamilyMappings": [{"familyId": "GENERIC_REVIEW", "confidence": "high"}], "acquisitionResult": "success", "rows": [{"id": "closed-1", "title": "Already closed", "status": "closed"}]}]}
        self.assertEqual(build_feed(payload)["candidateCount"], 0)

    def test_semantic_validation_is_processor_owned(self):
        row = {"id": "bad", "summary": "Missing required keyword", "status": "new", "component": "Editor", "owner": "", "type": "defect", "priority": "normal", "milestone": "6.9", "version": "trunk", "keywords": "has-patch", "time": "2026-10-01T00:00:00Z", "changetime": "2026-10-06T00:00:00Z", "comments": "1", "_comments": "1"}
        payload = {"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": "core-trac-report-15-has-patch-needs-testing", "acquisitionResult": "success", "semanticValidation": {"state": "passed", "findings": []}, "rows": [row]}]}
        self.assertEqual(build_feed(payload)["candidateCount"], 0)

    def test_feed_has_only_stable_fabric_contract_and_no_v1_fields(self):
        feed = build_feed(self.payload)
        self.assertEqual(feed["schema"], SCHEMA)
        self.assertEqual(feed["candidateCount"], len(feed["candidates"]))
        self.assertNotIn("v1", json.dumps(feed).lower())
        required = {"candidateId", "opportunityId", "resourceRefs", "relationships", "sourceRevision", "observedAt", "sourceMemberships", "familyCandidates", "freshness", "whyNow", "derivedPriority", "sourceHealth"}
        self.assertTrue(required.issubset(feed["candidates"][0]))


if __name__ == "__main__":
    unittest.main()
