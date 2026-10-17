from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from acquire import acquire_core_trac, acquire_meta_trac, acquire_run, load_meta_trac_sources, validate_csv
from process import build_feed


# Controlled test-only protocol samples. These are deliberately not presented
# as observed Meta Trac tickets; the upstream CSV endpoint returned a 403
# browser-verification challenge during this task.
CSV_HEADER = "ticket,summary,status,keywords,time,changetime,description\n"
TEST_ROW = "900001,Test accessibility ticket,new,accessibility,2024-01-02T03:04:05Z,2024-01-03T03:04:05Z,Test-only description\n"
TEST_CSV = (CSV_HEADER + TEST_ROW).encode()
TEST_URL = "https://meta.trac.wordpress.org/query?format=csv&status=!closed"


def source_definition(source_id: str = "meta-trac-accessibility-open-union") -> dict:
    registry = json.loads((ROOT / "config/meta-trac-v2-source-registry.json").read_text())
    return next(item for item in registry["sources"] if item["id"] == source_id)


def test_csv_acquirer(body_for_url):
    """Use the production CSV parser with deterministic, local response bytes."""
    def acquire(source, run_dir, observed_at, downloads, timeout):
        body = body_for_url(source["csvUrl"])
        downloads.mkdir(parents=True, exist_ok=True)
        path = downloads / "query.csv"
        path.write_bytes(body)
        return acquire_core_trac(
            source, run_dir, observed_at, downloads, timeout,
            opener=lambda _url: None,
            waiter=lambda *_: path,
            closer=lambda *_: None,
        )
    return acquire


