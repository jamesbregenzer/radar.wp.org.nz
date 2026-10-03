from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("generate_dashboard", ROOT / "scripts" / "generate-dashboard.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_payload(payload: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    path = Path(handle.name)
    handle.close()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


class PublicContributionOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.payload = MODULE.load_public_contribution_payload()
        self.records = {record["ticket_id"]: record for record in self.payload["contributions"]}
        self.record_64670 = self.records["64670"]

    def test_64670_public_contribution_and_confirmation_are_represented(self):
        record = self.record_64670
        self.assertEqual(record["component"], "REST API")
        self.assertEqual(record["contribution_type"], "observation / diagnosis")
        self.assertEqual(record["contribution_link"], "https://core.trac.wordpress.org/ticket/64670#comment:5")
        self.assertIn("parent:0", record["contribution_summary"])

        outcomes = record["outcomes"]
        self.assertEqual(outcomes[0]["type"], "confirmed")
        self.assertIn("PR #10973", outcomes[0]["summary"])
        self.assertTrue(record["outcome_flags"]["confirmed"])

    def test_public_sources_only(self):
        self.assertEqual(self.payload["source_contract"]["private_source_kinds"], [])
        for record in self.payload["contributions"]:
            for source_kind in MODULE.all_public_source_kinds(record):
                self.assertIn(source_kind, MODULE.PUBLIC_CONTRIBUTION_SOURCE_KINDS)
                self.assertIn(source_kind, self.payload["source_contract"]["allowed_source_kinds"])

    def test_existing_63568_public_delivery_is_preserved(self):
        record = self.records["63568"]
        self.assertEqual(record["contribution_type"], "review / verification")
        self.assertEqual(record["contribution_link"], "https://core.trac.wordpress.org/ticket/63568#comment:61")
        self.assertEqual(record["opportunity"]["identity"], "core-trac:63568")

    def test_deterministic_opportunity_linking_is_required(self):
        broken = copy.deepcopy(self.payload)
        broken["contributions"][0]["opportunity"]["identity"] = "github-pr:10973"
        with self.assertRaisesRegex(ValueError, "mismatched opportunity identity"):
            MODULE.load_public_contribution_payload(write_payload(broken))

    def test_unsupported_impact_claims_are_not_invented(self):
        flags = self.record_64670["outcome_flags"]
        self.assertFalse(flags["incorporated"])
        self.assertFalse(flags["merged"])
        self.assertFalse(flags["resolved"])
        self.assertFalse(flags["public_props"])

        broken = copy.deepcopy(self.payload)
        broken["contributions"][0]["outcome_flags"]["merged"] = True
        with self.assertRaisesRegex(ValueError, "claims merge without public merge outcome"):
            MODULE.load_public_contribution_payload(write_payload(broken))

    def test_duplicates_reconcile_to_latest_public_record(self):
        duplicated = copy.deepcopy(self.payload)
        older = copy.deepcopy(duplicated["contributions"][0])
        older["contribution_date"] = "2026-01-01"
        older["contribution_summary"] = "Older duplicate"
        duplicated["contributions"].append(older)

        records = MODULE.public_contribution_records(write_payload(duplicated))
        summaries = [record["contribution_summary"] for record in records]
        self.assertNotIn("Older duplicate", summaries)

    def test_latest_outcome_uses_authoritative_newest_public_event(self):
        record = copy.deepcopy(self.record_64670)
        record["outcomes"].append({
            "type": "confirmed",
            "date": "2026-08-01",
            "label": "Newer public confirmation",
            "summary": "A newer public source supersedes older outcome text.",
            "url": "https://core.trac.wordpress.org/ticket/64670#comment:7",
            "evidence": [{
                "kind": "wordpress_core_trac",
                "url": "https://core.trac.wordpress.org/ticket/64670#comment:7",
                "label": "Core Trac comment #7",
                "supports": "Newer public source."
            }]
        })
        self.assertEqual(MODULE.latest_public_outcome(record)["label"], "Newer public confirmation")

    def test_private_contributor_fields_cannot_enter_public_output(self):
        broken = copy.deepcopy(self.payload)
        broken["contributions"][0]["evidence"].append({
            "kind": "wordpress_core_trac",
            "url": "https://example.test/",
            "label": "Receipt",
            "supports": "Thor queue state"
        })
        with self.assertRaisesRegex(ValueError, "private implementation term"):
            MODULE.load_public_contribution_payload(write_payload(broken))

        html = MODULE.build_contributions_page()
        for term in MODULE.PRIVATE_CONTRIBUTION_TERMS:
            self.assertNotIn(term, html.lower())

    def test_generated_page_links_opportunity_contribution_and_outcome(self):
        html = MODULE.build_contributions_page()
        self.assertIn("WP Core Radar Contributions", html)
        self.assertIn("https://core.trac.wordpress.org/ticket/64670#comment:5", html)
        self.assertIn("https://core.trac.wordpress.org/ticket/64670", html)
        self.assertIn("https://lists.wordpress.org/pipermail/wp-trac/2026-May/564007.html", html)
        self.assertIn("https://github.com/WordPress/wordpress-develop/pull/10973", html)


if __name__ == "__main__":
    unittest.main()
