#!/usr/bin/env python3
"""WP-3 compatibility wrapper; canonical operations live in radar.py."""

from __future__ import annotations

import sys

from radar import main as radar_main


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "verify" and "--reference-time" not in arguments:
        arguments.extend(["--reference-time", "1970-01-01T00:00:00Z"])
    return radar_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
