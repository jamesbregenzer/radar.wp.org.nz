import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicDocumentationTests(unittest.TestCase):
    def test_readme_presents_the_public_product(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://radar.wp.org.nz/", readme)
        self.assertIn("WordPress Core Trac", readme)
        self.assertIn("deterministic", readme)
        self.assertNotIn("Cloudflare Access", readme)
        self.assertNotRegex(readme, r"\bWP-[1-6](?:A)?\b")
        self.assertNotIn("\u2014", readme)

    def test_obsolete_phase_and_migration_docs_are_absent(self):
        retired = {
            "WP-2-CORE-HARDENING.md",
            "WP-3-CERTIFIED-RADAR-DATA.md",
            "WP-4-STABLE-RADAR-OPERATIONS.md",
            "WP-5-MACHINE-FEED-UI-ALIGNMENT.md",
            "WP-6-RADAR-PRODUCTION-MIGRATION.md",
            "WP-6A-ADMIN-PORTABILITY.md",
            "failed-approaches.md",
            "mac-mini-collector.md",
            "migration-radar-wp-org-nz.md",
            "vision.md",
        }
        existing = {path.name for path in (ROOT / "docs").glob("*.md")}
        self.assertTrue(retired.isdisjoint(existing))

    def test_current_docs_do_not_repeat_stale_access_or_migration_claims(self):
        paths = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("Cloudflare Access", text)
                self.assertNotIn("radar.james.bregenzer.dev", text)
                self.assertNotIn("jamesbregenzer/wp-core-radar", text)


if __name__ == "__main__":
    unittest.main()
