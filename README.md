<p align="center">
  <img src="docs/assets/banner.svg" alt="WP Core Radar, a dashboard for finding useful WordPress Core contribution opportunities.">
</p>

# WP Core Radar

WP Core Radar helps me find useful, high-value ways to contribute to WordPress Core.

**View the current Radar:** [https://radar.wp.org.nz/](https://radar.wp.org.nz/)

I regularly collect and upload public ticket data from [WordPress Core Trac](https://core.trac.wordpress.org/). Radar then:

1. validates each collection;
2. normalizes tickets into one consistent opportunity model;
3. scores and ranks opportunities with deterministic, explainable rules; and
4. publishes the current dashboard, reports, and machine-readable feed.

The aim is simple: make promising testing, review, documentation, accessibility, and development opportunities easier to identify.

Radar is a standalone public project built around public WordPress evidence. Its machine-readable API is a general public data interface; downstream tools or systems that choose to read it are outside Radar's product boundary and are not part of Radar's public architecture.

## How scoring works

Each configured Trac search provides a baseline priority. Ticket-level signals then adjust that score. Useful signals include an existing patch, a request for testing or feedback, recent activity, a clear owner, and a manageable discussion size. Stale, closed, previously completed, or unusually complex tickets receive penalties.

Scoring is deterministic. The same inputs, configuration, and reference time produce the same ordering. Every score includes a breakdown of the rules that contributed to it. The executable policy lives in [`config/scoring.json`](config/scoring.json), with a plain-language explanation in [`docs/scoring-rubric.md`](docs/scoring-rubric.md).

Scores are recommendations, not a substitute for reading the ticket. WordPress Core changes quickly, so current Trac state should always be checked before acting.

## Data and outputs

GitHub is the durable source of truth after a collection is published. Raw imports are retained under `data/raw/`, while the verified current dataset lives in `data/certified/current/`.

The same certified opportunity data powers:

- the public dashboard;
- the public contribution outcome view at `/contributions/`;
- the admin view;
- generated reports; and
- the versioned read-only API at `/api/v1/`.

Public contribution outcomes are recorded in `data/public-contributions.json` from independently verifiable public WordPress sources such as Core Trac, WordPress GitHub pull requests, public patches, public reviews, and public ticket discussion.

Radar does not modify WordPress.org, comment on Trac, submit patches, or hold WordPress.org contribution credentials.

## Local development

Install dependencies and run the complete offline validation suite:

```bash
npm ci
npm run check
```

Regenerate the dashboard and reports from the archived collection without fetching new Trac data:

```bash
python3 scripts/run-radar.py --skip-fetch --reference-time 2026-01-15T12:00:00Z
```

Preview the generated site at `http://localhost:8000/`:

```bash
python3 -m http.server 8000 --directory docs/radar
```

Collection uses a browser-assisted local workflow because direct server-side Trac exports have not proved reliable for this project. That operational detail is isolated from Radar's validation, scoring, certification, and publishing logic. See [`docs/collection-operations.md`](docs/collection-operations.md) when operating the collector.

## Documentation

- [`docs/RADAR-PRODUCT.md`](docs/RADAR-PRODUCT.md): product scope and durable rules
- [`docs/architecture.md`](docs/architecture.md): current data flow and component responsibilities
- [`docs/scoring-rubric.md`](docs/scoring-rubric.md): explainable scoring policy
- [`docs/contribution-tracks.md`](docs/contribution-tracks.md): configured opportunity tracks
- [`docs/contracts/machine-feed.md`](docs/contracts/machine-feed.md): `/api/v1/` contract
- [`docs/contracts/executor.md`](docs/contracts/executor.md): structured operation contract
- [`docs/outcome-tracking.md`](docs/outcome-tracking.md): review and contribution-history state
- [`docs/collection-operations.md`](docs/collection-operations.md): collection and scheduled-run operations
