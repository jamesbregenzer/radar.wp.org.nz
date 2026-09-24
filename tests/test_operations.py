from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from certification import certify, execution_result, validate_named
from operations import (
    certify_operation, collect_operation, generate_operation, pipeline_operation,
    publish_operation, resolve_source_revision, validate_collection_operation,
    verify_operation,
)
from pipeline import CollectionResult
from radarcore import RunContext, select_datasets
from radarlib import TICKET_ID_KEYS, load_queries

FIXTURE_RAW = ROOT / "tests/fixtures/raw"
SLUGS = [query["slug"] for query in load_queries()]
CONTEXT = RunContext(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
REVISION = "a" * 40


def selection(slugs=None):
    return select_datasets(FIXTURE_RAW, "2026-01-15", slugs or SLUGS, TICKET_ID_KEYS)


def result(operation, status="success", code="OK", outputs=None):
    return execution_result(operation, status, CONTEXT, outputs=outputs or [], code=code)


class OperationsTests(unittest.TestCase):
    def test_cli_parses_every_operation(self):
        import radar
        parser = radar.build_parser()
        cases = [
            ["collect", "--reference-time", CONTEXT.generated_iso],
            ["validate-collection", "--reference-time", CONTEXT.generated_iso, "--collection-id", "2026-01-15"],
            ["generate", "--reference-time", CONTEXT.generated_iso, "--collection-id", "2026-01-15"],
            ["certify", "--reference-time", CONTEXT.generated_iso, "--collection-id", "2026-01-15", "--source-revision", REVISION],
            ["verify", "--reference-time", CONTEXT.generated_iso],
            ["publish", "--reference-time", CONTEXT.generated_iso],
            ["pipeline", "--reference-time", CONTEXT.generated_iso, "--collection-id", "2026-01-15", "--source-revision", REVISION],
        ]
        self.assertEqual([parser.parse_args(case).operation for case in cases],
                         ["collect", "validate-collection", "generate", "certify", "verify", "publish", "pipeline"])

    def test_pipeline_cli_rejects_selected_query_subset(self):
        import radar
        with self.assertRaises(SystemExit):
            radar.build_parser().parse_args([
                "pipeline", "--reference-time", CONTEXT.generated_iso,
                "--collection-id", "2026-01-15", "--source-revision", REVISION,
                "--query", SLUGS[0],
            ])

    def test_collect_all_queries_with_mock_collector(self):
        calls = []
        def collector(slug, context):
            calls.append(slug)
            return CollectionResult(slug, 0, selection([slug]))
        value = collect_operation(CONTEXT, collector=collector)
        self.assertEqual(value["status"], "success")
        self.assertEqual(calls, SLUGS)
        self.assertEqual(len(value["stage_results"]), len(SLUGS))
        self.assertTrue(all(stage["status"] == "success" for stage in value["stage_results"]))

    def test_collect_selected_queries(self):
        import radar
        parsed = radar.build_parser().parse_args([
            "collect", "--reference-time", CONTEXT.generated_iso,
            "--query", SLUGS[1],
        ])
        self.assertEqual(parsed.query, [SLUGS[1]])
        calls = []
        collect_operation(CONTEXT, [SLUGS[1]], lambda slug, context: calls.append(slug) or CollectionResult(slug, 0, selection([slug])))
        self.assertEqual(calls, [SLUGS[1]])

    def test_partial_collection_failure(self):
        def collector(slug, context):
            return CollectionResult(slug, 1 if slug == SLUGS[1] else 0, selection([slug]))
        value = collect_operation(CONTEXT, collector=collector)
        self.assertEqual((value["status"], value["code"]), ("failure", "COLLECTION_QUERY_FAILED"))
        self.assertTrue(any(stage["status"] == "failure" for stage in value["stage_results"]))

    def test_complete_validation(self):
        value = validate_collection_operation(CONTEXT, "2026-01-15", FIXTURE_RAW)
        self.assertEqual((value["status"], value["code"]), ("success", "OK"))

    def test_missing_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            value = validate_collection_operation(CONTEXT, "2026-01-15", Path(directory))
        self.assertEqual(value["code"], "COLLECTION_INCOMPLETE")

    def test_malformed_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "manual/2026-01-15"
            base.mkdir(parents=True)
            for slug in SLUGS:
                (base / f"{slug}.csv").write_text("wrong,header\na,b\n")
            value = validate_collection_operation(CONTEXT, "2026-01-15", Path(directory))
        self.assertEqual(value["code"], "COLLECTION_MALFORMED")

    def test_ambiguous_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "manual/2026-01-15"
            base.mkdir(parents=True)
            for slug in SLUGS:
                (base / f"{slug}.csv").write_text("id,summary\n1,A\n")
            (base / f"{SLUGS[0].upper()}.CSV").write_text("id,summary\n1,A\n")
            value = validate_collection_operation(CONTEXT, "2026-01-15", Path(directory))
        self.assertEqual(value["code"], "COLLECTION_AMBIGUOUS")

    def test_deterministic_generate_result(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "result.txt"
            def runner(command):
                artifact.write_text("stable")
                return 0
            first = generate_operation(CONTEXT, "2026-01-15", runner, [artifact], FIXTURE_RAW)
            second = generate_operation(CONTEXT, "2026-01-15", runner, [artifact], FIXTURE_RAW)
            self.assertEqual(first, second)
            self.assertFalse(any(directory in item["path"] for item in first["artifacts"]))

    def test_generation_failure(self):
        value = generate_operation(CONTEXT, "2026-01-15", lambda command: 2, [], FIXTURE_RAW)
        self.assertEqual(value["code"], "GENERATION_FAILED")

    def test_certification_delegation(self):
        with tempfile.TemporaryDirectory() as directory:
            value = certify_operation(CONTEXT, "2026-01-15", REVISION, Path(directory) / "current", FIXTURE_RAW)
            self.assertEqual(value["status"], "success")

    def test_verification_delegation(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            certify(selection(), CONTEXT, REVISION, current)
            self.assertEqual(verify_operation(CONTEXT, current)["status"], "success")

    def test_publication_plan_and_no_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            certified = certify(selection(), CONTEXT, REVISION, current)
            snapshot_id = certified["output_identities"][0]
            eligible = publish_operation(CONTEXT, current)
            unchanged = publish_operation(CONTEXT, current, snapshot_id)
            self.assertEqual(eligible["status"], "success")
            self.assertEqual((unchanged["status"], unchanged["code"]), ("no_data_delta", "NO_DATA_DELTA"))

    def test_publication_ineligible(self):
        with tempfile.TemporaryDirectory() as directory:
            value = publish_operation(CONTEXT, Path(directory))
        self.assertEqual(value["code"], "PUBLICATION_NOT_ELIGIBLE")

    def test_pipeline_success_and_idempotency(self):
        calls = []
        operations = {
            "validate": lambda c, i: calls.append("validate") or result("validate-collection", outputs=["collection"]),
            "generate": lambda c, i: calls.append("generate") or result("generate"),
            "certify": lambda c, i, r: calls.append("certify") or result("certify", outputs=["snapshot"]),
            "verify": lambda c: calls.append("verify") or result("verify", outputs=["snapshot"]),
            "publish": lambda c: calls.append("publish") or result("publish", outputs=["snapshot"]),
        }
        first = pipeline_operation(CONTEXT, "2026-01-15", REVISION, include_collect=False, operations=operations)
        calls.clear()
        second = pipeline_operation(CONTEXT, "2026-01-15", REVISION, include_collect=False, operations=operations)
        self.assertEqual(first, second)
        self.assertEqual(len(first["stage_results"]), 5)

    def test_collecting_pipeline_invokes_every_enabled_query(self):
        collected = []
        stages = []

        def collector(slug, context):
            collected.append(slug)
            return CollectionResult(slug, 0, selection([slug]))

        operations = {
            "collect": lambda context: collect_operation(context, collector=collector),
            "validate": lambda *args: stages.append("validate") or result("validate-collection"),
            "generate": lambda *args: result("generate"),
            "certify": lambda *args: result("certify"),
            "verify": lambda *args: result("verify"),
            "publish": lambda *args: result("publish", outputs=["snapshot"]),
        }
        value = pipeline_operation(CONTEXT, "2026-01-15", REVISION, operations=operations)
        self.assertEqual(value["status"], "success")
        self.assertEqual(collected, SLUGS)
        self.assertEqual(stages, ["validate"])

    def test_stale_same_date_files_cannot_hide_required_query_failure(self):
        calls = []

        def collector(slug, context):
            calls.append(slug)
            # FIXTURE_RAW already contains every same-date file. One failed
            # required query must still fail this collection attempt.
            return CollectionResult(slug, 1 if slug == SLUGS[-1] else 0, selection([slug]))

        later = []
        operations = {
            "collect": lambda context: collect_operation(context, collector=collector),
            "validate": lambda *args: later.append("validate") or result("validate-collection"),
            "generate": lambda *args: later.append("generate") or result("generate"),
            "certify": lambda *args: later.append("certify") or result("certify"),
        }
        value = pipeline_operation(CONTEXT, "2026-01-15", REVISION, operations=operations)
        self.assertEqual((value["status"], value["code"]), ("failure", "PIPELINE_STAGE_FAILED"))
        self.assertEqual(calls, SLUGS)
        self.assertEqual(later, [])
        self.assertEqual(value["stage_results"][0]["code"], "COLLECTION_QUERY_FAILED")
        self.assertEqual(validate_named(value, "execution-result.v1"), [])

    def test_collecting_pipeline_rejects_collection_id_date_mismatch_before_collection(self):
        calls = []
        value = pipeline_operation(
            CONTEXT, "2026-01-14", REVISION,
            operations={"collect": lambda context: calls.append("collect") or result("collect")},
        )
        self.assertEqual((value["status"], value["code"]), ("failure", "COLLECTION_ID_MISMATCH"))
        self.assertEqual(calls, [])
        self.assertEqual(validate_named(value, "execution-result.v1"), [])

    def test_skip_collect_fixture_pipeline_uses_archived_complete_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current"
            operations = {
                "validate": lambda context, collection_id: validate_collection_operation(
                    context, collection_id, FIXTURE_RAW),
                "generate": lambda context, collection_id: result("generate", outputs=[collection_id]),
                "certify": lambda context, collection_id, revision: certify_operation(
                    context, collection_id, revision, current, FIXTURE_RAW),
                "verify": lambda context: verify_operation(context, current),
                "publish": lambda context: publish_operation(context, current),
            }
            first = pipeline_operation(CONTEXT, "2026-01-15", REVISION,
                                       include_collect=False, operations=operations)
            second = pipeline_operation(CONTEXT, "2026-01-15", REVISION,
                                        include_collect=False, operations=operations)
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "success")
            self.assertEqual([stage["operation"] for stage in first["stage_results"]],
                             ["validate-collection", "generate", "certify", "verify", "publish"])

    def test_pipeline_stops_after_each_failure(self):
        stage_names = ["validate", "generate", "certify", "verify", "publish"]
        operation_names = {"validate": "validate-collection", "generate": "generate", "certify": "certify", "verify": "verify", "publish": "publish"}
        for failure_index, failure_name in enumerate(stage_names):
            calls = []
            operations = {}
            for name in stage_names:
                def make(stage):
                    return lambda *args: calls.append(stage) or result(operation_names[stage], "failure" if stage == failure_name else "success", "GENERATION_FAILED" if stage == failure_name else "OK")
                operations[name] = make(name)
            value = pipeline_operation(CONTEXT, "2026-01-15", REVISION, include_collect=False, operations=operations)
            self.assertEqual(value["status"], "failure")
            self.assertEqual(calls, stage_names[:failure_index + 1])

    def test_every_operation_result_validates(self):
        names = ["collect", "validate-collection", "generate", "certify", "verify", "publish", "pipeline"]
        for name in names:
            self.assertEqual(validate_named(result(name), "execution-result.v1"), [])

    def test_explicit_source_revision(self):
        self.assertEqual(resolve_source_revision("A" * 40), ("a" * 40, None))

    def test_invalid_explicit_source_revision(self):
        self.assertIsNotNone(resolve_source_revision("main")[1])

    def test_dirty_tree_blocks_automatic_revision(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=" M file.py\n", stderr="")
        self.assertIn("clean", resolve_source_revision(None, run=fake_run)[1])

    def test_current_certified_bundle_remains_valid(self):
        value = verify_operation(CONTEXT)
        self.assertEqual(value["status"], "success")


if __name__ == "__main__":
    unittest.main()
