from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from radarcore import RunContext, load_scoring_config, parse_run_time, select_datasets, validate_csv_artifact
from radarlib import TICKET_ID_KEYS, build_opportunities, days_since, normalize_ticket_id, parse_datetime, score_ticket

FIXTURES = ROOT / "tests" / "fixtures"
REFERENCE = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


class CoreTests(unittest.TestCase):
    def test_run_context_is_stable(self):
        context = parse_run_time("2026-01-15T12:00:00Z")
        self.assertEqual(context.collection_date, "2026-01-15")
        self.assertEqual(context.generated_iso, "2026-01-15T12:00:00")

    def test_naive_run_time_becomes_utc(self):
        self.assertEqual(parse_run_time("2026-01-15T12:00:00").reference_time.tzinfo, timezone.utc)

    def test_datetime_parsing(self):
        self.assertEqual(parse_datetime("01/10/2026 03:00 PM").day, 10)

    def test_days_since_requires_supplied_clock(self):
        self.assertEqual(days_since("2026-01-10", REFERENCE), 5)

    def test_ticket_id_normalization(self):
        self.assertEqual(normalize_ticket_id("#123"), "123")

    def test_scoring_config_is_executable(self):
        config = load_scoring_config()
        self.assertEqual(config["version"], "radar-scoring-v1")
        self.assertEqual(config["points"]["has_patch"], 35)

    def test_scoring_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"version": "x"}))
            with self.assertRaises(ValueError):
                load_scoring_config(path)

    def test_fresh_ticket_score_is_deterministic(self):
        row = {"ticket_id": "1", "summary": "A", "keywords": "has-patch", "modified": "2026-01-10"}
        score, reasons = score_ticket(row, {"priority": 50}, {}, REFERENCE)
        self.assertEqual(score, 105)
        self.assertIn("freshness: recently updated <=14 days +20", reasons)

    def test_closed_ticket_penalty(self):
        score, _ = score_ticket({"ticket_id": "1", "summary": "A", "status": "closed"}, {"priority": 50}, {}, REFERENCE)
        self.assertEqual(score, -50)

    def test_empty_csv_is_valid_with_warning(self):
        path = FIXTURES / "raw/manual/2026-01-15/docs_needs_testing.csv"
        evidence = validate_csv_artifact(path, "docs_needs_testing", TICKET_ID_KEYS)
        self.assertTrue(evidence.valid)
        self.assertEqual(evidence.row_count, 0)
        self.assertIn("empty_but_valid", evidence.warnings)
        self.assertEqual(len(evidence.sha256), 64)

    def test_unrecognized_csv_is_invalid(self):
        evidence = validate_csv_artifact(FIXTURES / "malformed.csv", "bad", TICKET_ID_KEYS)
        self.assertFalse(evidence.valid)
        self.assertIn("missing_ticket_id_header", evidence.errors)

    def test_missing_csv_is_invalid(self):
        evidence = validate_csv_artifact(FIXTURES / "missing.csv", "bad", TICKET_ID_KEYS)
        self.assertFalse(evidence.exists)

    def test_explicit_selection_is_complete(self):
        expected = ["media_has_patch", "accessibility_has_patch", "docs_needs_testing", "good_first_bugs", "general_needs_testing"]
        selection = select_datasets(FIXTURES / "raw", "2026-01-15", expected, TICKET_ID_KEYS)
        self.assertTrue(selection.complete)
        self.assertEqual(set(selection.artifacts), set(expected))

    def test_selection_reports_unexpected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "manual/2026-01-15"
            base.mkdir(parents=True)
            (base / "expected.csv").write_text("id,summary\n1,A\n")
            (base / "surprise.csv").write_text("id,summary\n2,B\n")
            selection = select_datasets(Path(directory), "2026-01-15", ["expected"], TICKET_ID_KEYS)
            self.assertEqual([path.name for path in selection.unexpected], ["surprise.csv"])

    def test_duplicate_rows_choose_highest_score(self):
        expected = ["media_has_patch", "accessibility_has_patch", "docs_needs_testing", "good_first_bugs", "general_needs_testing"]
        selection = select_datasets(FIXTURES / "raw", "2026-01-15", expected, TICKET_ID_KEYS)
        opportunities, sources, _ = build_opportunities(RunContext(REFERENCE), selection)
        ids = [item.ticket_id for item in opportunities]
        self.assertEqual(ids.count("101"), 1)
        self.assertEqual(sources["101"], {"media_has_patch", "general_needs_testing"})
        self.assertEqual(opportunities[0].ticket_id, "101")

    def test_same_inputs_same_opportunities(self):
        expected = ["media_has_patch", "accessibility_has_patch", "docs_needs_testing", "good_first_bugs", "general_needs_testing"]
        selection = select_datasets(FIXTURES / "raw", "2026-01-15", expected, TICKET_ID_KEYS)
        first = build_opportunities(RunContext(REFERENCE), selection)[0]
        second = build_opportunities(RunContext(REFERENCE), selection)[0]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
