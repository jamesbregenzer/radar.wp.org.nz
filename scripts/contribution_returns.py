#!/usr/bin/env python3
"""Public contribution return ingestion for Radar V2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from certification import canonical_hash

ROOT = Path(__file__).resolve().parents[1]


def validate_return_record(record: dict[str, Any]) -> None:
    required = [
        "id",
        "publicDeliveryUrl",
        "sourceResourceRef",
        "sourceFamily",
        "publicContributionType",
        "observedPublicDeliveryAt",
        "verificationSource",
        "outcomeFlags",
        "publicSummary",
    ]
    missing = [field for field in required if field not in record]
    if missing:
        raise ValueError(f"contribution return missing {', '.join(missing)}")
    if not str(record["publicDeliveryUrl"]).startswith(("https://core.trac.wordpress.org/", "https://github.com/WordPress/")):
        raise ValueError("contribution return must use an approved public WordPress URL")
    resource_ref = record["sourceResourceRef"]
    if not isinstance(resource_ref, dict) or not str(resource_ref.get("id", "")).startswith(("core-trac:", "wordpress-develop-github:", "gutenberg:")):
        raise ValueError("contribution return must reference a public Radar resource")


def load_contribution_return_feed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_contribution_return_feed(payload)


def normalize_contribution_return_feed(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "radar-contribution-return-feed.v1":
        raise ValueError("unsupported contribution return feed schema")
    records = []
    outcomes = []
    for item in payload.get("returns", []):
        validate_return_record(item)
        resource_id = item["sourceResourceRef"]["id"]
        ticket_id = resource_id.removeprefix("core-trac:") if resource_id.startswith("core-trac:") else None
        record = {
            "id": f"radar-contribution-v2-{canonical_hash(item)[:24]}",
            "returnId": item["id"],
            "resourceRef": item["sourceResourceRef"],
            "sourceFamily": item["sourceFamily"],
            "ticketId": ticket_id,
            "publicUrl": item["publicDeliveryUrl"],
            "contributionType": item["publicContributionType"],
            "observedPublicDeliveryAt": item["observedPublicDeliveryAt"],
            "verifiedPublicOutcomeAt": item.get("verifiedPublicOutcomeAt"),
            "verificationSource": item["verificationSource"],
            "publicSummary": item["publicSummary"],
            "sourceRevision": item.get("sourceRevision"),
            "outcomeFlags": item["outcomeFlags"],
        }
        records.append(record)
        if item.get("publicOutcomeUrl") or any(item["outcomeFlags"].values()):
            outcomes.append({
                "id": f"radar-outcome-v2-{canonical_hash({'return': item['id'], 'flags': item['outcomeFlags']})[:24]}",
                "contributionId": record["id"],
                "resourceRef": item["sourceResourceRef"],
                "publicOutcomeUrl": item.get("publicOutcomeUrl"),
                "verifiedPublicOutcomeAt": item.get("verifiedPublicOutcomeAt"),
                "outcomeFlags": item["outcomeFlags"],
                "verificationSource": item["verificationSource"],
            })
    return {
        "schema": "radar-contribution-return-projection.v1",
        "version": 1,
        "sourceRevision": payload.get("sourceRevision"),
        "contributions": sorted(records, key=lambda record: record["id"]),
        "outcomes": sorted(outcomes, key=lambda outcome: outcome["id"]),
    }
