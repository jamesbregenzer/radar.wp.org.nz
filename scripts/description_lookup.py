#!/usr/bin/env python3
"""Read one exact Core Trac description from a pinned Radar raw CSV archive."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from acquire import ROOT, TRAC_REGISTRY, rows_for_observation, source_slug, validate_csv

SHA256 = re.compile(r"[a-f0-9]{64}\Z")
OBSERVED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
MAX_RUN_BYTES = 40_000_000
MAX_CSV_BYTES = 32_000_000
MAX_FEED_BYTES = 50_000_000
MAX_DESCRIPTION_BYTES = 65_536


class DescriptionLookupError(RuntimeError):
    """A source, archive, or ticket binding could not be proved."""


def fail(code: str) -> None:
    raise DescriptionLookupError(code)


def read_bounded(path: Path, limit: int) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > limit:
            fail("description_archive_missing_or_oversized")
        body = path.read_bytes()
        if len(body) > limit:
            fail("description_archive_missing_or_oversized")
        return body
    except OSError:
        fail("description_archive_missing_or_oversized")


def lookup_description(
    *, source_id: str, source_revision: str, ticket_id: int, observed_at: str,
    raw_root: Path = ROOT / "data/raw", registry_path: Path = TRAC_REGISTRY,
) -> dict[str, Any]:
    """Resolve only the archived observation named by a trusted feed membership."""
    if (type(source_id) is not str or type(source_revision) is not str
            or not SHA256.fullmatch(source_revision) or type(ticket_id) is not int
            or ticket_id < 1 or type(observed_at) is not str
            or not OBSERVED_AT.fullmatch(observed_at)):
        fail("description_binding_invalid")
    try:
        parsed_time = datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%SZ")
        if parsed_time.strftime("%Y-%m-%dT%H:%M:%SZ") != observed_at:
            fail("description_binding_invalid")
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        fail("description_binding_invalid")
    if not isinstance(registry, dict) or not isinstance(registry.get("sources"), list):
        fail("description_binding_invalid")
    approved = [entry for entry in registry["sources"] if isinstance(entry, dict)
                if entry.get("id") == source_id and entry.get("sourceFamily", "CORE_TRAC") == "CORE_TRAC"]
    if len(approved) != 1:
        fail("description_source_not_approved")
    run_id = observed_at.replace(":", "-")
    run_dir = raw_root / run_id
    try:
        run = json.loads(read_bounded(run_dir / "run.json", MAX_RUN_BYTES))
    except (ValueError, UnicodeDecodeError):
        fail("description_archive_invalid")
    if (not isinstance(run, dict) or run.get("schema") != "radar-observation-set.v2"
            or run.get("success") is not True
            or run.get("runId") != run_id or run.get("observedAt") != observed_at):
        fail("description_archive_mismatch")
    if not isinstance(run.get("observations"), list):
        fail("description_archive_invalid")
    observations = [item for item in run["observations"]
                    if isinstance(item, dict) and item.get("sourceId") == source_id]
    if len(observations) != 1:
        fail("description_observation_missing_or_ambiguous")
    observation = observations[0]
    if (observation.get("sourceFamily") != "CORE_TRAC"
            or observation.get("observedAt") != observed_at
            or observation.get("acquisitionResult") != "success"
            or observation.get("sourceRevision") != source_revision):
        fail("description_revision_mismatch")
    artifacts = observation.get("rawArtifacts")
    filename = source_slug(source_id) + ".csv"
    expected_path = f"data/raw/{run_id}/{filename}"
    if (not isinstance(artifacts, list) or len(artifacts) != 1
            or not isinstance(artifacts[0], dict)
            or artifacts[0].get("path") != expected_path
            or artifacts[0].get("sha256") != source_revision
            or artifacts[0].get("contentType") != "text/csv"):
        fail("description_artifact_mismatch")
    artifact = artifacts[0]
    body = read_bounded(run_dir / filename, MAX_CSV_BYTES)
    if (type(artifact.get("byteLength")) is not int
            or artifact["byteLength"] != len(body)
            or hashlib.sha256(body).hexdigest() != source_revision):
        fail("description_raw_hash_mismatch")
    try:
        count, rows = validate_csv(body, list(approved[0].get("expectedFields") or []))
    except ValueError:
        fail("description_csv_invalid")
    saved_rows = observation.get("rows")
    if (type(artifact.get("rowCount")) is not int or artifact["rowCount"] != count
            or not isinstance(saved_rows, list) or saved_rows != rows_for_observation(rows)):
        fail("description_rows_mismatch")
    matches = [row for row in rows if row.get("id") == str(ticket_id)]
    if len(matches) != 1:
        fail("description_ticket_missing_or_ambiguous")
    description = matches[0].get("description")
    if not isinstance(description, str) or not description.strip():
        fail("description_missing")
    description_bytes = description.encode("utf-8")
    if len(description_bytes) > MAX_DESCRIPTION_BYTES:
        fail("description_oversized")
    return {
        "schemaVersion": "radar-core-trac-description-read.v1",
        "ticketId": ticket_id,
        "sourceId": source_id,
        "sourceRevision": source_revision,
        "observedAt": observed_at,
        "ticketModifiedAt": matches[0].get("changetime"),
        "runId": run_id,
        "rawArtifactPath": expected_path,
        "rawArtifactSha256": source_revision,
        "description": description,
        "descriptionByteLength": len(description_bytes),
        "descriptionSha256": hashlib.sha256(description_bytes).hexdigest(),
        "observedRow": rows_for_observation([matches[0]])[0],
        "discussionAvailable": False,
        "contextComplete": False,
    }


def lookup_candidate_description(
    *, feed_path: Path, feed_sha256: str, candidate_id: str, source_id: str,
    raw_root: Path = ROOT / "data/raw",
) -> dict[str, Any]:
    """Bind one published candidate membership to its exact archived CSV row."""
    if (type(feed_sha256) is not str or not SHA256.fullmatch(feed_sha256)
            or type(candidate_id) is not str or len(candidate_id) > 100
            or type(source_id) is not str):
        fail("description_binding_invalid")
    feed_bytes = read_bounded(feed_path, MAX_FEED_BYTES)
    if hashlib.sha256(feed_bytes).hexdigest() != feed_sha256:
        fail("description_feed_hash_mismatch")
    try:
        feed = json.loads(feed_bytes)
    except (ValueError, UnicodeDecodeError):
        fail("description_feed_invalid")
    if (not isinstance(feed, dict) or feed.get("schema") != "radar-candidate-feed.v2"
            or not isinstance(feed.get("candidates"), list)):
        fail("description_feed_invalid")
    candidates = [item for item in feed["candidates"]
                  if isinstance(item, dict) and item.get("candidateId") == candidate_id]
    if len(candidates) != 1:
        fail("description_candidate_missing_or_ambiguous")
    candidate = candidates[0]
    resource = candidate.get("resource")
    if not isinstance(resource, dict):
        fail("description_candidate_invalid")
    ticket = resource.get("identity")
    if (type(ticket) is not str or not re.fullmatch(r"[1-9][0-9]*", ticket)
            or resource.get("resourceType") != "CORE_TRAC_TICKET"
            or resource.get("id") != f"core-trac:{ticket}"):
        fail("description_candidate_invalid")
    memberships = candidate.get("sourceMemberships")
    if not isinstance(memberships, list):
        fail("description_candidate_invalid")
    matches = [item for item in memberships if isinstance(item, dict)
               and item.get("sourceId") == source_id]
    if len(matches) != 1:
        fail("description_membership_missing_or_ambiguous")
    membership = matches[0]
    evidence = membership.get("evidence")
    if (membership.get("sourceFamily") != "CORE_TRAC"
            or membership.get("freshness") not in {"fresh", "stale"}
            or not isinstance(evidence, dict) or evidence.get("id") != ticket):
        fail("description_membership_mismatch")
    result = lookup_description(
        source_id=source_id, source_revision=membership.get("sourceRevision"),
        ticket_id=int(ticket), observed_at=membership.get("observedAt"), raw_root=raw_root,
    )
    # The feed selects the row; the archive must contain those exact delivered
    # fields, not merely the same ticket number in a different observation.
    if result.pop("observedRow") != evidence:
        fail("description_membership_row_mismatch")
    return {
        **result,
        "candidateId": candidate_id,
        "opportunityId": candidate.get("opportunityId"),
        "feedSha256": feed_sha256,
        "feedRevision": feed.get("feedRevision"),
        "membershipFreshness": membership["freshness"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, default=ROOT / "data/candidate-feed.json")
    parser.add_argument("--feed-sha256", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--raw-root", type=Path, default=ROOT / "data/raw")
    args = parser.parse_args()
    try:
        result = lookup_candidate_description(
            feed_path=args.feed, feed_sha256=args.feed_sha256,
            candidate_id=args.candidate_id, source_id=args.source_id, raw_root=args.raw_root,
        )
    except DescriptionLookupError as error:
        print(json.dumps({"status": "refused", "code": str(error)}))
        return 2
    print(json.dumps({"status": "succeeded", "data": result}, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