class MetaTracTests(unittest.TestCase):
    def test_default_acquisition_never_requests_meta(self):
        observed = []
        def meta_acquirer(source, _run_dir, observed_at, _downloads, _timeout):
            observed.append((source["id"], observed_at))
            return {"schema": "radar-observation.v2", "version": 2, "sourceId": source["id"], "sourceFamily": "META_TRAC", "sourceRole": source["sourceRole"], "semanticMeaning": source["semanticMeaning"], "candidateFamilyMappings": source["candidateFamilyMappings"], "identityField": source["identityField"], "resourceType": source["resourceType"], "observedAt": observed_at, "acquisitionResult": "failed", "rows": [], "rawArtifacts": [], "error": "fixture only"}
        with tempfile.TemporaryDirectory() as temporary, patch("acquire.primary_core_trac_sources", return_value=[]):
            manifest = acquire_run(raw_root=Path(temporary), observed_at="2026-10-12T12:00:00Z", wave2_sources=[], meta_sources=None, meta_acquirer=meta_acquirer)
        self.assertEqual(observed, [])
        self.assertEqual(manifest["observations"], [])

    def test_meta_registry_can_be_loaded_for_explicit_opt_in(self):
        self.assertEqual([source["id"] for source in load_meta_trac_sources()], [
            "meta-trac-report-10-good-first-bugs", "meta-trac-accessibility-open-union",
        ])

    def test_full_csv_exports_with_page_parameters_deduplicate_and_keep_selector_membership(self):
        source = source_definition()
        source["selectors"] = [{"id": "description_accessibility", "csvUrls": [TEST_URL + "&page=1", TEST_URL + "&page=2"]}, {"id": "keyword_accessibility", "csvUrls": [TEST_URL + "&keywords=accessibility"]}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = acquire_meta_trac(source, root / "run", "2026-10-12T12:00:00Z", root / "downloads", 1, csv_acquirer=test_csv_acquirer(lambda _url: TEST_CSV))
        self.assertEqual(observation["acquisitionResult"], "success")
        self.assertEqual(len(observation["rows"]), 1)
        row = observation["rows"][0]
        self.assertEqual(row["canonicalIdentity"], "meta.trac.wordpress.org/ticket/900001")
        self.assertEqual(row["url"], "https://meta.trac.wordpress.org/ticket/900001")
        self.assertEqual(row["selectorMemberships"], ["description_accessibility", "keyword_accessibility"])
        self.assertEqual({item["url"] for item in observation["rawArtifacts"]}, {TEST_URL + "&page=1", TEST_URL + "&page=2", TEST_URL + "&keywords=accessibility"})

    def test_description_selector_requires_description_but_keyword_exports_do_not(self):
        source = source_definition()
        description_csv = (CSV_HEADER + "900010,Test description match,new,,2024-01-02T03:04:05Z,2024-01-03T03:04:05Z,Accessibility support test\n").encode()
        keyword_csv = ("ticket,summary,status,keywords,time,changetime\n"
                       "900011,Test keyword match,new,accessibility,2024-01-02T03:04:05Z,2024-01-03T03:04:05Z\n").encode()
        a11y_csv = ("ticket,summary,status,keywords,time,changetime\n"
                    "900012,Test a11y match,new,a11y,2024-01-02T03:04:05Z,2024-01-03T03:04:05Z\n").encode()
        def body_for_url(url):
            if "description=~accessibility" in url:
                return description_csv
            if "keywords=~accessibility" in url:
                return keyword_csv
            return a11y_csv
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = acquire_meta_trac(source, root / "run", "2026-10-12T12:00:00Z", root / "downloads", 1, csv_acquirer=test_csv_acquirer(body_for_url))
        self.assertEqual(observation["acquisitionResult"], "success")
        rows = {row["id"]: row for row in observation["rows"]}
        self.assertIn("description", rows["900010"])
        self.assertNotIn("description", rows["900011"])
        feed = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [observation]})
        self.assertEqual(feed["candidateCount"], 3)

        source["selectors"] = [source["selectors"][0]]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing_description = ("ticket,summary,status,keywords,time,changetime\n"
                                   "900010,Test description match,new,,2024-01-02T03:04:05Z,2024-01-03T03:04:05Z\n").encode()
            rejected = acquire_meta_trac(source, root / "run", "2026-10-12T12:00:00Z", root / "downloads", 1, csv_acquirer=test_csv_acquirer(lambda _url: missing_description))
        self.assertEqual(rejected["acquisitionResult"], "failed")
        self.assertEqual(rejected["rows"], [])

    def test_partial_union_failure_fails_closed_and_preserves_successful_raw_evidence(self):
        source = source_definition()
        source["selectors"] = [{"id": "description_accessibility", "csvUrls": [TEST_URL]}, {"id": "keyword_a11y", "csvUrls": [TEST_URL + "&keywords=a11y"]}]
        calls = 0
        def acquire(source_item, run_dir, observed_at, downloads, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return test_csv_acquirer(lambda _url: TEST_CSV)(source_item, run_dir, observed_at, downloads, timeout)
            return {"acquisitionResult": "failed", "rows": [], "rawArtifacts": [], "error": "test selector failure"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = acquire_meta_trac(source, root / "run", "2026-10-12T12:00:00Z", root / "downloads", 1, csv_acquirer=acquire)
        self.assertEqual(observation["acquisitionResult"], "failed")
        self.assertEqual(observation["rows"], [])
        self.assertTrue(observation["rawArtifacts"])
        self.assertIn("keyword_a11y", observation["error"])

        prior = dict(observation, acquisitionResult="success", error=None, observedAt="2026-10-11T12:00:00Z", rows=[{
            "id": "900001", "canonicalIdentity": "meta.trac.wordpress.org/ticket/900001", "url": "https://meta.trac.wordpress.org/ticket/900001",
            "summary": "Test accessibility ticket", "status": "new", "keywords": "accessibility", "time": "2024-01-02T03:04:05Z",
            "changetime": "2024-01-03T03:04:05Z", "description": "Test-only description", "selectorMemberships": ["description_accessibility"],
        }])
        feed = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [observation], "previous": {"observations": [prior]}})
        candidate = next(item for item in feed["candidates"] if item["resource"]["resourceType"] == "META_TRAC_TICKET")
        health = next(item for item in feed["sourceHealth"] if item["sourceId"] == source["id"])
        self.assertEqual(candidate["freshness"]["state"], "stale")
        self.assertEqual(candidate["sourceMemberships"][0]["presentInCurrentObservation"], False)
        self.assertEqual(health["state"], "degraded")

    def test_required_semantic_columns_and_values_are_rejected_when_missing(self):
        source = source_definition()
        required_headers = source["requiredCsvHeaders"]
        required_values = source["requiredCsvFields"]
        with self.assertRaisesRegex(ValueError, "keywords"):
            validate_csv(b"ticket,summary,status,time,changetime,description\n1,Test,new,2024-01-01T00:00:00Z,2024-01-02T00:00:00Z,Test\n", source["expectedFields"], required_values, required_headers)
        with self.assertRaisesRegex(ValueError, "changetime"):
            validate_csv((CSV_HEADER + "900001,Test,new,accessibility,2024-01-02T03:04:05Z,,Test\n").encode(), source["expectedFields"], required_values, required_headers)
        with self.assertRaisesRegex(ValueError, "invalid timestamps"):
            validate_csv((CSV_HEADER + "900001,Test,new,accessibility,not-a-time,2024-01-02T03:04:05Z,Test\n").encode(), source["expectedFields"], required_values, required_headers)

        observation = {
            "sourceId": source["id"], "sourceFamily": "META_TRAC", "sourceRole": "SIGNAL", "semanticMeaning": source["semanticMeaning"],
            "candidateFamilyMappings": source["candidateFamilyMappings"], "identityField": "canonicalIdentity", "resourceType": "META_TRAC_TICKET",
            "requiredSemanticColumns": source["requiredSemanticColumns"], "requiredRowFields": source["requiredRowFields"],
            "selectorKeywordRequirements": source["selectorKeywordRequirements"], "semanticValidation": source["semanticValidation"],
            "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success",
            "rows": [{"id": "900001", "canonicalIdentity": "meta.trac.wordpress.org/ticket/900001", "url": "https://meta.trac.wordpress.org/ticket/900001",
                "summary": "Test accessibility ticket", "status": "new", "time": "2024-01-02T03:04:05Z", "changetime": "2024-01-03T03:04:05Z",
                "description": "Test-only description", "selectorMemberships": ["description_accessibility"]}],
        }
        feed = build_feed({"observations": [observation]})
        self.assertEqual(feed["candidateCount"], 0)
        health = next(item for item in feed["sourceHealth"] if item["sourceId"] == source["id"])
        self.assertEqual(health["semanticValidation"]["state"], "failed")

    def test_recent_fetch_time_is_not_replaced_by_old_modified_time(self):
        source = source_definition()
        observation = {
            "sourceId": source["id"], "sourceFamily": "META_TRAC", "sourceRole": "SIGNAL", "semanticMeaning": source["semanticMeaning"],
            "candidateFamilyMappings": source["candidateFamilyMappings"], "identityField": "canonicalIdentity", "resourceType": "META_TRAC_TICKET",
            "expectedFields": source["expectedFields"], "requiredSemanticColumns": source["requiredSemanticColumns"], "requiredRowFields": source["requiredRowFields"],
            "selectorKeywordRequirements": source["selectorKeywordRequirements"], "selectorRequiredColumns": source["selectorRequiredColumns"],
            "selectorTextRequirements": source["selectorTextRequirements"], "semanticValidation": source["semanticValidation"],
            "freshnessExpectation": source["freshnessExpectation"], "enforceObservationFreshness": source["enforceObservationFreshness"],
            "exactUpstreamUrl": source["authoritativeSource"], "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success",
            "rows": [{"id": "900001", "canonicalIdentity": "meta.trac.wordpress.org/ticket/900001", "url": "https://meta.trac.wordpress.org/ticket/900001",
                "summary": "Test accessibility ticket", "status": "new", "keywords": "accessibility", "time": "2024-01-02T03:04:05Z",
                "changetime": "2024-01-03T03:04:05Z", "description": "Test-only description", "selectorMemberships": ["keyword_accessibility"]}],
        }
        feed = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [observation]})
        candidate = feed["candidates"][0]
        self.assertEqual(candidate["observedAt"], "2026-10-12T12:00:00Z")
        self.assertEqual(candidate["sourceMemberships"][0]["evidence"]["changetime"], "2024-01-03T03:04:05Z")
        self.assertEqual(candidate["freshness"]["state"], "fresh")

        stale = json.loads(json.dumps(observation))
        stale["observedAt"] = "2026-07-01T12:00:00Z"
        stale_feed = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [stale]})
        stale_candidate = stale_feed["candidates"][0]
        stale_health = next(item for item in stale_feed["sourceHealth"] if item["sourceId"] == source["id"])
        self.assertEqual(stale_candidate["freshness"]["state"], "stale")
        self.assertEqual(stale_health["failure"], "SOURCE_OBSERVATION_STALE")

    def test_description_selector_requires_matching_text_but_keyword_selector_can_omit_description(self):
        source = source_definition()
        def observation(row):
            return {
                "sourceId": source["id"], "sourceFamily": "META_TRAC", "sourceRole": "SIGNAL", "semanticMeaning": source["semanticMeaning"],
                "candidateFamilyMappings": source["candidateFamilyMappings"], "identityField": "canonicalIdentity", "resourceType": "META_TRAC_TICKET",
                "requiredSemanticColumns": source["requiredSemanticColumns"], "requiredRowFields": source["requiredRowFields"],
                "selectorKeywordRequirements": source["selectorKeywordRequirements"], "selectorRequiredColumns": source["selectorRequiredColumns"],
                "selectorTextRequirements": source["selectorTextRequirements"], "semanticValidation": source["semanticValidation"],
                "freshnessExpectation": source["freshnessExpectation"], "enforceObservationFreshness": source["enforceObservationFreshness"],
                "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success", "rows": [row],
            }
        base = {"id": "900001", "canonicalIdentity": "meta.trac.wordpress.org/ticket/900001", "url": "https://meta.trac.wordpress.org/ticket/900001",
                "summary": "Test accessibility ticket", "status": "new", "keywords": "accessibility", "time": "2024-01-02T03:04:05Z",
                "changetime": "2024-01-03T03:04:05Z"}
        blank_description = dict(base, description="", selectorMemberships=["description_accessibility"])
        rejected = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [observation(blank_description)]})
        self.assertEqual(rejected["candidateCount"], 0)
        rejected_health = next(item for item in rejected["sourceHealth"] if item["sourceId"] == source["id"])
        self.assertEqual(rejected_health["semanticValidation"]["state"], "failed")

        keyword_only = dict(base, selectorMemberships=["keyword_accessibility"])
        accepted = build_feed({"referenceTime": "2026-10-12T12:00:00Z", "observations": [observation(keyword_only)]})
        self.assertEqual(accepted["candidateCount"], 1)

    def test_multiple_selectors_are_one_membership_and_cannot_add_corroboration_bonus(self):
        source = source_definition()
        observation = {
            "sourceId": source["id"], "sourceFamily": "META_TRAC", "sourceRole": "SIGNAL", "semanticMeaning": source["semanticMeaning"],
            "candidateFamilyMappings": source["candidateFamilyMappings"], "identityField": "canonicalIdentity", "resourceType": "META_TRAC_TICKET",
            "expectedFields": source["expectedFields"], "requiredSemanticColumns": source["requiredSemanticColumns"], "requiredRowFields": source["requiredRowFields"],
            "selectorKeywordRequirements": source["selectorKeywordRequirements"], "semanticValidation": source["semanticValidation"],
            "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success",
            "rows": [{"id": "900001", "canonicalIdentity": "meta.trac.wordpress.org/ticket/900001", "url": "https://meta.trac.wordpress.org/ticket/900001",
                "summary": "Test accessibility ticket", "status": "new", "keywords": "accessibility a11y", "time": "2024-01-02T03:04:05Z",
                "changetime": "2024-01-03T03:04:05Z", "description": "Test-only description",
                "selectorMemberships": ["description_accessibility", "keyword_accessibility", "keyword_a11y"]}],
        }
        feed = build_feed({"observations": [observation]})
        candidate = feed["candidates"][0]
        self.assertEqual(len(candidate["sourceMemberships"]), 1)
        self.assertEqual(candidate["sourceMemberships"][0]["evidence"]["selectorMemberships"], ["description_accessibility", "keyword_accessibility", "keyword_a11y"])
        single_selector = json.loads(json.dumps(observation))
        single_selector["rows"][0]["selectorMemberships"] = ["keyword_accessibility"]
        single_candidate = build_feed({"observations": [single_selector]})["candidates"][0]
        self.assertEqual(candidate["score"]["value"], single_candidate["score"]["value"])

    def test_meta_and_core_ticket_ids_remain_host_scoped(self):
        meta = {
            "sourceId": "meta-trac-report-10-good-first-bugs", "sourceFamily": "META_TRAC", "sourceRole": "SIGNAL",
            "semanticMeaning": "Test-only Meta source", "candidateFamilyMappings": [{"familyId": "WPORG_BUG_GARDENING", "confidence": "low"}],
            "identityField": "canonicalIdentity", "resourceType": "META_TRAC_TICKET", "requiredSemanticColumns": ["keywords"],
            "requiredRowFields": ["id", "summary", "status", "time", "changetime"], "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success",
            "rows": [{"id": "123", "canonicalIdentity": "meta.trac.wordpress.org/ticket/123", "url": "https://meta.trac.wordpress.org/ticket/123", "summary": "Meta test", "status": "new", "keywords": "good-first-bug", "time": "2024-01-02T03:04:05Z", "changetime": "2024-01-03T03:04:05Z"}],
        }
        core = {
            "sourceId": "core-trac-report-44-good-first-bugs", "sourceFamily": "CORE_TRAC", "sourceRole": "SIGNAL",
            "semanticMeaning": "Test-only Core source", "candidateFamilyMappings": [{"familyId": "CORE_BUG_GARDENING", "confidence": "low"}],
            "identityField": "id", "resourceType": "CORE_TRAC_TICKET", "observedAt": "2026-10-12T12:00:00Z", "acquisitionResult": "success",
            "rows": [{"id": "123", "summary": "Core test", "status": "new", "keywords": "good-first-bug"}],
        }
        feed = build_feed({"observations": [meta, core]})
        ids = {item["resource"]["id"] for item in feed["candidates"]}
        self.assertIn("meta-trac:meta.trac.wordpress.org/ticket/123", ids)
        self.assertIn("core-trac:123", ids)


if __name__ == "__main__":
    unittest.main()
