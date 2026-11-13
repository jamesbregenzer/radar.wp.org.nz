from __future__ import annotations
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run

class RunnerTests(unittest.TestCase):
    def test_previous_input_is_the_newest_prior_observation_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, observed in (("old", "2026-10-06T12:00:00Z"), ("new", "2026-10-07T12:00:00Z")):
                path = root / name; path.mkdir()
                (path / "run.json").write_text(json.dumps({"schema": "radar-observation-set.v2", "success": True, "observedAt": observed, "observations": [{"sourceId": name}]}))
            (root / "current").mkdir()
            (root / "current" / "run.json").write_text(json.dumps({"schema": "radar-observation-set.v2", "success": True, "observedAt": "2026-10-08T12:00:00Z", "observations": [{"sourceId": "current"}]}))
            self.assertEqual(run.prior_observation_run(root, "current")["observations"][0]["sourceId"], "new")

    def test_fresh_raw_run_is_staged_when_feed_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "lock"; feed_path = Path(temporary) / "candidate-feed.json"
            feed = json.loads((ROOT / "data/candidate-feed.json").read_text())
            feed_path.write_text(json.dumps(feed, indent=2, sort_keys=True) + "\n")
            manifest = {"success": True, "runId": "fresh-run", "observations": []}
            calls = []
            with patch.object(run, "LOCK", lock), patch.object(run, "FEED", feed_path), patch.object(run, "acquire_run", return_value=manifest), patch.object(run, "build_feed", return_value=feed), patch.object(run, "prior_observation_run", return_value=None), patch.object(run, "git", side_effect=lambda *args: calls.append(args)), patch.object(run.subprocess, "run", return_value=type("Result", (), {"returncode": 1})()):
                self.assertEqual(run.run_once(), 0)
            self.assertIn(("add", "data/raw/fresh-run"), calls)
            self.assertIn(("commit", "-m", "Update Radar V2 candidate feed"), calls)

    def test_invalid_feed_is_not_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            with patch.object(run, "LOCK", Path(temporary) / "lock"), patch.object(run, "FEED", Path(temporary) / "candidate-feed.json"), patch.object(run, "acquire_run", return_value={"success": True, "runId": "bad", "observations": []}), patch.object(run, "build_feed", return_value={"schema": "invalid"}), patch.object(run, "git", side_effect=lambda *args: calls.append(args)):
                with self.assertRaises(ValueError): run.run_once()
            self.assertEqual(calls, [])

    def test_local_overlap_lock_returns_two(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "lock"
            with lock.open("a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(run, "LOCK", lock):
                    self.assertEqual(run.run_once(), 2)

    @staticmethod
    def write_receipt(raw_root: Path, name: str, value: dict) -> Path:
        path = raw_root / name / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    @staticmethod
    def eligible_legacy(run_id: str, observed_at: str, row_id: str) -> dict:
        return {
            "schema": "radar-observation-set.v2",
            "runId": run_id,
            "observedAt": observed_at,
            "success": True,
            "observations": [{"sourceId": "legacy-source", "rows": [{"id": row_id}]}],
        }

    def test_prior_selector_skips_every_explicit_false_marker_and_falls_back(self):
        false_markers = (
            {"publicationEligible": False},
            {"sourceCoverage": {"publicationEligible": False}},
            {"observations": [{"sourceId": "private", "publicationEligible": False}]},
            {"observations": [{"sourceId": "private", "acquisitionDiagnostics": {"publicationEligible": False}}]},
        )
        for index, marker in enumerate(false_markers):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                raw_root = Path(temporary)
                eligible = self.eligible_legacy("eligible", "2026-11-10T00:00:00Z", "legacy-row")
                private = {
                    "schema": "radar-observation-set.v2", "runId": f"private-{index}",
                    "observedAt": "2026-11-12T00:00:00Z", "success": True,
                    "observations": [{"sourceId": "private", "rows": [{"id": "private-row"}]}],
                    **marker,
                }
                self.write_receipt(raw_root, "eligible", eligible)
                self.write_receipt(raw_root, f"private-{index}", private)
                self.assertEqual(run.prior_observation_run(raw_root, "current"), eligible)

    def test_prior_selector_returns_none_when_all_history_is_nonpublishable(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw_root = Path(temporary)
            for name, marker in (
                ("top", {"publicationEligible": False}),
                ("nested", {"observations": [{"publicationEligible": False}]}),
            ):
                self.write_receipt(raw_root, name, {
                    "schema": "radar-observation-set.v2", "runId": name,
                    "observedAt": "2026-11-12T00:00:00Z", "success": True,
                    "observations": [{"sourceId": name, "rows": [{"id": f"{name}-row"}]}],
                    **marker,
                })
            self.assertIsNone(run.prior_observation_run(raw_root, "current"))

    def test_current_manifest_false_markers_stop_before_prior_feed_or_git(self):
        false_markers = (
            {"publicationEligible": False},
            {"sourceCoverage": {"publicationEligible": False}},
            {"observations": [{"publicationEligible": False}]},
            {"observations": [{"acquisitionDiagnostics": {"publicationEligible": False}}]},
        )
        for marker in false_markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                lock = root / "lock"
                feed_path = root / "candidate-feed.json"
                feed_path.write_text("old feed", encoding="utf-8")
                manifest = {"success": True, "runId": "private-current", "observations": [], **marker}
                calls = []
                with patch.object(run, "LOCK", lock), patch.object(run, "FEED", feed_path), \
                     patch.object(run, "acquire_run", return_value=manifest), \
                     patch.object(run, "prior_observation_run", side_effect=lambda *_: calls.append("prior")), \
                     patch.object(run, "build_feed", side_effect=lambda *_args, **_kwargs: calls.append("build")), \
                     patch.object(run, "git", side_effect=lambda *args: calls.append(args)):
                    with self.assertRaisesRegex(RuntimeError, "publicationEligible=false"):
                        run.run_once()
                self.assertEqual(feed_path.read_text(encoding="utf-8"), "old feed")
                self.assertEqual(calls, [])

    def test_mocked_cycle_history_fallback_never_passes_private_rows_to_feed_or_git(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_root = root / "data/raw"
            self.write_receipt(raw_root, "eligible-old", self.eligible_legacy(
                "eligible-old", "2026-11-10T00:00:00Z", "eligible-row"))
            self.write_receipt(raw_root, "private-new", {
                "schema": "radar-observation-set.v2", "runId": "private-new",
                "observedAt": "2026-11-12T00:00:00Z", "success": True,
                "publicationEligible": False,
                "observations": [{"sourceId": "private-source", "rows": [{"id": "private-row"}]}],
            })
            current = {
                "schema": "radar-observation-set.v2", "success": True,
                "runId": "current", "observedAt": "2026-11-12T01:00:00Z",
                "sourceCoverage": {"successfulSources": 1, "failedSources": 16},
                "observations": [{"sourceId": "ordinary-source", "rows": []}],
            }
            feed = json.loads((ROOT / "data/candidate-feed.json").read_text(encoding="utf-8"))
            feed_path = root / "data/candidate-feed.json"
            build_inputs = []
            git_calls = []
            with patch.object(run, "ROOT", root), patch.object(run, "LOCK", root / "lock"), \
                 patch.object(run, "FEED", feed_path), patch.object(run, "acquire_run", return_value=current), \
                 patch.object(run, "build_feed", side_effect=lambda manifest, previous=None: (build_inputs.append(previous) or feed)), \
                 patch.object(run, "git", side_effect=lambda *args: git_calls.append(args)), \
                 patch.object(run.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()):
                self.assertEqual(run.run_once(), 0)

            self.assertEqual(build_inputs[0]["runId"], "eligible-old")
            self.assertNotIn("private-row", json.dumps(build_inputs))
            self.assertNotIn("private-new", json.dumps(build_inputs))
            self.assertNotIn(("add", "data/raw/private-new"), git_calls)
            self.assertIn(("add", "data/raw/current"), git_calls)
            # Existing partial-success policy remains: this successful run is not
            # rejected merely because its coverage reports other failed sources.
            self.assertTrue(feed_path.is_file())

if __name__ == "__main__": unittest.main()
