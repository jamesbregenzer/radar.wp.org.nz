# WP Core Radar

WP Core Radar turns approved public WordPress sources into a deterministic
candidate feed for useful contribution opportunities.

The product lifecycle is deliberately small:

```text
approved public sources
  -> fresh raw observations
  -> normalization and deduplication
  -> scoring and classification
  -> canonical candidate feed
  -> commit and push
  -> repeat unattended
```

Radar is read-only and public-source based. It does not modify WordPress.org,
hold WordPress.org credentials, manage private work, or record contribution
outcomes. Git history is the durable archive; the working tree contains only
current source definitions, processing logic, fixtures, and raw observations
needed by the V2 pipeline.

## Source and scoring contracts

- [`config/core-trac-v2-source-registry.json`](config/core-trac-v2-source-registry.json)
  defines approved Core Trac V2 sources.
- [`config/wave2-sources.json`](config/wave2-sources.json) defines approved
  WordPress observatory sources.
- [`config/scoring.json`](config/scoring.json) is the executable scoring policy.
- [`docs/RADAR_V2_PRODUCT_AND_SOURCE_CONTRACT.md`](docs/RADAR_V2_PRODUCT_AND_SOURCE_CONTRACT.md)
  defines the V2 data and candidate-feed contract.
- [`docs/scoring-rubric.md`](docs/scoring-rubric.md) explains the scoring
  dimensions in plain language.
- [`docs/wave2-sources.md`](docs/wave2-sources.md) documents Wave 2 source
  boundaries and evidence requirements.

The implementation preserves source-native evidence, normalizes duplicate
observations into stable resources, and emits source-neutral candidate records.
The same inputs, configuration, and reference time produce the same result.
