from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acquire import rows_for_observation, validate_csv
from description_lookup import DescriptionLookupError, lookup_candidate_description, lookup_description

SOURCE_ID = "core-trac-report-18-release-blockers"
TICKET_ID = 65415


class DescriptionLookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.raw_root = Path(self.temporary.name) / "data/raw"

    def archive(self, observed_at, body, *, rows=None):
        run_id = observed_at.replace(":", "-")
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        raw = run_dir / f"{SOURCE_ID}.csv"
        raw.write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        parsed_count, parsed_rows = validate_csv(body, ["id", "summary", "status"])
        observation = {
            "sourceId": SOURCE_ID, "sourceFamily": "CORE_TRAC",
            "observedAt": observed_at, "acquisitionResult": "success",
            "sourceRevision": sha,
            "rows": rows_for_observation(parsed_rows) if rows is None else rows,
            "rawArtifacts": [{"path": f"data/raw/{run_id}/{SOURCE_ID}.csv",
                              "sha256": sha, "byteLength": len(body),
                              "contentType": "text/csv", "rowCount": parsed_count}],
        }
        run = {"schema": "radar-observation-set.v2", "runId": run_id,
               "observedAt": observed_at, "success": True,
               "observations": [observation]}
        (run_dir / "run.json").write_text(json.dumps(run))
        return sha, run, raw

    def read(self, observed_at, revision):
        return lookup_description(source_id=SOURCE_ID, source_revision=revision,
                                  ticket_id=TICKET_ID, observed_at=observed_at,
                                  raw_root=self.raw_root)

    def feed(self, memberships, *, ticket=TICKET_ID):
        feed = {"schema": "radar-candidate-feed.v2", "feedRevision": "pinned",
                "candidates": [{"candidateId": "candidate:test", "opportunityId": f"opportunity:core-trac:{ticket}",
                                "resource": {"resourceType": "CORE_TRAC_TICKET", "identity": str(ticket),
                                             "id": f"core-trac:{ticket}"},
                                "sourceMemberships": memberships}]}
        path = Path(self.temporary.name) / "feed.json"
        body = json.dumps(feed).encode()
        path.write_bytes(body)
        return path, hashlib.sha256(body).hexdigest(), feed

    def membership(self, time, sha, row, *, freshness="fresh"):
        return {"sourceId": SOURCE_ID, "sourceFamily": "CORE_TRAC", "sourceRevision": sha,
                "observedAt": time, "freshness": freshness, "evidence": row}

    def candidate_read(self, path, sha):
        return lookup_candidate_description(feed_path=path, feed_sha256=sha,
                                            candidate_id="candidate:test", source_id=SOURCE_ID,
                                            raw_root=self.raw_root)

    def test_pinned_feed_selects_fresh_and_stale_exact_rows(self):
        old, new = "2026-10-31T11:23:46Z", "2026-10-31T17:26:03Z"
        old_sha, old_run, _ = self.archive(old, b'id,summary,status,_description\n65415,Old,new,"Old\nbody"\n')
        new_sha, new_run, _ = self.archive(new, b'id,summary,status,_description\n65415,New,new,"New\nbody"\n')
        for time, sha, run, freshness, expected in [
            (old, old_sha, old_run, "stale", "Old\nbody"),
            (new, new_sha, new_run, "fresh", "New\nbody"),
        ]:
            path, feed_sha, _ = self.feed([self.membership(time, sha, run["observations"][0]["rows"][0], freshness=freshness)])
            result = self.candidate_read(path, feed_sha)
            self.assertEqual(result["description"], expected)
            self.assertEqual(result["feedSha256"], feed_sha)
            self.assertEqual(result["membershipFreshness"], freshness)
            self.assertFalse(result["contextComplete"])

    def test_feed_hash_membership_and_delivered_row_must_match(self):
        time = "2026-10-31T17:26:03Z"
        sha, run, _ = self.archive(time, b'id,summary,status,_description\n65415,Real,new,Body\n')
        member = self.membership(time, sha, run["observations"][0]["rows"][0])
        path, feed_sha, feed = self.feed([member])
        with self.assertRaisesRegex(DescriptionLookupError, "description_feed_hash_mismatch"):
            self.candidate_read(path, "a" * 64)
        member["evidence"] = {**member["evidence"], "summary": "Different"}
        path, feed_sha, _ = self.feed([member])
        with self.assertRaisesRegex(DescriptionLookupError, "description_membership_row_mismatch"):
            self.candidate_read(path, feed_sha)
        member["evidence"] = run["observations"][0]["rows"][0]
        path, feed_sha, _ = self.feed([member, member])
        with self.assertRaisesRegex(DescriptionLookupError, "description_membership_missing_or_ambiguous"):
            self.candidate_read(path, feed_sha)
        path, feed_sha, _ = self.feed([])
        with self.assertRaisesRegex(DescriptionLookupError, "description_membership_missing_or_ambiguous"):
            self.candidate_read(path, feed_sha)

    def test_fresh_and_stale_memberships_select_their_own_archives(self):
        prior_time = "2026-10-31T11:23:46Z"
        current_time = "2026-10-31T17:26:03Z"
        prior_body = b'id,summary,status,_description\r\n65415,Issue,new,"Earlier\r\nbody"\r\n'
        current_body = b'id,summary,status,description\r\n65415,Issue,new,"Current\nbody"\r\n'
        prior_sha, _, _ = self.archive(prior_time, prior_body)
        current_sha, _, _ = self.archive(current_time, current_body)
        prior = self.read(prior_time, prior_sha)
        current = self.read(current_time, current_sha)
        self.assertEqual(prior["description"], "Earlier\r\nbody")
        self.assertEqual(current["description"], "Current\nbody")
        self.assertEqual(prior["sourceRevision"], prior_sha)
        self.assertEqual(current["sourceRevision"], current_sha)
        self.assertEqual(prior["descriptionByteLength"], len("Earlier\r\nbody".encode()))
        self.assertEqual(prior["descriptionSha256"], hashlib.sha256(b"Earlier\r\nbody").hexdigest())
        self.assertFalse(prior["discussionAvailable"])
        self.assertFalse(prior["contextComplete"])
        with self.assertRaisesRegex(DescriptionLookupError, "description_revision_mismatch"):
            self.read(prior_time, current_sha)

    def test_changed_raw_bytes_and_normalized_rows_refuse(self):
        time = "2026-10-31T17:26:03Z"
        sha, run, raw = self.archive(time, b'id,summary,status,_description\n65415,Issue,new,Original\n')
        raw.write_bytes(raw.read_bytes().replace(b"Original", b"Changed!"))
        with self.assertRaisesRegex(DescriptionLookupError, "description_raw_hash_mismatch"):
            self.read(time, sha)
        raw.write_bytes(b'id,summary,status,_description\n65415,Issue,new,Original\n')
        run["observations"][0]["rows"][0]["summary"] = "tampered"
        (self.raw_root / time.replace(":", "-") / "run.json").write_text(json.dumps(run))
        with self.assertRaisesRegex(DescriptionLookupError, "description_rows_mismatch"):
            self.read(time, sha)

    def test_missing_duplicate_and_absent_description_refuse(self):
        time = "2026-10-31T17:26:03Z"
        sha, _, _ = self.archive(time, b'id,summary,status,_description\n123,Issue,new,Other\n')
        with self.assertRaisesRegex(DescriptionLookupError, "description_ticket_missing_or_ambiguous"):
            self.read(time, sha)
        duplicate = (b'id,summary,status,_description\n'
                     b'65415,Issue,new,First\n65415,Issue,new,Second\n')
        sha, _, _ = self.archive(time, duplicate)
        with self.assertRaisesRegex(DescriptionLookupError, "description_ticket_missing_or_ambiguous"):
            self.read(time, sha)
        sha, _, _ = self.archive(time, b'id,summary,status\n65415,Issue,new\n')
        with self.assertRaisesRegex(DescriptionLookupError, "description_missing"):
            self.read(time, sha)

    def test_conflicting_aliases_refuse_without_guessing(self):
        time = "2026-10-31T17:26:03Z"
        body = b'id,summary,status,description,_description\n65415,Issue,new,One,Two\n'
        run_id = time.replace(":", "-")
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / f"{SOURCE_ID}.csv").write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        (run_dir / "run.json").write_text(json.dumps({
            "schema": "radar-observation-set.v2", "runId": run_id, "observedAt": time, "success": True,
            "observations": [{"sourceId": SOURCE_ID, "sourceFamily": "CORE_TRAC",
                              "observedAt": time, "acquisitionResult": "success",
                              "sourceRevision": sha, "rows": [],
                              "rawArtifacts": [{"path": f"data/raw/{run_id}/{SOURCE_ID}.csv",
                                                "sha256": sha, "byteLength": len(body),
                                                "contentType": "text/csv", "rowCount": 1}]}]}))
        with self.assertRaisesRegex(DescriptionLookupError, "description_csv_invalid"):
            self.read(time, sha)

    def test_missing_archive_and_wrong_source_refuse(self):
        with self.assertRaisesRegex(DescriptionLookupError, "description_archive_missing_or_oversized"):
            self.read("2026-10-31T17:26:03Z", "a" * 64)
        with self.assertRaisesRegex(DescriptionLookupError, "description_source_not_approved"):
            lookup_description(source_id="../other", source_revision="a" * 64,
                               ticket_id=TICKET_ID, observed_at="2026-10-31T17:26:03Z",
                               raw_root=self.raw_root)

    def test_cli_returns_exact_pinned_raw_description_and_incomplete_context(self):
        time = "2026-10-31T17:26:03Z"
        fixture = ROOT / "tests/fixtures/raw/v2/release-blockers-20261031.csv"
        sha, run, _ = self.archive(time, fixture.read_bytes())
        path, feed_sha, _ = self.feed([self.membership(time, sha, run["observations"][0]["rows"][0])])
        completed = subprocess.run([
            sys.executable, str(ROOT / "scripts/description_lookup.py"),
            "--feed", str(path), "--feed-sha256", feed_sha,
            "--candidate-id", "candidate:test", "--source-id", SOURCE_ID,
            "--raw-root", str(self.raw_root),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "succeeded")
        self.assertIn("PHPMailer/issues/3342\r\n\r\nBut the gist", result["data"]["description"])
        self.assertFalse(result["data"]["discussionAvailable"])
        self.assertFalse(result["data"]["contextComplete"])


if __name__ == "__main__":
    unittest.main()
