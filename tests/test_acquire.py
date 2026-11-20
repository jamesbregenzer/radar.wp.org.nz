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
from acquire import FIREFOX_EXECUTABLE, FirefoxSession, acquire_core_trac, acquire_run, acquire_wave2, close_firefox, download_is_incomplete, ensure_firefox_profile_available, fetch_wave2_source, firefox_command, navigate_firefox, new_csv_file, open_firefox, prepare_firefox_profile, radar_firefox_pids, validate_csv
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

    def test_first_download_baseline_is_captured_before_firefox_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            downloads.mkdir()
            source = {"id": "first-report", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/report", "expectedFields": ["id", "summary", "status"]}

            def opener(_url, *, downloads):
                (downloads / "report_12.csv").write_text("id,summary,status\n12,Example,new\n", encoding="utf-8")
                return FirefoxSession(self.FakeProcess(), root / "profile")

            def waiter(directory, before, _timeout):
                path = new_csv_file(before, directory)
                if path is None:
                    raise TimeoutError("no new download")
                return path

            with patch("acquire.open_firefox", side_effect=opener), patch("acquire.close_firefox"), patch("acquire.navigate_firefox"):
                manifest = acquire_run(
                    raw_root=root / "raw",
                    observed_at="2026-10-07T12:00:00Z",
                    downloads=downloads,
                    timeout=1,
                    trac_sources=[source],
                    wave2_sources=[],
                    trac_acquirer=acquire_core_trac,
                )
            self.assertTrue(manifest["observations"][0]["acquisitionResult"] == "success")
            self.assertEqual(manifest["observations"][0]["rows"][0]["id"], "12")

    def test_close_firefox_terminates_only_the_dedicated_profile_processes(self):
        session = FirefoxSession(self.FakeProcess(), Path("/tmp/radar-profile"))
        with patch("acquire.radar_firefox_pids", side_effect=[[123], [], [], []]), patch("acquire.os.kill") as kill, patch("acquire.subprocess.run") as run:
            close_firefox(session)
        self.assertEqual(session.graceful_quit_count, 1)
        self.assertFalse(session.emergency_kill_used)
        kill.assert_called_once_with(123, __import__("signal").SIGTERM)
        run.assert_not_called()

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
            def navigate(url, *, timeout):
                navigations.append((url, timeout))
            for index, source in enumerate(sources):
                record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, session=session, first_in_session=index == 0, navigator=navigate, waiter=waiter)
                self.assertEqual(record["acquisitionResult"], "success")
            self.assertEqual([item[0] for item in navigations], ["https://example.test/two", "https://example.test/two"])
            self.assertTrue(all(item[1] > 0 for item in navigations))

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

    def test_profile_process_inspection_error_fails_closed(self):
        result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "permission denied"})()
        with patch("acquire.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "cannot verify processes"):
                radar_firefox_pids(Path("/tmp/radar-profile"))

    def test_profile_process_matching_uses_exact_profile_argument(self):
        result = type("Result", (), {
            "returncode": 0,
            "stdout": (
                f"101 {FIREFOX_EXECUTABLE} -no-remote -profile /tmp/radar-profile https://example.test/one\n"
                f"202 {FIREFOX_EXECUTABLE} -no-remote -profile /tmp/radar-profile-extra https://example.test/two\n"
            ),
        })()
        with patch("acquire.subprocess.run", return_value=result):
            self.assertEqual(radar_firefox_pids(Path("/tmp/radar-profile")), [101])

    def test_core_trac_writes_canonical_observation_and_keeps_raw_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "core-trac-report", "sourceRole": "DIRECT_OPPORTUNITY", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary"], "candidateFamilyMappings": [{"familyId": "TEST", "confidence": "high"}], "identityField": "id"}; body = b"id,summary\n123,Fix it\n"; (downloads / "report_1.csv").write_bytes(body)
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda _: None, waiter=lambda *_: downloads / "report_1.csv", closer=lambda *_: None)
            self.assertEqual(record["schema"], "radar-observation.v2"); self.assertEqual(record["acquisitionResult"], "success"); self.assertEqual(record["rows"][0]["id"], "123"); self.assertEqual(record["rawArtifacts"][0]["sha256"], __import__("hashlib").sha256(body).hexdigest())
            self.assertFalse((downloads / "report_1.csv").exists())

    def test_core_trac_keeps_multiline_description_only_in_raw_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir()
            source = {"id": "core-trac-report", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}
            body = b'id,summary,status,_description\r\n123,Fix it,new,"First\r\nsecond"\r\n'
            path = downloads / "report.csv"; path.write_bytes(body)
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1,
                                       opener=lambda _: None, waiter=lambda *_: path, closer=lambda *_: None)
            self.assertEqual(record["rows"], [{"id": "123", "summary": "Fix it", "status": "new"}])
            self.assertEqual((root / "run/core-trac-report.csv").read_bytes(), body)

    def test_core_trac_retries_one_download_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); source = {"id": "retry", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}; body = b"id,summary,status\n123,Fix it,new\n"; path = downloads / "report_1.csv"; path.write_bytes(body); waits = iter([TimeoutError("no download"), path]); opens = []; closes = []
            def waiter(*_):
                result = next(waits)
                if isinstance(result, Exception): raise result
                return result
            record = acquire_core_trac(source, root / "run", "2026-10-07T12:00:00Z", downloads, 1, opener=lambda url: opens.append(url), waiter=waiter, closer=lambda *_: closes.append(True))
            self.assertEqual(record["acquisitionResult"], "success"); self.assertEqual(len(opens), 2); self.assertEqual(len(closes), 2)

    def test_core_source_deadline_bounds_each_retry_deterministically(self):
        class Clock:
            value = 0.0
            def __call__(self): return self.value
            def sleep(self, duration): self.value += duration

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir()
            source = {"id": "bounded", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}
            clock = Clock(); wait_timeouts = []; path = downloads / "report_1.csv"
            def waiter(_directory, _before, timeout):
                wait_timeouts.append(timeout)
                if len(wait_timeouts) == 1:
                    clock.value += timeout
                    raise TimeoutError("first bounded attempt timed out")
                path.write_text("id,summary,status\n123,Fix it,new\n", encoding="utf-8")
                return path
            result = acquire_core_trac(
                source, root / "run", "2026-10-07T12:00:00Z", downloads, 10,
                opener=lambda _url: None, waiter=waiter, closer=lambda _process: None,
                deadline=3.0, source_started_at=0.0, clock=clock, sleep=clock.sleep,
            )
            self.assertEqual(result["acquisitionResult"], "success")
            self.assertEqual(len(wait_timeouts), 2)
            self.assertAlmostEqual(wait_timeouts[0], 1.5)
            self.assertGreater(wait_timeouts[1], 0)
            self.assertLessEqual(clock(), 3.0)

    def test_source_diagnostics_record_actual_deadline_overrun(self):
        class Clock:
            value = 0.0
            def __call__(self): return self.value
            def sleep(self, duration): self.value += duration

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir()
            source = {"id": "overrun", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}
            clock = Clock(); wait_timeouts = []
            def waiter(_directory, _before, timeout):
                wait_timeouts.append(timeout)
                clock.value += timeout + (0.25 if len(wait_timeouts) == 1 else 0.1)
                raise TimeoutError("mocked wait crossed its deadline")
            result = acquire_core_trac(
                source, root / "run", "2026-10-07T12:00:00Z", downloads, 1,
                opener=lambda _url: None, waiter=waiter, closer=lambda _process: None,
                clock=clock, sleep=clock.sleep,
            )
            diagnostics = result["acquisitionDiagnostics"]
            self.assertEqual(result["acquisitionResult"], "failed")
            self.assertEqual(diagnostics["attemptsUsed"], 2)
            self.assertAlmostEqual(diagnostics["sourceElapsedSeconds"], 1.1)
            self.assertGreater(diagnostics["sourceElapsedSeconds"], diagnostics["sourceBudgetSeconds"])

    def test_zero_source_budget_begins_no_attempt(self):
        class Clock:
            def __call__(self): return 0.0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir()
            source = {"id": "zero-budget", "csvUrl": "https://example.test/query", "expectedFields": ["id", "summary", "status"]}
            opened = []
            result = acquire_core_trac(
                source, root / "run", "2026-10-07T12:00:00Z", downloads, 0,
                opener=lambda url: opened.append(url), closer=lambda _process: None,
                clock=Clock(), sleep=lambda _duration: None,
            )
            diagnostics = result["acquisitionDiagnostics"]
            self.assertEqual(opened, [])
            self.assertEqual(diagnostics["attemptsUsed"], 0)
            self.assertEqual(diagnostics["sourceBudgetSeconds"], 0)
            self.assertEqual(diagnostics["sourceElapsedSeconds"], 0)

    def test_core_trac_retries_timeout_once_then_fails_without_blocking_next_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); downloads = root / "Downloads"; downloads.mkdir(); bad = {"id": "bad", "csvUrl": "https://example.test/bad", "expectedFields": ["id", "summary", "status"]}; good = {"id": "good", "csvUrl": "https://example.test/good", "expectedFields": ["id", "summary", "status"]}; path = downloads / "report_1.csv"; path.write_text("id,summary,status\n123,Fix it,new\n"); timeout_waits = {"bad": 0}
            def acquirer(source, run_dir, observed, directory, timeout):
                if source["id"] == "bad":
                    return acquire_core_trac(source, run_dir, observed, directory, timeout, waiter=lambda *_: (_ for _ in ()).throw(TimeoutError("no download")), opener=lambda _: None, closer=lambda *_: None)
                return acquire_core_trac(source, run_dir, observed, directory, timeout, waiter=lambda *_: path, opener=lambda _: None, closer=lambda *_: None)
            manifest = acquire_run(raw_root=root / "raw", observed_at="2026-10-07T12:00:00Z", downloads=downloads, trac_sources=[bad, good], wave2_sources=[], trac_acquirer=acquirer)
            self.assertEqual([item["acquisitionResult"] for item in manifest["observations"]], ["failed", "success"])

    def test_failed_core_download_records_bounded_process_and_file_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            downloads.mkdir()
            (downloads / "query.csv").write_text("id,summary,status\n1,Old,new\n", encoding="utf-8")
            (downloads / "query.csv.part").write_text("partial", encoding="utf-8")
            source = {"id": "timeout", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/query?format=csv", "expectedFields": ["id", "summary", "status"]}
            with patch("acquire.time.sleep"):
                observation = acquire_core_trac(
                    source,
                    root / "run",
                    "2026-10-07T12:00:00Z",
                    downloads,
                    1,
                    opener=lambda _url: self.FakeProcess(),
                    waiter=lambda *_: (_ for _ in ()).throw(TimeoutError("no new CSV")),
                    closer=lambda _process: None,
                )
            self.assertEqual(observation["acquisitionResult"], "failed")
            diagnostics = observation["acquisitionDiagnostics"]
            self.assertEqual({key: diagnostics[key] for key in (
                "matchingCsvCountBefore", "matchingCsvCountAfter", "changedMatchingCsvCount",
                "incompleteMatchingCsvCount", "firefoxLauncherExitCode", "attemptsUsed",
                "failureClass", "humanVerification",
            )}, {
                "matchingCsvCountBefore": 1, "matchingCsvCountAfter": 1,
                "changedMatchingCsvCount": 0, "incompleteMatchingCsvCount": 1,
                "firefoxLauncherExitCode": None, "attemptsUsed": 2,
                "failureClass": "timeout", "humanVerification": "unobserved",
            })
            self.assertAlmostEqual(diagnostics["sourceBudgetSeconds"], 1.0)
            self.assertGreaterEqual(diagnostics["sourceElapsedSeconds"], 0)
            self.assertLessEqual(diagnostics["sourceElapsedSeconds"], 1.0)

    def test_acquire_run_budget_skips_sources_after_deadline(self):
        class Clock:
            value = 0.0
            def __call__(self): return self.value

        with tempfile.TemporaryDirectory() as temporary:
            clock = Clock(); calls = []
            sources = [
                {"id": "first", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/first"},
                {"id": "second", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/second"},
            ]
            def fake_acquirer(source, _run_dir, observed, _downloads, timeout):
                calls.append((source["id"], timeout))
                clock.value += 1.0
                return {"sourceId": source["id"], "sourceFamily": "CORE_TRAC", "observedAt": observed, "acquisitionResult": "success", "rows": [{"id": source["id"]}]}
            manifest = acquire_run(
                raw_root=Path(temporary), observed_at="2026-10-07T12:00:00Z", trac_sources=sources,
                wave2_sources=[], trac_acquirer=fake_acquirer, run_timeout=1.0, clock=clock,
            )
            self.assertEqual([item[0] for item in calls], ["first"])
            self.assertEqual(manifest["observations"][1]["acquisitionResult"], "failed")
            self.assertIn("run deadline exhausted", manifest["observations"][1]["error"])
            self.assertEqual(manifest["sourceCoverage"]["overallState"], "degraded")

    def test_wave2_requests_share_remaining_run_budget(self):
        class Clock:
            value = 0.0
            def __call__(self): return self.value

        clock = Clock(); timeouts = []
        def fetch(_url, *, timeout):
            timeouts.append(timeout)
            clock.value += 3.0
            return b"[]", {}, 200
        config = {"adapter": "github_issues", "urls": ["https://example.test/one", "https://example.test/two", "https://example.test/three"]}
        with patch("wave2_sources.fetch_public", side_effect=fetch), self.assertRaisesRegex(TimeoutError, "deadline exceeded"):
            fetch_wave2_source(config, deadline=5.0, clock=clock)
        self.assertEqual(timeouts, [5.0, 2.0])

    def test_wave2_socket_timeout_retains_45_second_cap(self):
        class Clock:
            value = 0.0
            def __call__(self): return self.value

        clock = Clock(); timeouts = []
        def fetch(_url, *, timeout):
            timeouts.append(timeout)
            clock.value += 5.0
            return b"[]", {}, 200
        config = {"adapter": "github_issues", "urls": ["https://example.test/one", "https://example.test/two"]}
        with patch("wave2_sources.fetch_public", side_effect=fetch):
            fetch_wave2_source(config, deadline=90.0, clock=clock)
        self.assertEqual(timeouts, [45.0, 45.0])

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
        self.assertEqual(rows[0]["description"], "description")
        self.assertNotIn("comments", rows[0])

    def test_multiline_description_preserves_original_csv_line_endings(self):
        description = "First line\r\nSecond line, with comma\nThird line"
        for header in ("_description", "Description"):
            with self.subTest(header=header):
                body = f'id,summary,status,{header}\r\n123,Fix it,new,"{description}"\r\n'.encode("utf-8")
                count, rows = validate_csv(body, ["id", "summary", "status", "description"])
                self.assertEqual(count, 1)
                self.assertEqual(rows[0]["description"], description)
                self.assertNotIn("discussion", rows[0])
                self.assertNotIn("contextComplete", rows[0])

    def test_description_aliases_select_only_unambiguous_body(self):
        for first, second in (("description", "_description"), ("_description", "description")):
            for left, right, expected in (
                ("", "Line one\nLine two", "Line one\nLine two"),
                ("Line one\r\nLine two", "", "Line one\r\nLine two"),
                ("Line one\nLine two", "Line one\nLine two", "Line one\nLine two"),
                ("", "", ""),
            ):
                with self.subTest(first=first, second=second, left=left, right=right):
                    body = f'id,summary,status,{first},{second}\r\n123,Fix it,new,"{left}","{right}"\r\n'.encode("utf-8")
                    _, rows = validate_csv(body, ["id", "summary", "status"])
                    self.assertEqual(rows[0]["description"], expected)

    def test_description_aliases_reject_conflicting_nonempty_bodies(self):
        for first, second in (("description", "_description"), ("_description", "description")):
            for line_ending in ("\n", "\r\n"):
                with self.subTest(first=first, second=second, line_ending=repr(line_ending)):
                    left = f"Line one{line_ending}left"
                    right = f"Line one{line_ending}right"
                    body = f'id,summary,status,{first},{second}\r\n123,Fix it,new,"{left}","{right}"\r\n'.encode("utf-8")
                    with self.assertRaisesRegex(ValueError, "conflicting description columns"):
                        validate_csv(body, ["id", "summary", "status"])

    def test_pinned_release_blocker_csv_keeps_provider_description_bytes(self):
        fixture = ROOT / "tests/fixtures/raw/v2/release-blockers-20261031.csv"
        count, rows = validate_csv(fixture.read_bytes(), ["id", "summary", "status", "description"])
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["id"], "65415")
        self.assertIn("PHPMailer/issues/3342\r\n\r\nBut the gist", rows[0]["description"])
        self.assertTrue(rows[0]["description"].endswith("}}}\r\n"))
        self.assertNotIn("discussion", rows[0])
        self.assertNotIn("contextComplete", rows[0])

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
            coverage = manifest["sourceCoverage"]
            self.assertEqual(coverage["overallState"], "degraded")
            self.assertEqual(coverage["families"]["CORE_TRAC"], {
                "state": "degraded",
                "configuredSourceCount": 2,
                "successfulSourceCount": 1,
                "failedSourceCount": 1,
                "failedSourceIds": ["bad"],
            })
            self.assertEqual(manifest["observations"][1]["rows"], [{"id": "1"}])

    def test_unavailable_core_coverage_keeps_successful_other_families(self):
        with tempfile.TemporaryDirectory() as temporary:
            core_sources = [
                {"id": "core-one", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/one"},
                {"id": "core-two", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/two"},
            ]
            public_source = {"sourceFamily": "PUBLIC_SOURCE"}

            def failed_core(source, _run_dir, observed, _downloads, _timeout):
                return {"sourceId": source["id"], "sourceFamily": "CORE_TRAC", "acquisitionResult": "failed", "rows": [], "observedAt": observed}

            def successful_public(source, _run_dir, observed):
                return {"sourceId": source["sourceFamily"], "sourceFamily": source["sourceFamily"], "acquisitionResult": "success", "rows": [{"id": "retained"}], "observedAt": observed}

            manifest = acquire_run(
                raw_root=Path(temporary),
                observed_at="2026-10-07T12:00:00Z",
                trac_sources=core_sources,
                wave2_sources=[public_source],
                trac_acquirer=failed_core,
                wave2_acquirer=successful_public,
            )
            self.assertTrue(manifest["success"])
            self.assertEqual(manifest["sourceCoverage"]["overallState"], "degraded")
            self.assertEqual(manifest["sourceCoverage"]["families"]["CORE_TRAC"]["state"], "unavailable")
            self.assertEqual(manifest["sourceCoverage"]["families"]["PUBLIC_SOURCE"]["state"], "complete")
            self.assertEqual(manifest["observations"][-1]["rows"], [{"id": "retained"}])

    def test_firefox_startup_failure_marks_core_unavailable_but_keeps_healthy_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            core_sources = [
                {"id": "core-one", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/one"},
                {"id": "core-two", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/two"},
            ]
            public_source = {"sourceFamily": "PUBLIC_SOURCE"}

            def successful_public(source, _run_dir, observed):
                return {"sourceId": source["sourceFamily"], "sourceFamily": source["sourceFamily"], "acquisitionResult": "success", "rows": [{"id": "retained"}], "observedAt": observed}

            with patch("acquire.open_firefox", side_effect=RuntimeError("dedicated profile is held")):
                manifest = acquire_run(
                    raw_root=Path(temporary),
                    observed_at="2026-10-07T12:00:00Z",
                    trac_sources=core_sources,
                    wave2_sources=[public_source],
                    wave2_acquirer=successful_public,
                )
            self.assertTrue(manifest["success"])
            self.assertEqual([item["acquisitionResult"] for item in manifest["observations"]], ["failed", "failed", "success"])
            self.assertEqual(manifest["sourceCoverage"]["families"]["CORE_TRAC"]["state"], "unavailable")
            self.assertEqual(manifest["observations"][-1]["rows"], [{"id": "retained"}])

    def test_all_configured_sources_unavailable_reports_unavailable_overall(self):
        with tempfile.TemporaryDirectory() as temporary:
            sources = [
                {"id": "core-one", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/one"},
                {"id": "core-two", "sourceFamily": "CORE_TRAC", "csvUrl": "https://example.test/two"},
            ]
            with patch("acquire.open_firefox", side_effect=RuntimeError("dedicated profile is held")):
                manifest = acquire_run(
                    raw_root=Path(temporary),
                    observed_at="2026-10-07T12:00:00Z",
                    trac_sources=sources,
                    wave2_sources=[],
                )
            self.assertFalse(manifest["success"])
            self.assertEqual(manifest["sourceCoverage"]["overallState"], "unavailable")

if __name__ == "__main__": unittest.main()
