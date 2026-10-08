from __future__ import annotations
import tempfile
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acquire import acquire_core_trac, acquire_run, acquire_wave2, download_is_incomplete, new_csv_file, prepare_firefox_profile, validate_csv
from process import build_feed

class AcquireTests(unittest.TestCase):
    def test_core_trac_writes_canonical_observation_and_keeps_raw_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "core-trac-report", "sourceRole": "DIRECT_OPPORTUNITY", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary"], "candidateFamilyMappings": [{"familyId": "TEST", "confidence": "high"}], "identityField": "id"}; body = b"id,summary\n123,Fix it\n"; (downloads / "report_1.csv").write_bytes(body)
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda _: None, waiter=lambda *_: downloads / "report_1.csv", closer=lambda: None)
            self.assertEqual(record["schema"], "radar-observation.v2"); self.assertEqual(record["acquisitionResult"], "success"); self.assertEqual(record["rows"][0]["id"], "123"); self.assertEqual(record["rawArtifacts"][0]["sha256"], __import__("hashlib").sha256(body).hexdigest())

    def test_report_names_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary); (downloads / "report_2 (1).csv").write_text("id\n1\n"); (downloads / "notes.txt").write_text("x")
            self.assertEqual(new_csv_file({}, downloads).name, "report_2 (1).csv")

    def test_incomplete_downloads_and_missing_ticket_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary); candidate = downloads / "query (1).csv"
            candidate.write_text("id,summary\n,Missing\n")
            (downloads / "query (1).csv.part").write_text("partial")
            self.assertTrue(download_is_incomplete(candidate))
            with self.assertRaises(TimeoutError):
                from acquire import wait_for_new_csv
                wait_for_new_csv(downloads, {}, timeout=0)
            with self.assertRaises(ValueError):
                validate_csv(candidate.read_bytes(), ["id", "summary"])

    def test_observed_report_headers_are_normalized(self):
        body = "__group__,ticket,summary,owner,component,_version,priority,severity,milestone,type,_status,workflow,_created,modified,_description,_reporter\nNext Release,65638,AI support,,AI,,normal,normal,7.2,enhancement,new,has-patch,2026-07-15T11:35:42Z,2026-10-01T23:36:28Z,description,reporter\n".encode()
        count, rows = validate_csv(body, ["id", "summary", "status", "component", "owner", "type", "priority", "milestone", "version", "keywords", "time", "changetime", "comments", "_comments"])
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["id"], "65638")
        self.assertEqual(rows[0]["status"], "new")
        self.assertEqual(rows[0]["keywords"], "has-patch")
        self.assertEqual(rows[0]["time"], "2026-07-15T11:35:42Z")
        self.assertEqual(rows[0]["changetime"], "2026-10-01T23:36:28Z")
        self.assertEqual(rows[0]["comments"], "")

    def test_observed_custom_query_headers_are_normalized(self):
        body = b"\xef\xbb\xbfid,Summary,Status,Keywords,Owner,Type,Priority\n123,Fix it,new,needs-testing,,defect (bug),normal\n"
        count, rows = validate_csv(body, ["id", "summary", "status", "keywords"])
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["id"], "123")
        self.assertEqual(rows[0]["summary"], "Fix it")
        self.assertEqual(rows[0]["keywords"], "needs-testing")

    def test_missing_required_semantic_header_still_fails(self):
        with self.assertRaisesRegex(ValueError, "status"):
            validate_csv(b"ticket,summary,workflow\n123,Fix it,needs-testing\n", ["id", "summary", "status", "keywords"])

    def test_firefox_profile_is_configured_for_radar_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary) / "downloads"
            profile = Path(temporary) / "profile"
            prepare_firefox_profile(downloads, profile)
            prefs = (profile / "user.js").read_text()
            self.assertIn(f'"browser.download.dir", {json.dumps(str(downloads))}', prefs)
            self.assertIn('"browser.download.folderList", 2', prefs)
            self.assertIn('"browser.helperApps.neverAsk.saveToDisk", "text/csv', prefs)

    def test_wave2_shape_validation_happens_before_successful_observation(self):
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts"}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                acquire_wave2(config, Path(temporary), "2026-10-07T12:00:00Z", fetcher=lambda _: [("https://example.test", b"{\"error\":\"upstream\"}", {}, 200)])

    def test_wave2_opportunity_states_survive_into_processing(self):
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts", "authoritativeSource": "https://make.wordpress.org/test/"}
        body = json.dumps([{ "id": 10, "link": "https://make.wordpress.org/test/post", "slug": "call-for-testing", "date_gmt": "2026-10-01T00:00:00", "modified_gmt": "2026-10-02T00:00:00", "title": {"rendered": "Call for testing: WordPress 7.2 Beta 1"}, "content": {"rendered": '<p>Test this beta. <a href="https://github.com/WordPress/gutenberg/issues/1">Gutenberg</a></p>'}, "tags": [] }]).encode()
        with tempfile.TemporaryDirectory() as temporary:
            observation = acquire_wave2(config, Path(temporary), "2026-10-06T12:00:00Z", fetcher=lambda _: [("https://example.test", body, {}, 200)])
        self.assertEqual(observation["acquisitionResult"], "success")
        self.assertEqual(observation["rows"][0]["candidateFamilyMappings"][0]["familyId"], "BETA_RC_TEST")
        self.assertEqual(build_feed({"observations": [observation]})["candidateCount"], 1)

    def test_no_clear_contribution_does_not_map_to_candidate(self):
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts"}
        body = json.dumps([{ "id": 11, "link": "https://make.wordpress.org/test/post", "slug": "routine-update", "date_gmt": "2026-10-01T00:00:00", "modified_gmt": "2026-10-02T00:00:00", "title": {"rendered": "Routine update"}, "content": {"rendered": "<p>No clear contribution request.</p>"}, "tags": [] }]).encode()
        with tempfile.TemporaryDirectory() as temporary:
            observation = acquire_wave2(config, Path(temporary), "2026-10-06T12:00:00Z", fetcher=lambda _: [("https://example.test", body, {}, 200)])
        self.assertEqual(observation["rows"][0]["candidateFamilyMappings"], [])
        self.assertEqual(build_feed({"observations": [observation]})["candidateCount"], 0)

    def test_partial_failure_keeps_successful_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = {"id": "bad", "csvUrl": "https://bad", "expectedFields": ["id"]}
            good = {"id": "good", "csvUrl": "https://good", "expectedFields": ["id"]}
            def acquirer(item, run_dir, observed, downloads, timeout):
                return {"schema": "radar-observation.v2", "version": 2, "sourceId": item["id"], "sourceFamily": "CORE_TRAC", "sourceRole": "DIRECT_OPPORTUNITY", "candidateFamilyMappings": [], "identityField": "id", "observedAt": observed, "acquisitionResult": "success", "rows": [{"id": "1"}]} if item["id"] == "good" else {"schema": "radar-observation.v2", "version": 2, "sourceId": "bad", "sourceFamily": "CORE_TRAC", "sourceRole": "DIRECT_OPPORTUNITY", "candidateFamilyMappings": [], "identityField": "id", "observedAt": observed, "acquisitionResult": "failed", "rows": [], "error": "network"}
            manifest = acquire_run(raw_root=Path(temporary), observed_at="2026-10-07T12:00:00Z", trac_sources=[source, good], wave2_sources=[], trac_acquirer=acquirer)
            self.assertTrue(manifest["success"])

if __name__ == "__main__": unittest.main()
