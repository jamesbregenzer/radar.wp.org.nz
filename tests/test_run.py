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

if __name__ == "__main__": unittest.main()
