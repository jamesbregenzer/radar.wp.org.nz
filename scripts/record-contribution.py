#!/usr/bin/env python3
"""Record one public-safe, verified WordPress Core contribution.

This helper is intentionally narrow. It will not record review/watch/reject state
and it fails closed unless the lifecycle is PUBLIC_DELIVERY_VERIFIED.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse

STATE_PATH = Path("data") / "contributions" / "contribution-state.json"
ALLOWED_STATUS = {"tested", "commented", "committed"}


def fail(message: str) -> None:
    raise SystemExit(message)


def load_state() -> dict:
    payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "contribution-state.v1" or payload.get("version") != 1:
        fail("CONTRIBUTION_STATE_INVALID")
    if not isinstance(payload.get("contributions"), list):
        fail("CONTRIBUTION_STATE_INVALID")
    return payload


def public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "core.trac.wordpress.org",
        "github.com",
    }:
        fail("PUBLIC_URL_INVALID")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--lifecycle-state", required=True)
    parser.add_argument("--status", required=True, choices=sorted(ALLOWED_STATUS))
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--tested-sha", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--reason", default="Public delivery verified.")
    parser.add_argument("--updated-at")
    parser.add_argument("--received-props", action="store_true")
    parser.add_argument("--props-observed-at", default="")
    parser.add_argument("--changeset", default="")
    args = parser.parse_args()

    if args.lifecycle_state != "PUBLIC_DELIVERY_VERIFIED":
        fail("PUBLIC_DELIVERY_VERIFIED_REQUIRED")
    if not args.ticket.isdigit():
        fail("TICKET_ID_INVALID")
    if args.received_props and not args.props_observed_at:
        fail("PROPS_OBSERVATION_REQUIRED")
    if not args.received_props and (args.props_observed_at or args.changeset):
        fail("PROPS_MUST_BE_OBSERVED")

    state = load_state()
    record = {
        "ticket_id": args.ticket,
        "lifecycle_state": "PUBLIC_DELIVERY_VERIFIED",
        "status": args.status,
        "public_url": public_url(args.public_url),
        "tested_sha": args.tested_sha,
        "summary": args.summary,
        "reason": args.reason,
        "updated_at": args.updated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "received_props": args.received_props,
    }
    if args.received_props:
        record["props_observed_at"] = args.props_observed_at
        if args.changeset:
            record["changeset"] = args.changeset

    contributions = [
        item for item in state["contributions"]
        if str(item.get("ticket_id")) != args.ticket
    ]
    contributions.append(record)
    contributions.sort(key=lambda item: int(item["ticket_id"]))
    state["contributions"] = contributions

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded verified contribution #{args.ticket}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
