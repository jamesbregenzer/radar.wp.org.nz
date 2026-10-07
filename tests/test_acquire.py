from __future__ import annotations
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acquire import acquire_core_trac, acquire_run, new_csv_file, snapshot_downloads

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

    def test_partial_failure_keeps_successful_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = {"id": "bad", "csvUrl": "https://bad", "expectedFields": ["id"]}
            good = {"id": "good", "csvUrl": "https://good", "expectedFields": ["id"]}
            def acquirer(item, run_dir, observed, downloads, timeout):
                return {"schema": "radar-observation.v2", "version": 2, "sourceId": item["id"], "sourceFamily": "CORE_TRAC", "sourceRole": "DIRECT_OPPORTUNITY", "candidateFamilyMappings": [], "identityField": "id", "observedAt": observed, "acquisitionResult": "success", "rows": [{"id": "1"}]} if item["id"] == "good" else {"schema": "radar-observation.v2", "version": 2, "sourceId": "bad", "sourceFamily": "CORE_TRAC", "sourceRole": "DIRECT_OPPORTUNITY", "candidateFamilyMappings": [], "identityField": "id", "observedAt": observed, "acquisitionResult": "failed", "rows": [], "error": "network"}
            manifest = acquire_run(raw_root=Path(temporary), observed_at="2026-10-07T12:00:00Z", trac_sources=[source, good], wave2_sources=[], trac_acquirer=acquirer)
            self.assertTrue(manifest["success"])

if __name__ == "__main__": unittest.main()
