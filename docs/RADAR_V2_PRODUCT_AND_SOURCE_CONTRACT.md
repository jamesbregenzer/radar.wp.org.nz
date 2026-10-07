# Radar V2 product and source contract

Radar V2 has one job:

```text
approved public WordPress sources
-> acquire fresh raw data
-> normalize and deduplicate
-> score and classify
-> data/candidate-feed.json
-> commit and push
-> repeat unattended
```

Radar is read-only. It uses public source URLs, retains current raw artifacts,
and emits no HTTP API, dashboard, review state, contribution outcome, or
provider governance.

## Canonical observation

Every source observation is represented as `radar-observation.v2` with:

- `sourceId`, `sourceFamily`, and `sourceRole`;
- semantic meaning, identity field, resource type, and exact upstream URL;
- `observedAt` and a content-derived `sourceRevision`;
- `acquisitionResult` of `success` or `failed`;
- normalized `rows` and raw artifact hashes;
- an optional truthful error.

`scripts/acquire.py` writes one observation set containing these records. Core
Trac CSV is parsed once. Wave 2 response bytes are validated and normalized by
the existing adapter functions in `scripts/wave2_sources.py` before being
placed in the same observation rows.

## Approved sources

`config/core-trac-v2-source-registry.json` and `config/wave2-sources.json` are
the only source registries. They define public URLs, expected semantics,
source roles, identity fields, and candidate-family mappings. A source failure
is recorded in the current run; healthy sources continue. Processing may retain
the newest prior usable observation as explicitly stale evidence.

## Processing and scoring

`scripts/process.py` reads the observation set, revalidates rows against the
approved registry rules, deduplicates by source family and native identity,
preserves every source membership, excludes non-actionable resources, and
emits `data/candidate-feed.json`.

`config/scoring.json` is the single scoring policy. It contains the exact V2
base, bonuses, caps, stale penalty, and tier thresholds used by the processor.
The result is deterministic for the same observations, configuration, and
reference time.

## Unattended runtime

`scripts/run.py` takes a local non-overlap lock, runs acquisition and
processing, validates the candidate feed, stages the current raw run and feed,
commits when either changes, then pulls with rebase and pushes. It does not
deploy or modify WordPress.org.
