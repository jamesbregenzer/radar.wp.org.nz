from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from acquire import acquire_core_trac, acquire_run, acquire_wave2, new_csv_file, primary_core_trac_sources, validate_csv, wait_for_new_csv


FIELDS = ["id", "summary", "status"]


def source(source_id: str, url: str = "https://core.trac.wordpress.org/report/15?format=csv") -> dict[str, object]:
    return {"id": source_id, "csvUrl": url, "sourceRole": "DIRECT_OPPORTUNITY", "expectedFields": FIELDS}


class AcquireTests(unittest.TestCase):
    def test_registry_iteration_excludes_legacy_v1_sources(self):
        sources = primary_core_trac_sources()
        self.assertTrue(sources)
        self.assertTrue(all(item["sourceRole"] != "LEGACY_V1_COMPATIBILITY" for item in sources))

    def test_detects_query_and_report_download_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary)
            unrelated = downloads / "notes.csv"
            unrelated.write_text("not a Trac download")
            before = {unrelated: (unrelated.stat().st_size, unrelated.stat().st_mtime_ns)}
            query = downloads / "query.csv"
            query.write_text("id,summary,status\n1,Query,new\n")
            self.assertEqual(new_csv_file(before, downloads), query)
            before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in downloads.iterdir()}
            report = downloads / "report_16.csv"
            report.write_text("id,summary,status\n16,Report,new\n")
            self.assertEqual(new_csv_file(before, downloads), report)

    def test_detects_firefox_duplicate_download_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary)
            existing = downloads / "query.csv"
            existing.write_text("old")
            before = {existing: (existing.stat().st_size, existing.stat().st_mtime_ns)}
            duplicate = downloads / "query (1).csv"
            duplicate.write_text("id,summary,status\n1,New,new\n")
            self.assertEqual(new_csv_file(before, downloads), duplicate)

    def test_incomplete_download_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary)
            candidate = downloads / "report_15.csv"
            candidate.write_text("id,summary,status\n15,Partial,new\n")
            (downloads / "report_15.csv.part").write_text("still downloading")
            with self.assertRaises(TimeoutError):
                wait_for_new_csv(downloads, {}, timeout=0)

    def test_ignores_unrelated_download_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary)
            unrelated = downloads / "report-not-a-trac-file.csv"
            unrelated.write_text("id,summary,status\n1,Nope,new\n")
            self.assertIsNone(new_csv_file({}, downloads))

    def test_core_trac_acquisition_copies_csv_and_writes_metadata_without_deleting_downloads(self):
        body = b"id,summary,status\n15,Report,new\n"
        with tempfile.TemporaryDirectory() as temporary:
            downloads = Path(temporary) / "Downloads"
            run_dir = Path(temporary) / "raw"
            downloads.mkdir()
            unrelated = downloads / "keep.csv"
            unrelated.write_text("unrelated")
            downloaded = downloads / "report_15.csv"

            def opener(url):
                self.assertEqual(url, "https://core.trac.wordpress.org/report/15?format=csv")
                downloaded.write_bytes(body)

            def waiter(path, before, timeout):
                self.assertNotIn(downloaded, before)
                return downloaded

            record = acquire_core_trac(source("core-trac-report-15"), run_dir, "2026-10-07T12:00:00Z", downloads, 1, opener=opener, waiter=waiter, closer=lambda: None)
            self.assertEqual(record["rowCount"], 1)
            self.assertEqual(record["artifactSha256"], hashlib.sha256(body).hexdigest())
            self.assertTrue((run_dir / "core-trac-report-15.csv").exists())
            self.assertTrue((run_dir / "core-trac-report-15.json").exists())
            self.assertTrue(unrelated.exists())

    def test_malformed_and_empty_csv_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_csv(b"", FIELDS)
        with self.assertRaises(ValueError):
            validate_csv(b"id,summary\n1,Missing status\n", FIELDS)
        with self.assertRaises(ValueError):
            validate_csv(b"id,summary,status\n1,Too,many,fields\n", FIELDS)
        with self.assertRaises(ValueError):
            validate_csv(b"id,summary,status\n,Missing id,new\n", FIELDS)

    def test_firefox_cleanup_runs_when_open_fails(self):
        closed = []

        def opener(url):
            raise RuntimeError("Firefox unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                acquire_core_trac(source("broken"), Path(temporary), "2026-10-07T12:00:00Z", Path(temporary), 1, opener=opener, closer=lambda: closed.append(True))
        self.assertEqual(closed, [True])

    def test_wave2_rejects_http_200_non_json_before_reporting_success(self):
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts"}

        def fetcher(_config):
            return [("https://example.test/posts", b"<html>error</html>", {}, 200)]

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                acquire_wave2(config, Path(temporary), "2026-10-07T12:00:00Z", fetcher=fetcher)

    def test_wave2_rejects_json_error_objects_with_http_200(self):
        config = {"sourceFamily": "MAKE_TEST_RELEASE_SIGNALS", "adapter": "wp_rest_posts"}

        def fetcher(_config):
            return [("https://example.test/posts", b'[{"error":"upstream failure"}]', {}, 200)]

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                acquire_wave2(config, Path(temporary), "2026-10-07T12:00:00Z", fetcher=fetcher)

    def test_one_source_failure_does_not_stop_remaining_sources(self):
        body = b"id,summary,status\n1,Good,new\n"

        def trac_acquirer(item, run_dir, observed, downloads, timeout):
            if item["id"] == "bad":
                raise RuntimeError("Firefox failed")
            artifact = run_dir / f"{item['id']}.csv"
            artifact.write_bytes(body)
            return {"sourceId": item["id"], "exactUrl": item["csvUrl"], "observedAt": observed, "success": True, "artifact": artifact.name}

        with tempfile.TemporaryDirectory() as temporary:
            manifest = acquire_run(
                raw_root=Path(temporary),
                observed_at="2026-10-07T12:00:00Z",
                trac_sources=[source("bad"), source("good")],
                wave2_sources=[],
                trac_acquirer=trac_acquirer,
            )
            self.assertFalse(manifest["success"])
            self.assertEqual([item["success"] for item in manifest["results"]], [False, True])
            self.assertTrue((Path(temporary) / "2026-10-07T12-00-00Z" / "good.csv").exists())

    def test_raw_hash_and_row_count_are_recorded(self):
        body = b"id,summary,status\n1,Good,new\n2,Also good,assigned\n"

        def trac_acquirer(item, run_dir, observed, downloads, timeout):
            artifact = run_dir / "source.csv"
            artifact.write_bytes(body)
            record = {"sourceId": item["id"], "exactUrl": item["csvUrl"], "observedAt": observed, "success": True, "artifact": artifact.name, "artifactSha256": hashlib.sha256(body).hexdigest(), "rowCount": 2}
            (run_dir / "source.json").write_text(json.dumps(record))
            return record

        with tempfile.TemporaryDirectory() as temporary:
            manifest = acquire_run(raw_root=Path(temporary), observed_at="2026-10-07T12:00:00Z", trac_sources=[source("good")], wave2_sources=[], trac_acquirer=trac_acquirer)
            self.assertTrue(manifest["success"])
            result = manifest["results"][0]
            self.assertEqual(result["rowCount"], 2)
            self.assertEqual(result["artifactSha256"], hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
