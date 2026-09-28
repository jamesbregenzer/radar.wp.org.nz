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
- `scripts/generate-api.py` creates static API artifacts from the verified bundle.
- `cloudflare/worker-radar.js` serves Static Assets, API routes, and the admin application.

The Worker verifies manifest, hash, collection, snapshot, and opportunity relationships before reporting a healthy dataset. It does not fetch Trac data, rescore opportunities, or use GitHub for normal runtime reads.

## Review state

`data/reviews/reviews.json` is the durable review overlay. Generated public views omit private notes. Applying current review state to a dashboard or admin view does not mutate certified snapshot identity or content.

The deployed admin reads static projections without a GitHub credential. If durable write support is unavailable, write requests fail closed and do not claim that anything was saved. The generic persistence requirements are documented in [`contracts/executor.md`](contracts/executor.md).

## Publication

The public application is served by the `radar-wp-org-nz` Cloudflare Worker with Static Assets from `docs/radar`. GitHub remains the durable source of truth; deployment copies committed projections to the public application.

Radar core does not own scheduling, browser availability, provider credentials, or repository publication. Those concerns are supplied by its operating environment through the bounded contract in [`contracts/executor.md`](contracts/executor.md).

## Safety boundary

Radar recommends opportunities only. A consumer must check current Trac state and make its own contribution decision. Radar never treats a score or API record as authority to change WordPress.org.
