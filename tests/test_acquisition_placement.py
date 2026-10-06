from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from acquisition_placement import (
    ERROR_CODE,
    PlacementError,
    receipt_execution_metadata,
    require_trac_acquisition_placement,
    resolve_placement,
)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


BROWSER_FETCH = load_script("browser-fetch.py")


class AcquisitionPlacementTests(unittest.TestCase):
    def test_trac_acquisition_capability_resolves_to_thor(self):
        placement = require_trac_acquisition_placement(
            env={"RADAR_ACQUISITION_PROVIDER": "thor"},
            hostname="jb",
        )

        self.assertTrue(placement.accepted)
        self.assertEqual(placement.capability, "wordpress.trac.raw-acquisition")
        self.assertEqual(placement.provider, "thor")
        self.assertTrue(placement.unattended)

    def test_normal_acquisition_fails_closed_on_jb(self):
        with self.assertRaises(PlacementError) as raised:
            require_trac_acquisition_placement(env={}, hostname="jb")

        self.assertEqual(raised.exception.code, ERROR_CODE)
        self.assertEqual(raised.exception.placement.status, "wrong-host")

    def test_explicit_interactive_canary_is_marked_noncanonical(self):
        placement = require_trac_acquisition_placement(
            env={},
            hostname="jb",
            allow_interactive_canary=True,
        )

        self.assertEqual(placement.status, "diagnostic-canary")
        self.assertFalse(placement.unattended)
        self.assertEqual(placement.host, "noncanonical-interactive")

    def test_receipt_metadata_exposes_operator_visibility(self):
        placement = resolve_placement(env={"RADAR_ACQUISITION_PROVIDER": "thor"}, hostname="jb")
        metadata = receipt_execution_metadata(
            placement=placement,
            started_at="2026-10-06T10:00:00Z",
            completed_at="2026-10-06T10:00:02Z",
            upload_status="uploaded",
            readback_status="verified",
            next_scheduled_at="2026-10-06T22:00:00Z",
        )

        self.assertEqual(metadata["capability"], "wordpress.trac.raw-acquisition")
        self.assertEqual(metadata["host"], "thor")
        self.assertEqual(metadata["uploadStatus"], "uploaded")
        self.assertEqual(metadata["readbackStatus"], "verified")
        self.assertIsNone(metadata["failureReason"])

    def test_browser_fetch_guard_prevents_local_download_attempt(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "browser-fetch.py"),
                "general_needs_testing",
                "--collection-id",
                "2026-10-06T10-00-00Z",
            ],
            cwd=ROOT,
            env={},
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 78)
        self.assertIn(ERROR_CODE, completed.stderr)

    def test_browser_fetch_supports_explicit_interactive_canary_flag(self):
        parser_text = Path(BROWSER_FETCH.__file__).read_text(encoding="utf-8")
        self.assertIn("--interactive-canary", parser_text)
        self.assertIn("require_trac_acquisition_placement", parser_text)

    def test_placement_check_reports_bounded_failure(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check-acquisition-placement.py")],
            cwd=ROOT,
            env={},
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 78)
        payload = json.loads(completed.stderr)
        self.assertEqual(payload["code"], ERROR_CODE)
        self.assertEqual(payload["placement"]["capability"], "wordpress.trac.raw-acquisition")


if __name__ == "__main__":
    unittest.main()
