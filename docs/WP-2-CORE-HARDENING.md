# WP-2 Radar Core Hardening

Status: **IMPLEMENTED IN WP-2**

This document records the implementation boundary for WP-2 under the
authoritative `RADAR-PRODUCT.md` plan. It does not change Radar's frozen
product architecture.

## Core changes

- The proven Firefox/browser collector remains the active collector.
- `scripts/pipeline.py` provides a collector result boundary and separates
  collection from presentation generation.
- `RunContext` supplies one explicit reference time to scoring and every
  generated projection.
- `config/scoring.json` is the single executable source for scoring values and
  thresholds.
- `DatasetSelection` names an exact collection identity and expected query
  artifacts. Legacy recursive discovery remains available only as a
  compatibility path; explicit selection is the hardened path for downstream
  certification.
- `CollectionEvidence` records source/query identity, artifact path, collection
  time derived from the artifact, CSV/header validity, row count, SHA-256,
  warnings, errors, and status. A valid zero-row query is retained with an
  explicit warning and is not failed by an arbitrary row threshold.
- `Opportunity` is the canonical normalized/scored internal model. Existing
  dashboard, admin, report, and contribution renderers receive compatibility
  projections from this one model.
- Fixed fixtures and deterministic unit/contract tests cover parsing, scoring,
  selection, evidence, deduplication, ordering, and pipeline orchestration.

## Compatibility and runtime assumptions

| Assumption | Classification | Treatment |
| --- | --- | --- |
| Firefox downloads `query.csv` | collector compatibility | Preserved; hidden behind the collection boundary |
| Browser runs in an allowed local network environment | executor requirement | Expressed, not provisioned by Radar |
| Local collector checkout path | runtime compatibility | Derived from the scheduled wrapper location or supplied explicitly |
| Homebrew Python path | runtime compatibility | Remains only in the legacy scheduled wrapper |
| LaunchAgent/six-hour schedule | external runtime | Unchanged and out of scope |
| GitHub publication | durable-data boundary | Remains the point at which collected data becomes durable truth |

## Intentionally deferred

- Versioned `collection.v1`, `snapshot.v1`, `opportunity.v1`, and
  `execution-result.v1` schemas, canonical serialization, and fail-closed
  certification belong to WP-3.
- Stable operational commands and structured publish/verify lifecycle belong
  to WP-4.
- A public machine feed and full UI migration to a versioned opportunity schema
  belong to WP-5. `admin-data.json` remains a UI payload, not an API.
- Runtime provisioning, scheduling, credentials, and routing remain external
  runtime concerns.

Architecture changes still require an ADR or an explicit amendment to the
authoritative program plan; this implementation must not become a route for
silent architectural drift.
