from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline import collect_query
from radarcore import RunContext
from radarlib import load_queries

def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


IMPORT_DOWNLOAD = load_script("import-download.py")


class ScheduledContinuityTests(unittest.TestCase):
    def test_browser_collection_receives_frozen_pre_boundary_identity(self):
        context = RunContext.from_iso("2026-09-23T23:59:59Z")
        commands: list[list[str]] = []

        collect_query("general_needs_testing", context, runner=lambda command: commands.append(command) or 1)

        self.assertEqual(commands[0][-2:], ["--collection-id", "2026-09-23"])

    def test_import_uses_explicit_collection_id_not_current_wall_clock(self):
        slug = str(load_queries()[0]["slug"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "query.csv"
            source.write_text("id,summary\n1,Fixture\n", encoding="utf-8")
            archive = root / "manual"
            with patch.object(IMPORT_DOWNLOAD, "RAW_MANUAL", archive):
                target = IMPORT_DOWNLOAD.import_download(
                    slug, source, collection_id="2026-09-23"
                )
            self.assertEqual(target, archive / "2026-09-23" / f"{slug}.csv")
            self.assertTrue(target.exists())

    def test_wrapper_freezes_context_and_uses_canonical_pipeline(self):
        wrapper = (ROOT / "scripts" / "run-scheduled-radar.sh").read_text()
        self.assertIn('REFERENCE_TIME="${RADAR_REFERENCE_TIME:-$(date -u', wrapper)
        self.assertIn('COLLECTION_ID="${REFERENCE_TIME:0:10}"', wrapper)
        self.assertIn('scripts/radar.py collect', wrapper)
        self.assertIn('scripts/radar.py pipeline', wrapper)
        self.assertIn('--skip-collect', wrapper)
        self.assertIn('--collection-id "$COLLECTION_ID"', wrapper)
        self.assertIn('--reference-time "$REFERENCE_TIME"', wrapper)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "run-scheduled-radar.sh")], check=True)

    def test_failed_run_preserves_evidence_and_restores_clean_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            (repo / "scripts").mkdir()
            (repo / "data" / "raw" / "manual").mkdir(parents=True)
            (repo / "docs").mkdir()
            (repo / "reports").mkdir()
            shutil.copy2(ROOT / "scripts" / "run-scheduled-radar.sh", repo / "scripts")
            (repo / ".gitignore").write_text("logs/\n", encoding="utf-8")
            tracked = repo / "data" / "tracked.txt"
            tracked.write_text("known-good\n", encoding="utf-8")

            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Radar Test"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            origin = Path(directory) / "origin.git"
            subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)

            fake_python = Path(directory) / "fake-python"
            fake_python.write_text(
                "#!/bin/bash\n"
                "if [[ \"$1\" == \"--version\" ]]; then echo 'Python fixture'; exit 0; fi\n"
                "if [[ \"$1\" == \"-\" ]]; then cat >/dev/null; echo 'q1,q2,q3,q4,q5'; exit 0; fi\n"
                "if [[ \"$1\" == \"scripts/radar.py\" && \"$2\" == \"collect\" ]]; then\n"
                "  echo partial > data/tracked.txt\n"
                "  mkdir -p data/raw/manual/2026-09-23\n"
                "  echo 'id,summary' > data/raw/manual/2026-09-23/q1.csv\n"
                "  exit 1\n"
                "fi\n"
                "exit 99\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = os.environ | {
                "RADAR_REPO_DIR": str(repo),
                "RADAR_PYTHON_BIN": str(fake_python),
                "RADAR_REFERENCE_TIME": "2026-09-23T23:59:59Z",
            }
            completed = subprocess.run(
                ["bash", str(repo / "scripts" / "run-scheduled-radar.sh")],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(tracked.read_text(encoding="utf-8"), "known-good\n")
            self.assertFalse((repo / "data" / "raw" / "manual" / "2026-09-23").exists())
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True),
                "",
            )
            evidence = repo / "logs" / "failed-runs" / "2026-09-23T23-59-59Z"
            self.assertTrue((evidence / "run-context.txt").exists())
            self.assertTrue((evidence / "collection-artifacts" / "q1.csv").exists())

    def test_validate_only_fixture_runs_complete_context_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            (repo / "scripts").mkdir()
            (repo / "data" / "raw" / "manual").mkdir(parents=True)
            (repo / "docs").mkdir()
            (repo / "reports").mkdir()
            shutil.copy2(ROOT / "scripts" / "run-scheduled-radar.sh", repo / "scripts")
            (repo / ".gitignore").write_text("logs/\n", encoding="utf-8")
            tracked = repo / "data" / "tracked.txt"
            tracked.write_text("known-good\n", encoding="utf-8")

            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Radar Test"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            origin = Path(directory) / "origin.git"
            subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)

            fake_python = Path(directory) / "fake-python"
            fake_python.write_text(
                "#!/bin/bash\n"
                "if [[ \"$1\" == \"--version\" ]]; then echo 'Python fixture'; exit 0; fi\n"
                "if [[ \"$1\" == \"-\" ]]; then cat >/dev/null; echo 'q1,q2,q3,q4,q5'; exit 0; fi\n"
                "if [[ \"$1\" == \"scripts/radar.py\" && \"$2\" == \"collect\" ]]; then\n"
                "  echo collected > data/tracked.txt\n"
                "  mkdir -p data/raw/manual/2026-09-23\n"
                "  for q in q1 q2 q3 q4 q5; do echo 'id,summary' > data/raw/manual/2026-09-23/$q.csv; done\n"
                "  exit 0\n"
                "fi\n"
                "if [[ \"$1\" == \"scripts/verify-collector-snapshot.py\" ]]; then exit 0; fi\n"
                "if [[ \"$1\" == \"scripts/radar.py\" && \"$2\" == \"pipeline\" ]]; then\n"
                "  mkdir -p docs/radar\n"
                "  echo generated > docs/radar/result.txt\n"
                "  exit 0\n"
                "fi\n"
                "exit 99\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = os.environ | {
                "RADAR_REPO_DIR": str(repo),
                "RADAR_PYTHON_BIN": str(fake_python),
                "RADAR_REFERENCE_TIME": "2026-09-23T23:59:59Z",
                "RADAR_PUBLISH_MODE": "validate-only",
            }
            completed = subprocess.run(
                ["bash", str(repo / "scripts" / "run-scheduled-radar.sh")],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("no commit or push was performed", completed.stdout)
            self.assertEqual(tracked.read_text(encoding="utf-8"), "known-good\n")
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True),
                "",
            )
            self.assertEqual(
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                before,
            )
            context = repo / "logs" / "failed-runs" / "2026-09-23T23-59-59Z" / "run-context.txt"
            self.assertIn("result=validated-not-published", context.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
