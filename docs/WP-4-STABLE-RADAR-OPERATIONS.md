# WP-4 Stable Radar Operations

Status: **IMPLEMENTED**

This is the implementation record for roadmap item WP-4. The authoritative
program boundaries remain in `WORDPRESS-AUTOMATION-PROGRAM.md`.

## Stable interface

`scripts/radar.py` exposes seven product operations. Each accepts an explicit
ISO-8601 `--reference-time`, emits exactly one `execution-result.v1` JSON value
on stdout, and exits nonzero on failure.

| Operation | Responsibility | Principal output |
| --- | --- | --- |
| `collect` | Invoke the existing browser-assisted collector for all or selected configured queries | archived collection evidence |
| `validate-collection` | Select an exact collection and validate completeness, headers, and evidence | collection identity |
| `generate` | Generate current human/UI projections from one explicit collection | hashed projection artifacts |
| `certify` | Build and atomically install a verified canonical bundle | snapshot identity |
| `verify` | Verify schemas, canonical bytes, hashes, identity, and provenance offline | verified snapshot identity |
| `publish` | Plan the exact verified artifacts eligible for publication | artifact hashes and snapshot identity |
| `pipeline` | Run the ordered lifecycle and stop at the first failure | stage results and final identity |

Collection keeps the known-working browser workflow. WP-4 does not add cloud
HTTP fetching, scheduling, credentials, or live collection in CI.

## Determinism and idempotency

The caller supplies reference time, collection identity, and source revision.
An explicit source revision must be a full 40-character Git SHA. Automatic
revision discovery is allowed only in a clean worktree. Identical inputs,
configuration, and reference time produce identical structured results and
certified bytes. Retrying a successful operation is safe; publication can
return `NO_DATA_DELTA` when the caller states that the snapshot is already
published.

Product results contain repository/logical artifact paths rather than
machine-local paths. Diagnostics from compatibility generators go to stderr so
stdout stays machine-readable.

## Failure taxonomy

Stable result codes are `OK`, `COLLECTION_QUERY_FAILED`,
`COLLECTION_INCOMPLETE`, `COLLECTION_MALFORMED`, `COLLECTION_AMBIGUOUS`,
`GENERATION_FAILED`, `CERTIFICATION_FAILED`, `VERIFICATION_FAILED`,
`NO_DATA_DELTA`, `PUBLICATION_NOT_ELIGIBLE`, `SOURCE_REVISION_INVALID`, and
`PIPELINE_STAGE_FAILED`.

The pipeline is fail closed: it stops immediately after a failed stage and
reports compact results for stages that actually ran. Certification retains
the prior current bundle on failure. Publication always verifies first and is
ineligible if verification fails.

## Publication boundary

Publication is deliberately a plan, not a side effect. It returns the verified
snapshot identity plus hashes for `collection.json`, `opportunities.json`,
`snapshot.json`, and `snapshot.sha256`. It has no Git credentials and performs
no commit, push, release, deployment, scheduling, or provider operation.

Legacy `scripts/run-radar.py` behavior and `scripts/certify-data.py` remain
compatibility surfaces. New executors should use `scripts/radar.py`.

## WP-5 handoff

WP-5 will project the certified opportunity model into `/api/v1/...` and align
dashboard/admin/report consumers with that same model, including provenance and
health presentation. It must consume WP-4 verified artifacts and operation
results rather than introducing another source of truth. WP-4 does not add an
HTTP API, change the current UI projections, or migrate hosting.
