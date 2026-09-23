"""Deterministic core contracts for Radar collection and generation."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCORING_CONFIG = ROOT / "config" / "scoring.json"


@dataclass(frozen=True)
class RunContext:
    reference_time: datetime

    def __post_init__(self) -> None:
        value = self.reference_time
        if value.tzinfo is None:
            object.__setattr__(self, "reference_time", value.replace(tzinfo=timezone.utc))

    @property
    def collection_date(self) -> str:
        return self.reference_time.astimezone(timezone.utc).strftime("%Y-%m-%d")

    @property
    def generated_iso(self) -> str:
        return self.reference_time.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    @property
    def generated_display(self) -> str:
        return self.reference_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def parse_run_time(value: str | None) -> RunContext:
    if not value:
        return RunContext(datetime.now(timezone.utc))
    cleaned = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(cleaned)
    return RunContext(parsed)


@dataclass(frozen=True)
class CollectionEvidence:
    query_slug: str
    source_identity: str
    artifact_path: Path
    collected_at: datetime | None
    exists: bool
    valid_csv: bool
    recognized_ticket_id: bool
    row_count: int
    sha256: str
    status: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status == "valid"


@dataclass(frozen=True)
class DatasetSelection:
    identity: str
    expected_queries: tuple[str, ...]
    artifacts: dict[str, Path]
    evidence: dict[str, CollectionEvidence]
    unexpected: tuple[Path, ...] = ()
    ambiguous: dict[str, tuple[Path, ...]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (
            set(self.artifacts) == set(self.expected_queries)
            and not self.ambiguous
            and all(self.evidence[slug].valid for slug in self.expected_queries)
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_csv_artifact(path: Path, query_slug: str, ticket_id_keys: tuple[str, ...]) -> CollectionEvidence:
    if not path.exists():
        return CollectionEvidence(query_slug, query_slug, path, None, False, False, False, 0, "", "invalid", errors=("missing",))

    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            headers = tuple(reader.fieldnames or ())
            rows = list(reader)
    except (csv.Error, UnicodeError, OSError) as error:
        return CollectionEvidence(query_slug, query_slug, path, None, True, False, False, 0, file_sha256(path), "invalid", errors=(f"malformed_csv:{type(error).__name__}",))

    recognized = bool(set(headers).intersection(ticket_id_keys))
    errors = () if headers and recognized else (("missing_ticket_id_header",) if headers else ("missing_header",))
    warnings = ("empty_but_valid",) if recognized and not rows else ()
    collected_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return CollectionEvidence(
        query_slug=query_slug,
        source_identity=query_slug,
        artifact_path=path,
        collected_at=collected_at,
        exists=True,
        valid_csv=bool(headers),
        recognized_ticket_id=recognized,
        row_count=len(rows),
        sha256=file_sha256(path),
        status="valid" if headers and recognized else "invalid",
        warnings=warnings,
        errors=errors,
    )


def select_datasets(raw_dir: Path, identity: str, expected_queries: list[str], ticket_id_keys: tuple[str, ...]) -> DatasetSelection:
    base = raw_dir / "manual" / identity
    expected = tuple(expected_queries)
    artifacts: dict[str, Path] = {}
    evidence: dict[str, CollectionEvidence] = {}
    ambiguous: dict[str, tuple[Path, ...]] = {}

    for slug in expected:
        candidates = tuple(sorted(path for path in base.glob("*.csv") if path.stem.casefold() == slug.casefold()))
        if len(candidates) > 1:
            ambiguous[slug] = candidates
        path = candidates[0] if candidates else base / f"{slug}.csv"
        evidence[slug] = validate_csv_artifact(path, slug, ticket_id_keys)
        if len(candidates) == 1:
            artifacts[slug] = path

    expected_paths = {base / f"{slug}.csv" for slug in expected}
    unexpected = tuple(sorted(path for path in base.glob("*.csv") if path not in expected_paths)) if base.exists() else ()
    return DatasetSelection(identity, expected, artifacts, evidence, unexpected, ambiguous)


def load_scoring_config(path: Path = SCORING_CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("version") or not isinstance(payload.get("points"), dict) or not isinstance(payload.get("thresholds"), dict):
        raise ValueError("Scoring configuration requires version, points, and thresholds.")
    return payload
