from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process import SCHEMA, SOURCE_INDEX_MAX_BYTES, SOURCE_INDEX_MAX_CANDIDATES, build_feed, build_source_index, digest, load_scoring, validate_observability_categories


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
        self.assertEqual(failed["acquisitionResult"], "failed")
        self.assertEqual(failed["coverage"], "PARTIAL")
        self.assertEqual(failed["counts"]["excludedByReason"]["acquisition_failed"], 1)

    def test_source_counts_distinguish_healthy_zero_from_partial_coverage(self):
        feed = build_feed({"observations": [{"sourceId": "empty-source", "sourceFamily": "TEST", "sourceCompleteness": "PARTIAL", "acquisitionResult": "success", "rows": [], "acquisitionCounts": {"fetchedRows": 0, "deduplicatedResources": 0}}]})
        source = next(item for item in feed["sourceHealth"] if item["sourceId"] == "empty-source")
        self.assertEqual((source["state"], source["acquisitionResult"], source["coverage"]), ("healthy", "success", "PARTIAL"))
        self.assertEqual(source["counts"], {"fetchedRows": 0, "deduplicatedResources": 0, "emittedFamilySignals": 0, "observationalCategories": 0, "excludedByReason": {reason: 0 for reason in source["counts"]["excludedByReason"]}})

    def test_dataform_crosspost_observations_keep_distinct_work_identity(self):
        def observation(source_id, family, post_id, mapped_family):
            return {"sourceId": source_id, "sourceFamily": family, "sourceRole": "DIRECT_OPPORTUNITY", "semanticMeaning": "Explicit public testing observation.", "acquisitionResult": "success", "rows": [{"id": f"wordpress_make_post/{post_id}", "title": "Call for testing: DataForm editor inspector", "url": f"https://make.wordpress.org/{'test' if family == 'MAKE_TEST_RELEASE_SIGNALS' else 'accessibility'}/dataform/", "status": "published", "candidateFamilyMappings": [{"familyId": mapped_family, "confidence": "medium"}]}]}
        feed = build_feed({"observations": [
            observation("MAKE_TEST_RELEASE_SIGNALS", "MAKE_TEST_RELEASE_SIGNALS", 12659, "GUTENBERG_TEST"),
            observation("ACCESSIBILITY_REQUESTS", "ACCESSIBILITY_REQUESTS", 17724, "ACCESSIBILITY_TEST"),
        ]})
        self.assertEqual(feed["candidateCount"], 2)
        self.assertEqual({item["resource"]["id"] for item in feed["candidates"]}, {
            "make-test-release-signals:wordpress_make_post/12659",
            "accessibility-requests:wordpress_make_post/17724",
        })
        self.assertTrue(all(not item["relationships"] for item in feed["candidates"]))
        self.assertTrue(all(not item.get("assignees") for item in feed["candidates"]))

    def test_added_configured_category_requires_explicit_observability_policy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            path.write_text(json.dumps({"sources": [{"sourceFamily": "NEW_PUBLIC_CATEGORY"}]}))
            with self.assertRaisesRegex(ValueError, "count/exclusion handling: NEW_PUBLIC_CATEGORY"):
                validate_observability_categories(path)

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
        feed = build_feed(payload)
        self.assertEqual(feed["candidateCount"], 0)
        source = next(item for item in feed["sourceHealth"] if item["sourceId"] == "generic-source")
        exclusions = source["counts"]["excludedByReason"]
        self.assertEqual(exclusions["non_actionable_status"], 1)
        self.assertLessEqual(len(exclusions), 8)

    def test_semantic_validation_is_processor_owned(self):
        row = {"id": "bad", "summary": "Missing required keyword", "status": "new", "component": "Editor", "owner": "", "type": "defect", "priority": "normal", "milestone": "6.9", "version": "trunk", "keywords": "has-patch", "time": "2026-10-01T00:00:00Z", "changetime": "2026-10-06T00:00:00Z", "comments": "1", "_comments": "1"}
        payload = {"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": "core-trac-report-15-has-patch-needs-testing", "acquisitionResult": "success", "semanticValidation": {"state": "passed", "findings": []}, "rows": [row]}]}
        self.assertEqual(build_feed(payload)["candidateCount"], 0)

    def test_report_membership_is_usable_without_workflow_as_keywords(self):
        for source_id in ("core-trac-report-15-has-patch-needs-testing", "core-trac-report-16-needs-patch"):
            payload = {"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": source_id, "acquisitionResult": "success", "rows": [{"id": source_id, "summary": "Report member", "status": "new", "workflow": "has-patch"}]}]}
            self.assertEqual(build_feed(payload)["candidateCount"], 1)

    def test_literal_keywords_are_validated_for_report_69_and_custom_query(self):
        for source_id in ("core-trac-report-69-bugs-needing-reproduction", "core-trac-query-needs-testing-no-patch"):
            missing = {"id": source_id, "summary": "No matching keyword", "status": "new", "keywords": "unrelated"}
            self.assertEqual(build_feed({"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": source_id, "acquisitionResult": "success", "rows": [missing]}]})["candidateCount"], 0)

    def test_literal_forbidden_keyword_and_closed_status_still_fail(self):
        forbidden = {"id": "forbidden", "summary": "Patch", "status": "new", "keywords": "has-patch"}
        self.assertEqual(build_feed({"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": "core-trac-report-16-needs-patch", "acquisitionResult": "success", "rows": [forbidden]}]})["candidateCount"], 0)
        closed = {"id": "closed", "summary": "Closed", "status": "closed", "workflow": "has-patch"}
        self.assertEqual(build_feed({"observations": [{"observedAt": "2026-10-07T11:00:00Z", "sourceId": "core-trac-report-15-has-patch-needs-testing", "acquisitionResult": "success", "rows": [closed]}]})["candidateCount"], 0)

    def test_feed_has_only_stable_fabric_contract_and_no_v1_fields(self):
        feed = build_feed(self.payload)
        self.assertEqual(feed["schema"], SCHEMA)
        self.assertEqual(feed["candidateCount"], len(feed["candidates"]))
        self.assertNotIn("v1", json.dumps(feed).lower())
        required = {"candidateId", "opportunityId", "resourceRefs", "relationships", "sourceRevision", "observedAt", "sourceMemberships", "familyCandidates", "freshness", "whyNow", "derivedPriority", "sourceHealth"}
        self.assertTrue(required.issubset(feed["candidates"][0]))

    def test_source_index_is_revisions_bound_and_contains_only_the_selected_source(self):
        feed = build_feed(self.payload)
        encoded = build_source_index(feed, "core-trac-report-15-has-patch-needs-testing")
        index = json.loads(encoded)
        self.assertEqual(index["schema"], SCHEMA)
        self.assertEqual(index["sourceIndex"], {"schema": "radar-source-candidate-index.v1", "sourceId": "core-trac-report-15-has-patch-needs-testing"})
        self.assertEqual(index["candidateCount"], len(index["candidates"]))
        self.assertEqual(index["feedRevision"], "candidate-feed-revision-v2-" + digest({key: value for key, value in index.items() if key != "feedRevision"}))
        self.assertTrue(all(any(item["sourceId"] == "core-trac-report-15-has-patch-needs-testing" for item in candidate["sourceMemberships"]) for candidate in index["candidates"]))
        self.assertLessEqual(len(encoded), SOURCE_INDEX_MAX_BYTES)

    def test_source_index_fails_closed_on_record_and_byte_overflow(self):
        feed = build_feed(self.payload)
        candidate = feed["candidates"][0]
        membership = candidate["sourceMemberships"][0]
        source_id = membership["sourceId"]
        many = dict(feed)
        many["candidates"] = [dict(candidate, id=f"copy-{index}", sourceMemberships=[membership]) for index in range(SOURCE_INDEX_MAX_CANDIDATES + 1)]
        many["candidateCount"] = len(many["candidates"])
        with self.assertRaisesRegex(ValueError, "record limit"):
            build_source_index(many, source_id)
        huge_candidate = dict(candidate, sourceMemberships=[dict(membership, evidence={"id": "x", "summary": "x" * SOURCE_INDEX_MAX_BYTES})])
        huge = dict(feed, candidates=[huge_candidate], candidateCount=1)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            build_source_index(huge, source_id)


if __name__ == "__main__":
    unittest.main()
