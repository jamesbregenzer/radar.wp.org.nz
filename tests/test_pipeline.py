from __future__ import annotations

import sys
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline import generate_presentations
from radarcore import RunContext, select_datasets
from radarlib import TICKET_ID_KEYS

FIXTURES = ROOT / "tests" / "fixtures"


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class PipelineTests(unittest.TestCase):
    def test_generation_passes_one_clock_to_both_renderers(self):
        commands = []
        context = RunContext(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
        result = generate_presentations(context, lambda command: commands.append(command) or 0)
        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][-1], commands[1][-1])

    def test_generation_stops_on_failure(self):
        commands = []
        context = RunContext(datetime(2026, 1, 15, tzinfo=timezone.utc))
        result = generate_presentations(context, lambda command: commands.append(command) or 7)
        self.assertEqual(result, 7)
        self.assertEqual(len(commands), 1)

    def test_report_and_dashboard_are_repeatable(self):
        context = RunContext(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
        expected = ["media_has_patch", "accessibility_has_patch", "docs_needs_testing", "good_first_bugs", "general_needs_testing"]
        selection = select_datasets(FIXTURES / "raw", "2026-01-15", expected, TICKET_ID_KEYS)
        report = load_script("fixture_report", "generate-report.py")
        dashboard = load_script("fixture_dashboard", "generate-dashboard.py")
        self.assertEqual(report.build_report(context=context, selection=selection), report.build_report(context=context, selection=selection))
        self.assertEqual(dashboard.build_dashboard(context, selection), dashboard.build_dashboard(context, selection))
        self.assertEqual(dashboard.admin_data_payload(context, selection), dashboard.admin_data_payload(context, selection))


if __name__ == "__main__":
    unittest.main()
