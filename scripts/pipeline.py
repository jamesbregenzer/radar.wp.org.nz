#!/usr/bin/env python3
"""Application-layer stages for Radar collection and deterministic generation."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from radarcore import DatasetSelection, RunContext, select_datasets
from radarlib import DATA_RAW, ROOT, TICKET_ID_KEYS


Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class CollectionResult:
    query_slug: str
    exit_code: int
    selection: DatasetSelection

    @property
    def succeeded(self) -> bool:
        evidence = self.selection.evidence.get(self.query_slug)
        return self.exit_code == 0 and evidence is not None and evidence.valid


def subprocess_runner(command: list[str]) -> int:
    print("$ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


def collect_query(query_slug: str, context: RunContext, runner: Runner = subprocess_runner) -> CollectionResult:
    code = runner([sys.executable, "scripts/browser-fetch.py", query_slug])
    selection = select_datasets(DATA_RAW, context.collection_date, [query_slug], TICKET_ID_KEYS)
    return CollectionResult(query_slug, code, selection)


def generate_presentations(context: RunContext, runner: Runner = subprocess_runner, collection_id: str | None = None) -> int:
    value = context.generated_iso
    for script in ("scripts/generate-report.py", "scripts/generate-dashboard.py"):
        command = [sys.executable, script, "--reference-time", value]
        if collection_id:
            command.extend(["--collection-id", collection_id])
        code = runner(command)
        if code:
            return code
    return 0
