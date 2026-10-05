#!/usr/bin/env python3
"""Collect a bounded public wordpress-develop GitHub source snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
from typing import Any

from certification import canonical_hash, canonical_json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "sources" / "wordpress-develop-github.json"
PULLS_URL = "https://api.github.com/repos/WordPress/wordpress-develop/pulls?state=open&sort=updated&direction=desc&per_page={limit}"


def fetch_json(url: str) -> tuple[list[dict[str, Any]], str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/vnd.github+json",
            "user-agent": "wp-core-radar-public-source-collector",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return payload, response.headers.get("etag")


def normalize_pull_request(item: dict[str, Any]) -> dict[str, Any]:
    body = item.get("body") or ""
    ticket_references = sorted(set(re.findall(r"(?:ticket/|#)([0-9]{4,6})\b", f"{item.get('title') or ''} {body} {item.get('html_url') or ''}")))
    return {
        "resourceType": "WORDPRESS_DEVELOP_PR",
        "number": item["number"],
        "url": item["html_url"],
        "apiUrl": item["url"],
        "title": item.get("title") or "",
        "ticketReferences": ticket_references,
        "state": item.get("state") or "unknown",
        "draft": bool(item.get("draft")),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
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
        "changedFiles": item.get("changed_files"),
    }


def build_snapshot(limit: int, observed_at: str | None = None) -> dict[str, Any]:
    observed = observed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    url = PULLS_URL.format(limit=limit)
    try:
        pulls, etag = fetch_json(url)
        resources = [normalize_pull_request(item) for item in pulls]
        health = {"state": "certified", "failure": None}
        completeness = "PARTIAL" if len(resources) == limit else "COMPLETE"
        limitations = [
            f"Snapshot is bounded to the {limit} most recently updated open wordpress-develop pull requests.",
            "GitHub review and CI details are represented only when present in the bounded pull request response.",
        ]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        resources = []
        etag = None
        health = {"state": "failed", "failure": f"{type(error).__name__}: {error}"}
        completeness = "NONE"
        limitations = ["GitHub collection failed; no partial source data is certified."]

    preimage = {
        "schema": "source-family-snapshot.v1",
        "sourceFamily": "WORDPRESS_DEVELOP_GITHUB",
        "sourceRevision": etag,
        "observedTime": observed,
        "resources": resources,
    }
    canonical = canonical_hash(preimage)
    return {
        "schema": "source-family-snapshot.v1",
        "version": 1,
        "sourceFamily": "WORDPRESS_DEVELOP_GITHUB",
        "snapshotId": f"source-family-wordpress-develop-github-{canonical[:24]}",
        "sourceRevision": etag,
        "observedTime": observed,
        "certifiedTime": observed,
        "completeness": completeness,
        "freshness": "fresh" if resources else "stale",
        "recordCount": len(resources),
        "canonicalHash": canonical,
        "limitations": limitations,
        "health": health,
        "resources": resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--observed-at")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.limit, args.observed_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(snapshot))
    print(args.output.relative_to(ROOT))
    return 0 if snapshot["health"]["state"] == "certified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
