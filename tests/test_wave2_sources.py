from __future__ import annotations
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from wave2_sources import normalize_github_item, normalize_release_offer, normalize_wp_item, normalize_resources

class Wave2SourceTests(unittest.TestCase):
    def test_normalization_preserves_public_identity_and_signals(self):
        resource = normalize_wp_item({"id": 10, "link": "https://make.wordpress.org/test/post", "slug": "help-test-wordpress-beta", "date_gmt": "2026-10-01T00:00:00", "modified_gmt": "2026-10-02T00:00:00", "title": {"rendered": "Call for testing: WordPress 7.2 Beta 1"}, "content": {"rendered": '<p>Test this. <a href="https://github.com/WordPress/gutenberg/issues/1">Gutenberg</a></p>'}, "tags": []}, "MAKE_TEST_RELEASE_SIGNALS", "WORDPRESS_MAKE_POST", "2026-10-06T12:00:00Z")
        self.assertEqual(resource["nativeIdentity"], "wordpress_make_post/10")
        self.assertEqual({item["familyId"] for item in resource["candidateSignals"]}, {"BETA_RC_TEST", "GUTENBERG_TEST"})

    def test_normalize_resources_dedupes_native_identity(self):
        body = b'[{"id": 10, "link": "https://example.test/post", "slug": "call-for-testing", "date_gmt": "2026-10-01T00:00:00", "modified_gmt": "2026-10-02T00:00:00", "title": {"rendered": "Call for testing: WordPress 7.2 Beta 1"}, "content": {"rendered": "<p>Test this beta.</p>"}, "tags": []}]'
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts"}
        resources = normalize_resources(config, [("https://example.test", body, {}, 200), ("https://example.test/again", body, {}, 200)], "2026-10-06T12:00:00Z")
        self.assertEqual(len(resources), 1)

    def test_make_post_without_explicit_request_does_not_become_candidate(self):
        resource = normalize_wp_item({"id": 11, "link": "https://make.wordpress.org/accessibility/meeting-notes/", "slug": "meeting-notes", "date_gmt": "2026-10-01T00:00:00", "modified_gmt": "2026-10-01T00:00:00", "title": {"rendered": "Accessibility team meeting notes"}, "content": {"rendered": "<p>Routine meeting notes.</p>"}, "tags": []}, "ACCESSIBILITY_REQUESTS", "WORDPRESS_MAKE_POST")
        self.assertEqual(resource["candidateSignals"], [])

    def test_documentation_issue_requires_unassigned_open_request(self):
        base = {"node_id": "I_fixture", "number": 42, "html_url": "https://github.com/WordPress/Documentation-Issue-Tracker/issues/42", "title": "[DevHub] Correct developer handbook example", "body": "The example is outdated.", "state": "open", "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z", "labels": [], "assignees": [], "repository_url": "https://api.github.com/repos/WordPress/Documentation-Issue-Tracker"}
        self.assertEqual(normalize_github_item(base, "CORE_DEVELOPER_DOCS", "2026-10-06T00:00:00Z")["candidateSignals"][0]["familyId"], "DOCS_REVIEW")
        self.assertEqual(normalize_github_item({**base, "assignees": [{"login": "owner"}]}, "CORE_DEVELOPER_DOCS", "2026-10-06T00:00:00Z")["candidateSignals"], [])

    def test_release_nightly_is_not_a_candidate_but_beta_is(self):
        nightly = normalize_release_offer({"current": "7.2-alpha-64115", "version": "7.2-alpha-64115", "locale": "en_US", "response": "development"}, "development")
        beta = normalize_release_offer({"current": "7.2-beta1", "version": "7.2-beta1", "locale": "en_US", "response": "upgrade"}, "beta")
        self.assertEqual(nightly["candidateSignals"], [])
        self.assertEqual(beta["candidateSignals"][0]["familyId"], "BETA_RC_TEST")

if __name__ == "__main__": unittest.main()
