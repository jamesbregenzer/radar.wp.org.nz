import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record-contribution.py"


class PublicContributionStateTests(unittest.TestCase):
    def run_recorder(self, root: Path, *args: str):
        state_dir = root / "data" / "contributions"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "contribution-state.json").write_text(
            json.dumps({"schema": "contribution-state.v1", "version": 1, "contributions": []}) + "\n",
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=root,
            capture_output=True,
            text=True,
        )

    def test_rejects_unverified_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_recorder(
                Path(tmp),
                "--ticket", "63568",
                "--lifecycle-state", "TESTED",
                "--status", "tested",
                "--public-url", "https://core.trac.wordpress.org/ticket/63568",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PUBLIC_DELIVERY_VERIFIED_REQUIRED", result.stderr + result.stdout)

    def test_records_only_verified_public_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_recorder(
                root,
                "--ticket", "63568",
                "--lifecycle-state", "PUBLIC_DELIVERY_VERIFIED",
                "--status", "commented",
                "--public-url", "https://core.trac.wordpress.org/ticket/63568#comment:1",
                "--tested-sha", "7c82a49985545e1aa65cee06622b63303857ace1",
                "--updated-at", "2026-09-28T15:00:00Z",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(
                (root / "data" / "contributions" / "contribution-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(payload["contributions"]), 1)
            self.assertEqual(payload["contributions"][0]["lifecycle_state"], "PUBLIC_DELIVERY_VERIFIED")

    def test_props_require_observed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_recorder(
                Path(tmp),
                "--ticket", "63568",
                "--lifecycle-state", "PUBLIC_DELIVERY_VERIFIED",
                "--status", "commented",
                "--public-url", "https://core.trac.wordpress.org/ticket/63568",
                "--received-props",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PROPS_OBSERVATION_REQUIRED", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
