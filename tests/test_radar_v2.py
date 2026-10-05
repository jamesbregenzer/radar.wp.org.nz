from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from radarv2 import load_wordpress_develop_source, project_v2


class RadarV2ProjectionTests(unittest.TestCase):
    def payloads(self, wordpress_develop=None):
        snapshot = json.loads((ROOT / "data" / "certified" / "current" / "snapshot.json").read_text())
        collection = json.loads((ROOT / "data" / "certified" / "current" / "collection.json").read_text())
        opportunities = json.loads((ROOT / "data" / "certified" / "current" / "opportunities.json").read_text())
        contributions = json.loads((ROOT / "docs" / "radar" / "api" / "v1" / "contributions.json").read_text())
        return project_v2(
            snapshot=snapshot,
            collection=collection,
            opportunities=opportunities,
            contributions=contributions,
            wordpress_develop=wordpress_develop,
        )

    def test_v2_projection_is_repeatable(self):
        source = load_wordpress_develop_source()
        self.assertEqual(self.payloads(source), self.payloads(source))

    def test_v2_reports_github_degradation_without_blocking_trac(self):
        payloads = self.payloads(None)
        health = json.loads(payloads["health.json"])
        families = {item["sourceFamily"]: item for item in health["sourceFamilies"]}
        self.assertEqual(families["CORE_TRAC"]["health"]["state"], "certified")
        self.assertEqual(families["WORDPRESS_DEVELOP_GITHUB"]["health"]["state"], "degraded")
        self.assertEqual(health["status"], "degraded")

    def test_v2_opportunities_include_public_model_fields(self):
        source = load_wordpress_develop_source()
        opportunities = json.loads(self.payloads(source)["opportunities.json"])
        first = opportunities["opportunities"][0]
        self.assertTrue(first["id"].startswith("core-trac:"))
        self.assertTrue(first["revision"].startswith("opportunity-revision-v2-"))
        self.assertEqual(first["canonicalResource"]["sourceFamily"], "CORE_TRAC")
        self.assertIn(first["qualification"]["state"], {
            "CLEAR_OPPORTUNITY",
            "POSSIBLE_OPPORTUNITY",
            "NEEDS_MORE_EVIDENCE",
            "UPSTREAM_CHANGED",
            "LIKELY_ALREADY_COVERED",
            "NO_CLEAR_CONTRIBUTION",
        })
        self.assertTrue(first["qualification"]["whyNow"])
        self.assertIn("ticket_fields", first["sourceCoverage"])
        self.assertIn("confidence", first["ranking"]["dimensions"])


if __name__ == "__main__":
    unittest.main()
