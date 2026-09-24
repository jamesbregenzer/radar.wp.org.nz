from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from certifiedmodel import load_certified_projection


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class WP5AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.bundle = ROOT / "data/certified/current"
        self.feed = json.loads((self.bundle / "opportunities.json").read_text())

    def test_projection_preserves_order_scores_identity_and_provenance(self):
        ranked, sources, summary = load_certified_projection()
        records = self.feed["opportunities"]
        self.assertEqual([item["ticket_id"] for item in ranked], [item["ticket"]["id"] for item in records])
        self.assertEqual([item["score"] for item in ranked], [item["ranking"]["score"] for item in records])
        for record in records:
            self.assertEqual(sources[record["ticket"]["id"]],
                             {item["query_slug"] for item in record["discovery"]["sources"]})
        self.assertEqual(summary["certification"]["opportunity_count"], len(records))

    def test_admin_payload_is_aligned_and_private_notes_are_overlay_only(self):
        dashboard = load_script("wp5_dashboard", "generate-dashboard.py")
        payload = dashboard.admin_data_payload()
        flattened = [item for group in payload["groups"].values() for item in group]
        by_id = {item["ticket_id"]: item for item in flattened}
        for record in self.feed["opportunities"]:
            self.assertEqual(by_id[record["ticket"]["id"]]["score"], record["ranking"]["score"])
        self.assertIn("certification", payload["summary"])
        self.assertNotIn("notes", json.dumps(self.feed).lower())

    def test_review_overlay_does_not_mutate_certified_snapshot(self):
        before = hashlib.sha256((self.bundle / "snapshot.json").read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            reviews = Path(directory) / "reviews.json"
            reviews.write_text(json.dumps({"65661": {"status": "watch", "notes": "private overlay"}}))
            ranked, _, _ = load_certified_projection(reviews_path=reviews)
            item = next(item for item in ranked if item["ticket_id"] == "65661")
            self.assertEqual(item["review"]["notes"], "private overlay")
        self.assertEqual(hashlib.sha256((self.bundle / "snapshot.json").read_bytes()).hexdigest(), before)

    def test_dashboard_health_and_count_match_feed(self):
        dashboard = load_script("wp5_dashboard_health", "generate-dashboard.py")
        value = dashboard.build_dashboard()
        snapshot = json.loads((self.bundle / "snapshot.json").read_text())
        self.assertIn(snapshot["snapshot_id"].removeprefix("snapshot-v1-")[:12], value)
        self.assertIn(str(snapshot["opportunity_count"]), value)
        self.assertIn(snapshot["scoring_version"], value)

    def test_markdown_report_uses_certified_identity(self):
        report = load_script("wp5_report", "generate-report.py").build_report()
        snapshot = json.loads((self.bundle / "snapshot.json").read_text())
        self.assertIn(snapshot["snapshot_id"], report)


if __name__ == "__main__":
    unittest.main()
