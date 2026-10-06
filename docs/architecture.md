# WP Core Radar Architecture

WP Core Radar has one canonical data flow:

```text
WordPress Core Trac CSV exports
  -> raw collection archive
  -> collection validation and evidence
  -> normalization and deterministic scoring
  -> certified current dataset
  -> dashboard, admin, reports, and API projections
```

The v2 API adds a source-neutral projection over the certified dataset:

```text
certified current dataset
  + independently certified public source-family snapshots
  -> source-neutral resources
  -> typed public relationships
  -> qualified opportunities
  -> /api/v2/ sources, snapshot, resources, relationships, opportunities, changes, diagnostics, and taxonomy
```

## Collection

`config/queries.json` defines the enabled Trac searches. The current collector opens those CSV exports in a local browser, imports each downloaded `query.csv` into `data/raw/manual/<collection-id>/`, and removes the temporary browser file.

One run context fixes the reference time, collection ID, source revision, and required query set before collection begins. Every later stage receives that same context, including when a run crosses a date boundary. A certifiable run must collect every enabled query successfully.

The browser workflow is an implementation of the collection boundary, not a dependency of scoring or certification. See [`collection-operations.md`](collection-operations.md) for operating details.

## Canonical model and scoring

`scripts/radarlib.py` normalizes source rows into a single opportunity model and applies `config/scoring.json`. Dataset selection is explicit for certified generation, and duplicate ticket rows retain complete query provenance.

Time-dependent scoring uses the run's explicit reference time. Identical inputs, configuration, and reference time therefore produce identical normalized records and ordering.

## Certification

The canonical application entrypoint is `scripts/radar.py`. Its operations cover collection, collection validation, generation, certification, verification, publication planning, and the composed pipeline. Each operation returns a schema-validated `execution-result.v1` document.

Certification writes versioned `collection.v1`, `snapshot.v1`, and `opportunity.v1` artifacts under `data/certified/current/`. Canonical JSON and SHA-256 identities make the committed bundle independently verifiable offline. An incomplete or invalid run cannot replace the prior certified current dataset.

## Projections

All current product views use the certified opportunity model:

- `scripts/generate-dashboard.py` creates the dashboard, contribution history, admin payload, and safe review-state projection.
- `scripts/generate-report.py` creates the Markdown opportunity report.
- `scripts/generate-api.py` creates static v1 and v2 API artifacts from the verified bundle.
- `cloudflare/worker-radar.js` serves Static Assets, API routes, and the admin application.

The Worker verifies manifest, hash, collection, snapshot, and opportunity relationships before reporting a healthy dataset. It does not fetch Trac data, rescore opportunities, or use GitHub for normal runtime reads.

V2 source-family snapshots are static inputs to generation, not runtime fetches.
`data/sources/wordpress-develop-github.json` is the current bounded public
GitHub source snapshot. If that family cannot be refreshed, Trac certification
can still publish fresh Trac intelligence while v2 reports the GitHub family as
stale or degraded. No partial source family may report itself as complete.

Wave 2 sources use the same static-input rule. Their adapters retain immutable
raw responses and retrieval receipts, normalize source-native resources, and
certify each family independently before V2 projection. The source layer may
emit public candidate signals and outcome-observer possibilities. It does not
own executable work, human-facing composition, scheduling, or mutation authority. The accepted source list
and current quality-yield evidence are documented in
[`wave2-sources.md`](wave2-sources.md).

V2 resources are not opportunities. `scripts/radarv2.py` first projects public
Core Trac tickets and source-family records into family-qualified resources,
then adds typed relationships only when public evidence supports the edge. Bare
numeric references are ambiguous and cannot create cross-source relationships by
themselves. Opportunities identify a missing contribution increment over a
resource cluster and retain v1 Core Trac keys only in legacy compatibility
fields.

## Review state

`data/reviews/reviews.json` is the durable review overlay. Generated public views omit private notes. Applying current review state to a dashboard or admin view does not mutate certified snapshot identity or content.

The deployed admin reads static projections without a GitHub credential. If durable write support is unavailable, write requests fail closed and do not claim that anything was saved. The generic persistence requirements are documented in [`contracts/executor.md`](contracts/executor.md).

## Publication

The public application is served by the `radar-wp-org-nz` Cloudflare Worker with Static Assets from `docs/radar`. GitHub remains the durable source of truth; deployment copies committed projections to the public application.

Radar core does not own scheduling, browser availability, provider credentials, or repository publication. Those concerns are supplied by its operating environment through the bounded contract in [`contracts/executor.md`](contracts/executor.md).

## Safety boundary

Radar recommends opportunities only. A consumer must check current Trac state and make its own contribution decision. Radar never treats a score or API record as authority to change WordPress.org.
