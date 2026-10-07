from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process import SCHEMA, build_feed


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

    def test_feed_has_only_stable_fabric_contract_and_no_v1_fields(self):
        feed = build_feed(self.payload)
        self.assertEqual(feed["schema"], SCHEMA)
        self.assertEqual(feed["candidateCount"], len(feed["candidates"]))
        self.assertNotIn("v1", json.dumps(feed).lower())
        required = {"candidateId", "opportunityId", "resourceRefs", "relationships", "sourceRevision", "observedAt", "sourceMemberships", "familyCandidates", "freshness", "whyNow", "derivedPriority", "sourceHealth"}
        self.assertTrue(required.issubset(feed["candidates"][0]))


if __name__ == "__main__":
    unittest.main()
