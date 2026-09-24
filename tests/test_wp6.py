from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = json.loads((ROOT / "config/production-migration.json").read_text())
WRANGLER = json.loads((ROOT / "wrangler.jsonc").read_text())
WORKER = (ROOT / "cloudflare/worker-radar.js").read_text()


class WP6MigrationTests(unittest.TestCase):
    def test_target_topology_is_consistent(self):
        self.assertEqual(MIGRATION["repository"]["target"], "jamesbregenzer/radar.wp.org.nz")
        self.assertEqual(MIGRATION["worker"]["canonical_hostname"], "radar.wp.org.nz")
        self.assertEqual(MIGRATION["worker"]["name"], WRANGLER["name"])
        self.assertEqual(MIGRATION["worker"]["assets_directory"], WRANGLER["assets"]["directory"])
        self.assertEqual(WRANGLER["assets"]["binding"], "ASSETS")
        self.assertTrue(WRANGLER["assets"]["run_worker_first"])
        self.assertNotIn("routes", WRANGLER)
        self.assertNotIn("route", WRANGLER)
        self.assertNotIn("vars", WRANGLER)

    def test_worker_has_no_pages_or_legacy_hostname_dependency(self):
        self.assertNotIn("pages.dev", WORKER)
        self.assertNotIn("radar.james.bregenzer.dev", WORKER)
        self.assertNotIn('DEFAULT_GITHUB_REPO', WORKER)
        self.assertNotIn('GITHUB_TOKEN', WORKER)
        self.assertNotIn('env.GITHUB_REPO', WORKER)
        self.assertNotIn('env.GITHUB_OWNER', WORKER)
        self.assertIn('review-state.json', WORKER)

    def test_worker_routes_cover_human_and_machine_surfaces(self):
        for route in [
            "/api/v1/health", "/api/v1/snapshot", "/api/v1/collection",
            "/api/v1/opportunities", "/admin/", "/admin/login",
            "/admin/save", "/admin/props",
        ]:
            self.assertIn(route, WORKER)
        self.assertIn("return env.ASSETS.fetch(request)", WORKER)

    def test_redirect_contract_is_safe_and_explicit(self):
        apex, legacy = MIGRATION["redirects"]
        self.assertEqual(apex["source_hosts"], ["wp.org.nz", "www.wp.org.nz"])
        self.assertEqual(apex["destination"], "https://wordpress.org/")
        self.assertEqual(apex["status"], 301)
        self.assertFalse(apex["preserve_path"])
        self.assertFalse(apex["preserve_query"])
        self.assertEqual(legacy["source_hosts"], ["radar.james.bregenzer.dev"])
        self.assertEqual(legacy["destination_origin"], "https://radar.wp.org.nz")
        self.assertTrue(legacy["preserve_path"])
        self.assertTrue(legacy["preserve_query"])
        self.assertTrue(legacy["enable_after_acceptance"])

    def test_no_old_identity_in_active_product_configuration(self):
        active_paths = [
            ROOT / "cloudflare/worker-radar.js",
            ROOT / "wrangler.jsonc",
            ROOT / "package.json",
            ROOT / "scripts/certification.py",
            ROOT / "scripts/generate-api.py",
            ROOT / "scripts/generate-dashboard.py",
            ROOT / "scripts/generate-report.py",
            ROOT / "scripts/operations.py",
            ROOT / "scripts/pipeline.py",
            ROOT / "scripts/radar.py",
        ]
        forbidden = re.compile(r"radar\.james\.bregenzer\.dev|pages\.dev|wp-core-radar", re.I)
        for path in active_paths:
            self.assertIsNone(forbidden.search(path.read_text()), path.as_posix())


if __name__ == "__main__":
    unittest.main()
