from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("generate_dashboard", ROOT / "scripts" / "generate-dashboard.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class WP6APortabilityTests(unittest.TestCase):
    def test_safe_review_projection_excludes_private_notes(self):
        projected = MODULE.safe_review_projection({
            "status": "watch",
            "reason": "Useful public-safe reason",
            "notes": "private operator note",
            "updated_at": "2026-09-23T00:00:00Z",
            "received_props": True,
            "changeset": "62521",
        })
        self.assertEqual(projected["status"], "watch")
        self.assertEqual(projected["reason"], "Useful public-safe reason")
        self.assertTrue(projected["received_props"])
        self.assertEqual(projected["changeset"], "62521")
        self.assertNotIn("notes", projected)

    def test_committed_review_state_is_safe_and_versioned(self):
        payload = json.loads((ROOT / "docs" / "radar" / "review-state.json").read_text())
        self.assertEqual(payload["schema"], "radar-review-state.v1")
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["reviews"])
        for review in payload["reviews"].values():
            self.assertNotIn("notes", review)
            self.assertLessEqual(set(review), {
                "status", "reason", "updated_at", "received_props",
                "props_recorded_at", "changeset",
            })

    def test_admin_projection_contains_no_private_notes(self):
        payload = json.loads((ROOT / "docs" / "radar" / "admin-data.json").read_text())
        for items in payload.get("groups", {}).values():
            for item in items:
                self.assertNotIn("notes", item.get("review", {}))

    def test_worker_has_no_runtime_github_dependency(self):
        worker = (ROOT / "cloudflare" / "worker-radar.js").read_text()
        for forbidden in ("GITHUB_TOKEN", "api.github.com", "githubRequest(", "saveReviews("):
            self.assertNotIn(forbidden, worker)


if __name__ == "__main__":
    unittest.main()
