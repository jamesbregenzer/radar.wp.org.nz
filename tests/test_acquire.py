from __future__ import annotations
import tempfile
import json
import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acquire import FIREFOX_EXECUTABLE, FirefoxSession, acquire_core_trac, acquire_run, acquire_wave2, close_firefox, download_is_incomplete, ensure_firefox_profile_available, firefox_command, navigate_firefox, new_csv_file, open_firefox, prepare_firefox_profile, radar_firefox_pids, validate_csv
from process import build_feed

class AcquireTests(unittest.TestCase):
    class FakeProcess:
        def __init__(self, running=True, waits_until_exit=True):
            self.running = running; self.waits_until_exit = waits_until_exit; self.terminated = False; self.killed = False; self.wait_calls = 0
        def poll(self): return None if self.running else 0
        def terminate(self): self.terminated = True; self.running = not self.waits_until_exit
        def kill(self): self.killed = True; self.running = False
        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.running: raise subprocess.TimeoutExpired("firefox", timeout)

    def test_report_46_uses_direct_csv_query(self):
        registry = json.loads((ROOT / "config/core-trac-v2-source-registry.json").read_text())
        source = next(item for item in registry["sources"] if item["id"] == "core-trac-report-46-patches-defects-needing-review")
        self.assertIn("/query?", source["csvUrl"])
        self.assertIn("format=csv", source["csvUrl"])
        self.assertEqual(source["htmlUrl"], "https://core.trac.wordpress.org/report/46")

    def test_firefox_command_uses_executable_and_dedicated_profile(self):
        profile = Path("/Users/thor/Sites/wp-core-radar/data/.firefox-profile")
        self.assertEqual(firefox_command("https://example.test/report?format=csv", profile), [str(FIREFOX_EXECUTABLE), "-no-remote", "-profile", str(profile), "https://example.test/report?format=csv"])
        self.assertNotIn("open", firefox_command("https://example.test/report?format=csv", profile))

    def test_open_firefox_runs_direct_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary) / "downloads"; profile = Path(temporary) / "profile"
            with patch("acquire.subprocess.Popen") as process, patch("acquire.radar_firefox_pids", return_value=[]):
                open_firefox("https://example.test/report?format=csv", downloads=downloads, profile=profile)
            process.assert_called_once_with([str(FIREFOX_EXECUTABLE), "-no-remote", "-profile", str(profile), "https://example.test/report?format=csv"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            prefs = (profile / "user.js").read_text()
            self.assertIn(f'"browser.download.dir", {json.dumps(str(downloads))}', prefs)

    def test_profile_has_crash_recovery_suppression_prefs(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile"
            prepare_firefox_profile(Path(temporary) / "downloads", profile)
            prefs = (profile / "user.js").read_text()
            for pref in ("browser.sessionstore.resume_from_crash", "browser.startup.couldRestoreSession.count", "browser.sessionstore.max_resumed_crashes", "browser.shell.checkDefaultBrowser"):
                self.assertIn(pref, prefs)

    def test_navigation_reuses_profile_without_new_instance_flag(self):
        with patch("acquire.subprocess.run") as run:
            navigate_firefox("https://example.test/next", Path("/tmp/radar-profile"))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [str(FIREFOX_EXECUTABLE), "-profile", "/tmp/radar-profile"])
        self.assertNotIn("-no-remote", command)

    def test_close_firefox_uses_one_graceful_quit_and_waits_for_lock_release(self):
        session = FirefoxSession(self.FakeProcess(), Path("/tmp/radar-profile"))
        with patch("acquire.radar_firefox_pids", side_effect=[[123], [], [], []]), patch("acquire.subprocess.run") as run:
            close_firefox(session)
        self.assertEqual(session.graceful_quit_count, 1)
        self.assertFalse(session.emergency_kill_used)
        self.assertEqual(run.call_count, 1)
        self.assertIn('tell application "Firefox" to quit', run.call_args.args[0][-1])

    def test_one_session_handles_multiple_sources_and_retries_in_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "downloads"; downloads.mkdir()
            session = FirefoxSession(self.FakeProcess(), root / "profile")
            sources = [{"id": "one", "csvUrl": "https://example.test/one", "expectedFields": ["id", "summary", "status"]}, {"id": "two", "csvUrl": "https://example.test/two", "expectedFields": ["id", "summary", "status"]}]
            navigations = []
            waits = iter([downloads / "report_1.csv", TimeoutError("no download"), downloads / "report_2.csv", downloads / "report_3.csv"])
            def waiter(*_):
                value = next(waits)
                if isinstance(value, Exception):
                    raise value
                value.write_text("id,summary,status\n123,Fix it,new\n")
                return value
            for index, source in enumerate(sources):
                record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, session=session, first_in_session=index == 0, navigator=navigations.append, waiter=waiter)
                self.assertEqual(record["acquisitionResult"], "success")
            self.assertEqual(navigations, ["https://example.test/two", "https://example.test/two"])

    def test_stale_profile_lock_is_removed_only_when_unheld(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary); lock = profile / "parent.lock"; lock.write_text("stale")
            with patch("acquire.radar_firefox_pids", return_value=[]):
                ensure_firefox_profile_available(profile, timeout=0)
            self.assertFalse(lock.exists())

    def test_live_held_profile_fails_boundedly_without_lock_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary); lock = profile / "parent.lock"; lock.write_text("held")
            with patch("acquire.radar_firefox_pids", return_value=[12345]), self.assertRaisesRegex(RuntimeError, "12345"):
                ensure_firefox_profile_available(profile, timeout=0)
            self.assertTrue(lock.exists())

    def test_live_held_profile_prevents_launch_without_gui_prompt(self):
        with tempfile.TemporaryDirectory() as temporary, patch("acquire.radar_firefox_pids", return_value=[12345]), patch("acquire.subprocess.Popen") as process:
            with self.assertRaisesRegex(RuntimeError, "12345"):
                open_firefox("https://example.test/report?format=csv", downloads=Path(temporary) / "downloads", profile=Path(temporary) / "profile")
            process.assert_not_called()

    def test_core_trac_writes_canonical_observation_and_keeps_raw_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "core-trac-report", "sourceRole": "DIRECT_OPPORTUNITY", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary"], "candidateFamilyMappings": [{"familyId": "TEST", "confidence": "high"}], "identityField": "id"}; body = b"id,summary\n123,Fix it\n"; (downloads / "report_1.csv").write_bytes(body)
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda _: None, waiter=lambda *_: downloads / "report_1.csv", closer=lambda *_: None)
            self.assertEqual(record["schema"], "radar-observation.v2"); self.assertEqual(record["acquisitionResult"], "success"); self.assertEqual(record["rows"][0]["id"], "123"); self.assertEqual(record["rawArtifacts"][0]["sha256"], __import__("hashlib").sha256(body).hexdigest())
            self.assertFalse((downloads / "report_1.csv").exists())

    def test_core_trac_retries_one_download_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "retry", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}; body = b"id,summary,status\n123,Fix it,new\n"; path = downloads / "report_1.csv"; path.write_bytes(body); waits = iter([TimeoutError("no download"), path]); opens = []; closes = []
            def waiter(*_):
                result = next(waits)
                if isinstance(result, Exception): raise result
                return result
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda url: opens.append(url), waiter=waiter, closer=lambda *_: closes.append(True))
            self.assertEqual(record["acquisitionResult"], "success"); self.assertEqual(len(opens), 2); self.assertEqual(len(closes), 2)

    def test_core_trac_retries_timeout_once_then_fails_without_blocking_next_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); bad = {"id": "bad", "csvUrl": "https://example.test/bad", "expectedFields": ["id", "summary", "status"]}; good = {"id": "good", "csvUrl": "https://example.test/good", "expectedFields": ["id", "summary", "status"]}; path = downloads / "report_1.csv"; path.write_text("id,summary,status\n123,Fix it,new\n"); timeout_waits = {"bad": 0}
            def acquirer(source, run_dir, observed, directory, timeout):
                if source["id"] == "bad":
                    return acquire_core_trac(source, run_dir, observed, directory, timeout, waiter=lambda *_: (_ for _ in ()).throw(TimeoutError("no download")), opener=lambda _: None, closer=lambda *_: None)
                return acquire_core_trac(source, run_dir, observed, directory, timeout, waiter=lambda *_: path, opener=lambda _: None, closer=lambda *_: None)
            manifest = acquire_run(raw_root=root / "raw", observed_at="2026-10-07T12:00:00Z", downloads=downloads, trac_sources=[bad, good], wave2_sources=[], trac_acquirer=acquirer)
            self.assertEqual([item["acquisitionResult"] for item in manifest["observations"]], ["failed", "success"])

    def test_malformed_csv_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "malformed", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}; path = downloads / "report_1.csv"; path.write_text("id,summary\n123,Missing status\n"); opens = []
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda url: opens.append(url), waiter=lambda *_: path, closer=lambda *_: None)
            self.assertEqual(record["acquisitionResult"], "failed"); self.assertEqual(len(opens), 1); self.assertIn("ValueError", record["error"])
            self.assertTrue(path.exists())

    def test_artifact_write_failure_retains_staging_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "write-failure", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}; path = downloads / "report_1.csv"; path.write_text("id,summary,status\n123,Fix it,new\n")
            with patch("acquire.Path.write_bytes", side_effect=OSError("artifact write failed")):
                record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda _: None, waiter=lambda *_: path, closer=lambda *_: None)
            self.assertEqual(record["acquisitionResult"], "failed"); self.assertTrue(path.exists())

    def test_successful_acquisition_leaves_unrelated_downloads_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); unrelated = downloads / "notes.csv"; unrelated.write_text("unrelated\n"); consumed = downloads / "report_1.csv"; consumed.write_text("id,summary,status\n123,Fix it,new\n"); source = {"id": "cleanup", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda _: None, waiter=lambda *_: consumed, closer=lambda *_: None)
            self.assertEqual(record["acquisitionResult"], "success"); self.assertFalse(consumed.exists()); self.assertTrue(unrelated.exists())

    def test_report_names_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary); (downloads / "report_2 (1).csv").write_text("id\n1\n"); (downloads / "notes.txt").write_text("x")
            self.assertEqual(new_csv_file({}, downloads).name, "report_2 (1).csv")
            (downloads / "report_2(2).csv").write_text("id\n2\n")
            self.assertEqual(new_csv_file({}, downloads).name, "report_2(2).csv")

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
        self.assertEqual(rows[0]["workflow"], "has-patch")
        self.assertNotIn("keywords", rows[0])
        self.assertEqual(rows[0]["time"], "2026-07-15T11:35:42Z")
        self.assertEqual(rows[0]["changetime"], "2026-10-01T23:36:28Z")
        self.assertNotIn("comments", rows[0])

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
