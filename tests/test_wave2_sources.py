from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wave2_sources import WAVE2_SCHEMAS, collect_source, normalize_github_item, normalize_release_offer, normalize_wp_item, verify_snapshot


class Wave2SourceTests(unittest.TestCase):
    def test_wave2_schemas_have_public_stable_ids(self):
        for path in WAVE2_SCHEMAS.values():
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn(path.name, schema["$id"])
            self.assertFalse(schema["additionalProperties"])

    def test_collection_retains_raw_bytes_receipt_and_source_identity(self):
        payload = [{
            "id": 10,
            "link": "https://make.wordpress.org/test/2026/10/01/help-test-wordpress-beta/",
            "slug": "help-test-wordpress-beta",
            "date_gmt": "2026-10-01T00:00:00",
            "modified_gmt": "2026-10-02T00:00:00",
            "title": {"rendered": "Call for testing: WordPress 7.2 Beta 1"},
            "content": {"rendered": '<p>This is a call for testing. See <a href="https://github.com/WordPress/gutenberg/issues/1">the issue</a>.</p>'},
            "tags": [1],
        }]
        body = json.dumps(payload).encode("utf-8")
        config = {
            "sourceFamily": "MAKE_TEST_RELEASE_SIGNALS",
            "label": "Make Test",
            "adapter": "wp_rest_posts",
            "authoritativeSource": "https://make.wordpress.org/test/",
            "urls": ["https://example.test/posts"],
            "completeness": "PARTIAL",
            "scope": "fixture scope",
            "outcomeObservers": ["post revision"],
        }

        def fetcher(url):
            return body, {"content-type": "application/json", "etag": '"fixture"'}, 200

        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temporary:
            snapshot = collect_source(
                config,
                observed_at="2026-10-06T12:00:00Z",
                fetcher=fetcher,
                raw_root=Path(temporary),
            )
            result = verify_snapshot(snapshot)
            tampered = json.loads(json.dumps(snapshot))
            tampered["limitations"].append("Unbound limitation.")
            tampered_result = verify_snapshot(tampered)
        self.assertEqual(result["status"], "certified")
        self.assertEqual(tampered_result["status"], "failed")
        self.assertIn("snapshot canonical hash mismatch", tampered_result["errors"])
        self.assertEqual(snapshot["resources"][0]["nativeIdentity"], "wordpress_make_post/10")
        self.assertRegex(snapshot["rawAcquisitions"][0]["rawSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {item["familyId"] for item in snapshot["resources"][0]["candidateSignals"]},
            {"BETA_RC_TEST", "GUTENBERG_TEST"},
        )

    def test_make_post_without_explicit_request_does_not_become_candidate(self):
        resource = normalize_wp_item({
            "id": 11,
            "link": "https://make.wordpress.org/accessibility/meeting-notes/",
            "slug": "meeting-notes",
            "date_gmt": "2026-10-01T00:00:00",
            "modified_gmt": "2026-10-01T00:00:00",
            "title": {"rendered": "Accessibility team meeting notes"},
            "content": {"rendered": "<p>Routine meeting notes.</p>"},
            "tags": [],
        }, "ACCESSIBILITY_REQUESTS", "WORDPRESS_MAKE_POST")
        self.assertEqual(resource["candidateSignals"], [])

    def test_documentation_issue_requires_unassigned_open_request(self):
        base = {
            "node_id": "I_fixture",
            "number": 42,
            "html_url": "https://github.com/WordPress/Documentation-Issue-Tracker/issues/42",
            "title": "Correct developer handbook example",
            "body": "The example is outdated.",
            "state": "open",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-02T00:00:00Z",
            "labels": [],
            "assignees": [],
            "repository_url": "https://api.github.com/repos/WordPress/Documentation-Issue-Tracker",
        }
        devhub = {**base, "title": "[DevHub] Correct developer handbook example"}
        unassigned = normalize_github_item(devhub, "CORE_DEVELOPER_DOCS", "2026-10-06T00:00:00Z")
        assigned = normalize_github_item({**devhub, "node_id": "I_assigned", "assignees": [{"login": "owner"}]}, "CORE_DEVELOPER_DOCS", "2026-10-06T00:00:00Z")
        self.assertEqual(unassigned["candidateSignals"][0]["familyId"], "DOCS_REVIEW")
        self.assertEqual(assigned["candidateSignals"], [])

    def test_release_source_observes_nightly_without_manufacturing_candidate(self):
        nightly = normalize_release_offer({
            "current": "7.2-alpha-64115",
            "version": "7.2-alpha-64115",
            "locale": "en_US",
            "response": "development",
            "download": "https://wordpress.org/nightly-builds/wordpress-latest.zip",
        }, "development")
        beta = normalize_release_offer({
            "current": "7.2-beta1",
            "version": "7.2-beta1",
            "locale": "en_US",
            "response": "upgrade",
            "download": "https://downloads.wordpress.org/release/wordpress-7.2-beta1.zip",
        }, "beta")
        self.assertEqual(nightly["candidateSignals"], [])
        self.assertEqual(beta["candidateSignals"][0]["familyId"], "BETA_RC_TEST")


if __name__ == "__main__":
    unittest.main()
