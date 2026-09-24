from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from certification import (
    SCHEMA_FILES,
    CertificationError,
    build_certification_bundle,
    build_collection,
    build_opportunity_record,
    canonical_json,
    certify,
    load_schema,
    validate_named,
    verify_certified,
)
from radarcore import RunContext, file_sha256, select_datasets
from radarlib import Opportunity, TICKET_ID_KEYS, load_queries
from tests.fixture_support import ambiguous_collection_listing

FIXTURES = ROOT / "tests" / "fixtures"
EXPECTED = [query["slug"] for query in load_queries()]
CONTEXT = RunContext(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
REVISION = "0123456789abcdef0123456789abcdef01234567"


def fixture_selection():
    return select_datasets(FIXTURES / "raw", "2026-01-15", EXPECTED, TICKET_ID_KEYS)


class CertificationTests(unittest.TestCase):
    def test_all_schema_documents_have_stable_ids(self):
        for name in SCHEMA_FILES:
            schema = load_schema(name)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn(SCHEMA_FILES[name], schema["$id"])
            self.assertFalse(schema["additionalProperties"])

    def test_collection_constructs_and_validates(self):
        collection = build_collection(fixture_selection(), CONTEXT)
        self.assertEqual(validate_named(collection, "collection.v1"), [])
        self.assertEqual(collection["state"], "complete")

    def test_collection_id_is_deterministic(self):
        first = build_collection(fixture_selection(), CONTEXT)
        second = build_collection(fixture_selection(), CONTEXT)
        self.assertEqual(first["collection_id"], second["collection_id"])

    def test_zero_row_query_is_certifiable_with_warning(self):
        collection = build_collection(fixture_selection(), CONTEXT)
        docs = next(item for item in collection["query_evidence"] if item["query_slug"] == "docs_needs_testing")
        self.assertEqual(docs["row_count"], 0)
        self.assertIn("empty_but_valid", docs["warnings"])

    def test_canonical_json_is_sorted_utf8_with_one_newline(self):
        value = {"z": "café", "a": [2, 1]}
        self.assertEqual(canonical_json(value), b'{"a":[2,1],"z":"caf\xc3\xa9"}\n')

    def test_unknown_private_field_is_rejected(self):
        collection = build_collection(fixture_selection(), CONTEXT)
        collection["eden_eligible"] = True
        self.assertTrue(any("unknown property" in error for error in validate_named(collection, "collection.v1")))

    def test_missing_required_field_is_rejected(self):
        collection = build_collection(fixture_selection(), CONTEXT)
        del collection["state"]
        self.assertTrue(any("missing required" in error for error in validate_named(collection, "collection.v1")))

    def test_wrong_type_is_rejected(self):
        collection = build_collection(fixture_selection(), CONTEXT)
        collection["query_evidence"][0]["row_count"] = "one"
        self.assertTrue(validate_named(collection, "collection.v1"))

    def test_malformed_opportunity_is_rejected(self):
        record = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).opportunities["opportunities"][0]
        record["should_contribute"] = True
        self.assertTrue(any("unknown property" in error for error in validate_named(record, "opportunity.v1")))

    def test_execution_result_unknown_field_is_rejected(self):
        result = copy.deepcopy(build_certification_bundle(fixture_selection(), CONTEXT, REVISION).result)
        result["host"] = "collector-host"
        self.assertTrue(any("unknown property" in error for error in validate_named(result, "execution-result.v1")))

    def test_complete_bundle_validates_all_records(self):
        bundle = build_certification_bundle(fixture_selection(), CONTEXT, REVISION)
        self.assertEqual(validate_named(bundle.snapshot, "snapshot.v1"), [])
        for record in bundle.opportunities["opportunities"]:
            self.assertEqual(validate_named(record, "opportunity.v1"), [])
        self.assertEqual(validate_named(bundle.result, "execution-result.v1"), [])

    def test_snapshot_id_is_deterministic(self):
        first = build_certification_bundle(fixture_selection(), CONTEXT, REVISION)
        second = build_certification_bundle(fixture_selection(), CONTEXT, REVISION)
        self.assertEqual(first.snapshot["snapshot_id"], second.snapshot["snapshot_id"])

    def test_bundle_is_byte_identical(self):
        first = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).files()
        second = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).files()
        self.assertEqual(first, second)

    def test_configuration_hashes_match_exact_files(self):
        snapshot = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).snapshot
        self.assertEqual(snapshot["scoring_config_sha256"], file_sha256(ROOT / "config/scoring.json"))
        self.assertEqual(snapshot["query_config_sha256"], file_sha256(ROOT / "config/queries.json"))

    def test_opportunity_order_is_stable(self):
        records = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).opportunities["opportunities"]
        ranking = [(record["ranking"]["score"], int(record["ticket"]["id"])) for record in records]
        self.assertEqual(ranking, sorted(ranking, key=lambda item: (-item[0], item[1])))

    def test_multi_query_ticket_preserves_all_sources(self):
        records = build_certification_bundle(fixture_selection(), CONTEXT, REVISION).opportunities["opportunities"]
        ticket = next(record for record in records if record["ticket"]["id"] == "101")
        self.assertEqual([source["query_slug"] for source in ticket["discovery"]["sources"]],
                         ["general_needs_testing", "media_has_patch"])

    def test_review_props_and_changeset_are_preserved_without_notes(self):
        selection = fixture_selection()
        opportunity = Opportunity("999", 100, ("track priority: test +100",),
                                  {"summary": "Test"}, {"track": "testing"},
                                  {"status": "tested", "received_props": True,
                                   "props_recorded_at": "2026-01-01", "changeset": "12345",
                                   "notes": "private"})
        query_map = {query["slug"]: query for query in load_queries()}
        record = build_opportunity_record(opportunity, {EXPECTED[0]}, selection,
                                          "collection-v1-" + "a" * 24,
                                          "snapshot-v1-" + "b" * 24,
                                          "radar-scoring-v1", query_map)
        self.assertTrue(record["radar_state"]["received_props"])
        self.assertEqual(record["radar_state"]["changeset"], "12345")
        self.assertNotIn("notes", record["radar_state"])

    def test_missing_query_fails_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            selection = select_datasets(Path(directory), "2026-01-15", ["missing"], TICKET_ID_KEYS)
            with self.assertRaises(CertificationError):
                build_certification_bundle(selection, CONTEXT, REVISION)

    def test_malformed_query_fails_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "manual/2026-01-15"
            base.mkdir(parents=True)
            (base / "bad.csv").write_text("not,a-ticket\nfoo,bar\n")
            selection = select_datasets(Path(directory), "2026-01-15", ["bad"], TICKET_ID_KEYS)
            with self.assertRaises(CertificationError):
                build_certification_bundle(selection, CONTEXT, REVISION)

    def test_ambiguous_query_fails_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ambiguous_collection_listing(root, "2026-01-15", "same"):
                selection = select_datasets(root, "2026-01-15", ["same"], TICKET_ID_KEYS)
                self.assertEqual(len(selection.ambiguous["same"]), 2)
                with self.assertRaises(CertificationError):
                    build_certification_bundle(selection, CONTEXT, REVISION)

    def test_success_publishes_and_offline_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            result = certify(fixture_selection(), CONTEXT, REVISION, current)
            self.assertEqual(result["status"], "success")
            verified = verify_certified(current)
            self.assertEqual(verified["status"], "success")

    def test_failure_leaves_current_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            current.mkdir()
            marker = current / "marker.txt"
            marker.write_text("previous-certified")
            missing = select_datasets(Path(directory) / "raw", "2026-01-15", ["missing"], TICKET_ID_KEYS)
            result = certify(missing, CONTEXT, REVISION, current)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(marker.read_text(), "previous-certified")

    def test_tampered_opportunity_artifact_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            certify(fixture_selection(), CONTEXT, REVISION, current)
            payload = json.loads((current / "opportunities.json").read_text())
            payload["opportunities"][0]["ranking"]["score"] += 1
            (current / "opportunities.json").write_bytes(canonical_json(payload))
            with self.assertRaises(CertificationError):
                verify_certified(current)

    def test_tampered_manifest_fails_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            certify(fixture_selection(), CONTEXT, REVISION, current)
            snapshot = json.loads((current / "snapshot.json").read_text())
            snapshot["opportunity_count"] += 1
            (current / "snapshot.json").write_bytes(canonical_json(snapshot))
            with self.assertRaises(CertificationError):
                verify_certified(current)


if __name__ == "__main__":
    unittest.main()
