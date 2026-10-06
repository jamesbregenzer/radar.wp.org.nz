#!/usr/bin/env python3
"""Collect a bounded public Gutenberg GitHub source snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any

from certification import canonical_hash, canonical_json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "sources" / "gutenberg-github.json"
REPO = "WordPress/gutenberg"
ISSUES_URL = "https://api.github.com/repos/{repo}/issues?state=open&sort=updated&direction=desc&per_page={limit}"
PULLS_URL = "https://api.github.com/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page={limit}"


def fetch_json(url: str) -> tuple[Any, str | None, bool]:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/vnd.github+json",
            "user-agent": "wp-core-radar-public-source-collector",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
        link = response.headers.get("link") or ""
        return payload, response.headers.get("etag"), 'rel="next"' in link


def label_names(item: dict[str, Any]) -> list[str]:
    return sorted(str(label.get("name") or "") for label in item.get("labels", []) if label.get("name"))


def normalize_issue(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "resourceType": "GUTENBERG_ISSUE",
        "number": item["number"],
        "url": item["html_url"],
        "apiUrl": item["url"],
        "title": item.get("title") or "",
        "body": item.get("body") or "",
        "state": item.get("state") or "unknown",
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
        "labels": label_names(item),
        "comments": item.get("comments"),
        "milestone": (item.get("milestone") or {}).get("title"),
    }


def observed_page(kind: str, values: Any, truncated: bool) -> dict[str, Any]:
    if isinstance(values, dict) and "check_runs" in values:
        items = values.get("check_runs", [])
    elif isinstance(values, list):
        items = values
    else:
        items = []
    return {
        "kind": kind,
        "count": len(items),
        "truncated": truncated,
        "observed": True,
    }


def empty_observed_page(kind: str) -> dict[str, Any]:
    return {"kind": kind, "count": None, "truncated": None, "observed": False}


def diff_identity(files: list[dict[str, Any]], truncated: bool) -> dict[str, Any]:
    public_files = [
        {
            "filename": item.get("filename"),
            "status": item.get("status"),
            "sha": item.get("sha"),
            "previousFilename": item.get("previous_filename"),
            "additions": item.get("additions"),
            "deletions": item.get("deletions"),
            "changes": item.get("changes"),
        }
        for item in files
    ]
    return {
        "fileCount": len(public_files),
        "filesHash": canonical_hash({"files": public_files}) if public_files else None,
        "truncated": truncated,
        "observed": True,
    }


def empty_diff_identity() -> dict[str, Any]:
    return {"fileCount": None, "filesHash": None, "truncated": None, "observed": False}


def enrich_pull_request(item: dict[str, Any], enrich: bool) -> dict[str, Any]:
    if not enrich:
        return {
            "discussion": empty_observed_page("issue-comments"),
            "reviews": empty_observed_page("pull-request-reviews"),
            "checks": empty_observed_page("check-runs"),
            "diffIdentity": empty_diff_identity(),
        }
    comments, _, comments_truncated = fetch_json(item["issue_url"] + "/comments?per_page=100")
    reviews, _, reviews_truncated = fetch_json(item["url"] + "/reviews?per_page=100")
    files, _, files_truncated = fetch_json(item["url"] + "/files?per_page=100")
    head_sha = item.get("head", {}).get("sha")
    if head_sha:
        checks_url = f"https://api.github.com/repos/{REPO}/commits/{head_sha}/check-runs?per_page=100"
        checks, _, checks_truncated = fetch_json(checks_url)
    else:
        checks, checks_truncated = {"check_runs": []}, False
    return {
        "discussion": observed_page("issue-comments", comments, comments_truncated),
        "reviews": observed_page("pull-request-reviews", reviews, reviews_truncated),
        "checks": observed_page("check-runs", checks, checks_truncated),
        "diffIdentity": diff_identity(files if isinstance(files, list) else [], files_truncated),
    }


def normalize_pull_request(item: dict[str, Any], issue_index: dict[int, dict[str, Any]], enrichment: dict[str, Any]) -> dict[str, Any]:
    issue = issue_index.get(int(item["number"]), {})
    return {
        "resourceType": "GUTENBERG_PR",
        "number": item["number"],
        "url": item["html_url"],
        "apiUrl": item["url"],
        "title": item.get("title") or "",
        "body": item.get("body") or "",
        "state": item.get("state") or "unknown",
        "draft": bool(item.get("draft")),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
        "labels": sorted(set(label_names(item) + list(issue.get("labels", [])))),
        "comments": issue.get("comments"),
        "requestedReviewers": [user.get("login") for user in item.get("requested_reviewers", []) if user.get("login")],
        "requestedTeams": [team.get("slug") for team in item.get("requested_teams", []) if team.get("slug")],
        "milestone": (item.get("milestone") or {}).get("title") or issue.get("milestone"),
        "base": {
            "ref": item.get("base", {}).get("ref"),
            "sha": item.get("base", {}).get("sha"),
            "repo": item.get("base", {}).get("repo", {}).get("full_name"),
        },
        "head": {
            "ref": item.get("head", {}).get("ref"),
            "sha": item.get("head", {}).get("sha"),
            "repo": item.get("head", {}).get("repo", {}).get("full_name"),
        },
        "discussion": enrichment["discussion"],
        "reviews": enrichment["reviews"],
        "checks": enrichment["checks"],
        "diffIdentity": enrichment["diffIdentity"],
    }


def build_snapshot(limit: int, observed_at: str | None = None, enrich_limit: int = 0) -> dict[str, Any]:
    observed = observed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        issues_payload, issues_etag, issues_truncated = fetch_json(ISSUES_URL.format(repo=REPO, limit=limit))
        pulls_payload, pulls_etag, pulls_truncated = fetch_json(PULLS_URL.format(repo=REPO, limit=limit))
        issue_index = {
            int(item["number"]): normalize_issue(item)
            for item in issues_payload
            if "pull_request" not in item
        }
        pull_issue_index = {
            int(item["number"]): normalize_issue(item)
            for item in issues_payload
            if "pull_request" in item
        }
        resources = list(issue_index.values()) + [
            normalize_pull_request(item, pull_issue_index, enrich_pull_request(item, index < enrich_limit))
            for index, item in enumerate(pulls_payload)
        ]
        health = {"state": "certified", "failure": None}
        completeness = "PARTIAL" if issues_truncated or pulls_truncated else "COMPLETE"
        limitations = [
            f"Snapshot is bounded to the {limit} most recently updated open Gutenberg issues and {limit} most recently updated open Gutenberg pull requests.",
            f"Review, CI, discussion, and diff identity enrichment is bounded to the first {enrich_limit} pull requests.",
        ]
        source_revision = f"issues:{issues_etag or 'none'} pulls:{pulls_etag or 'none'}"
        pagination = {"issuesNextPagePresent": issues_truncated, "pullsNextPagePresent": pulls_truncated}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        resources = []
        pagination = {"issuesNextPagePresent": None, "pullsNextPagePresent": None}
        health = {"state": "failed", "failure": f"{type(error).__name__}: {error}"}
        completeness = "NONE"
        limitations = ["Gutenberg GitHub collection failed; no partial source data is certified."]
        source_revision = None

    preimage = {
        "schema": "source-family-snapshot.v1",
        "sourceFamily": "GUTENBERG",
        "sourceRevision": source_revision,
        "observedTime": observed,
        "resources": resources,
    }
    canonical = canonical_hash(preimage)
    return {
        "schema": "source-family-snapshot.v1",
        "version": 1,
        "sourceFamily": "GUTENBERG",
        "snapshotId": f"source-family-gutenberg-{canonical[:24]}",
        "sourceRevision": source_revision,
        "observedTime": observed,
        "certifiedTime": observed,
        "completeness": completeness,
        "freshness": "fresh" if resources else "stale",
        "recordCount": len(resources),
        "canonicalHash": canonical,
        "limitations": limitations,
        "health": health,
        "pagination": pagination,
        "resources": resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--enrich-limit", type=int, default=0)
    parser.add_argument("--observed-at")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.limit, args.observed_at, args.enrich_limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(snapshot))
    print(args.output.relative_to(ROOT))
    return 0 if snapshot["health"]["state"] == "certified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
