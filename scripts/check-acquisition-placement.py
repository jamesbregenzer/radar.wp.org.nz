#!/usr/bin/env python3
"""Check whether unattended source acquisition may run on this provider."""

from __future__ import annotations

import argparse
import json
import sys

from acquisition_placement import (
    ERROR_CODE,
    PlacementError,
    require_trac_acquisition_placement,
    utc_timestamp,
)
from trac_receipts import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive-canary", action="store_true", help="Allow an explicitly requested diagnostic run outside the canonical provider.")
    args = parser.parse_args()

    try:
        placement = require_trac_acquisition_placement(allow_interactive_canary=args.interactive_canary)
    except PlacementError as error:
        payload = {
            "schema": "radar-source-acquisition-placement.v1",
            "checkedAt": utc_timestamp(),
            "status": "failure",
            "code": ERROR_CODE,
            "placement": error.placement.public_dict(),
        }
        sys.stderr.buffer.write(canonical_json(payload))
        return 78

    payload = {
        "schema": "radar-source-acquisition-placement.v1",
        "checkedAt": utc_timestamp(),
        "status": "success",
        "code": "OK",
        "placement": placement.public_dict(),
    }
    sys.stdout.buffer.write(canonical_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
