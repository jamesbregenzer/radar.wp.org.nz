# WP-3 Certified Radar Data

Status: **IMPLEMENTED IN WP-3**

This document records the WP-3 implementation under the authoritative
`RADAR-PRODUCT.md` plan. It does not expand Radar into WordPress.org writes,
contribution authorization, an HTTP API, or runtime orchestration.

## Canonical contracts

The public-safe contracts are strict JSON Schemas under `schemas/`:

- `collection.v1` records the explicit collection Radar observed and its
  per-query evidence.
- `opportunity.v1` projects the WP-2 canonical internal `Opportunity`, including
  complete discovery-source provenance after deduplication.
- `snapshot.v1` certifies the collection, configuration, source revision,
  opportunity dataset, and artifact hashes.
- `execution-result.v1` is the portable success/failure envelope for
  certification and verification. WP-4 may reuse it without adding host,
  scheduler, credential, or executor identity.

All four schemas reject unknown top-level and nested fields where the contract
is defined. Provider credentials, executor instructions, private notes, and
contribution authorization are excluded.

## Canonical JSON policy

`scripts/certification.py` owns serialization and hashing:

1. objects are encoded with lexicographically sorted keys;
2. arrays retain their explicitly normalized semantic order;
3. separators are compact (``,``, ``:``) with no insignificant whitespace;
4. text is UTF-8 with Unicode preserved;
5. every document ends with exactly one LF;
6. repository-relative artifact identities replace machine-local paths;
7. the explicit `RunContext` is the only generation clock;
8. filesystem modification times, hostnames, usernames, and executor metadata
   never enter canonical hashes.

Equal logical inputs, source revision, configuration, and `RunContext` therefore
produce byte-identical artifacts.

## Stable identities

The collection ID is:

`collection-v1-` plus the first 24 hexadecimal characters of SHA-256 over the
canonical `collection.v1` preimage before `collection_id` is inserted.

The snapshot ID is:

`snapshot-v1-` plus the first 24 hexadecimal characters of SHA-256 over a
canonical identity object containing the collection hash, normalized
opportunity seed hash, explicit reference time, supplied Radar source revision,
scoring configuration hash, and query configuration hash.

Neither identity depends on random values, wall-clock calls, host state, or
temporary paths.

## Certification lifecycle

Certification requires an explicit complete `DatasetSelection`. It fails closed
if a required query is missing, malformed, or ambiguous; if normalization or
schema validation fails; or if canonical hashes cannot be reproduced.

All artifacts are built and validated before publication. A candidate is
written to a sibling staging directory, independently verified, and only then
swapped into `data/certified/current/`. A validation/certification failure does
not touch the prior current dataset and returns a structured failure result.

A structurally valid zero-row query remains valid and preserves the
`empty_but_valid` warning. Unexpected artifacts are recorded as warnings but do
not silently enter the selected collection.

## Current certified layout

```text
data/certified/current/
  collection.json
  opportunities.json
  snapshot.json
  snapshot.sha256
```

`current` means the newest complete dataset that successfully passed all
certification and offline-verification gates. A later failed or incomplete run
does not advance it.

`snapshot.json` inventories and hashes the collection and opportunity payloads.
Because a manifest cannot contain its own SHA-256 without becoming
self-referential, `snapshot.sha256` is the detached hash for `snapshot.json`.

## Provenance and verification

The snapshot records the exact scoring version and SHA-256 of
`config/scoring.json`, the SHA-256 of `config/queries.json`, the supplied Radar
source revision, schema versions, source collection identity/hash, opportunity
count, dataset hash, and payload artifact hashes.

Offline verification reads only the repository checkout. It checks schemas,
collection completeness, deterministic collection/snapshot identities, payload
hashes, detached manifest hash, opportunity count, provenance links, and exact
scoring/query configuration hashes. It requires no browser, WordPress access,
Cloudflare access, provider runtime, or current clock.

The narrow WP-3 interface is:

```bash
python3 scripts/certify-data.py certify \
  --collection-id YYYY-MM-DD \
  --reference-time 2026-01-15T12:00:00Z \
  --source-revision <git-sha>

python3 scripts/certify-data.py verify
```

WP-4 will define the final operational command composition and publication
lifecycle.

## Historical retention

WP-3 commits exactly one current certified dataset to `main`. Git history
retains previous current states without adding a permanently growing duplicate
snapshot tree. If immutable named releases are needed later, WP-4 may publish
certified bundles as GitHub release/workflow artifacts under a documented
retention policy. WP-3 does not introduce release automation.

## Handoff

- WP-4 owns stable `collect`, `validate-collection`, `generate`, `certify`,
  `verify`, `publish`, and composed `pipeline` operations.
- WP-5 owns `/api/v1/...` projection and migration of dashboard/admin/report
  consumers to the versioned canonical model.
- `docs/radar/admin-data.json` remains a compatibility UI payload, never the
  certified API.

Architecture changes continue to require an ADR or an explicit amendment to
the authoritative program plan.
