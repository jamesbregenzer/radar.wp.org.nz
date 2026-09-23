# WP Core Radar Architecture

The authoritative program boundaries and roadmap live in
`docs/WORDPRESS-AUTOMATION-PROGRAM.md`. This document describes Radar's current
implementation and target architecture without claiming that target work is
already complete.

## CURRENT IMPLEMENTATION

```text
WordPress Trac
  → local Firefox browser-assisted CSV collector
  → data/raw/manual/YYYY-MM-DD/<query_slug>.csv
  → recursive dataset discovery, normalization, scoring, and grouping
  → Markdown reports + dashboard + contributions + admin-data.json
  → GitHub durable source of truth

Protected admin review save
  → data/reviews/reviews.json
  → GitHub Action regeneration
  → committed generated dashboard files
```

The current collector opens configured Trac CSV searches, waits for
`query.csv`, imports the file into the raw archive, and removes the browser
download. It runs in an allowed local network/browser environment currently
associated with Thor because hosted/server collection has historically been
unreliable or blocked.

`scripts/run-radar.py` currently combines collection orchestration and
generation. `scripts/radarlib.py` recursively discovers CSV files, normalizes
rows, and implements executable scoring. `config/scoring.yaml` documents those
rules but is not executable configuration. Generators call `datetime.now()`
directly, and the scheduled wrapper contains a timestamp-only commit workaround.

The repository includes a Cloudflare Worker plus Static Assets target that
serves `docs/radar` and renders the protected admin interface. The established
live hostname remains `radar.james.bregenzer.dev` until WP-6 deployment and
migration are independently completed and verified.

### Current files and responsibilities

1. `config/queries.json` defines enabled query tracks.
2. `scripts/browser-fetch.py` opens each query in Firefox and waits for
   `query.csv`.
3. `scripts/import-download.py` archives the CSV and deletes the temporary
   browser download after successful import.
4. `scripts/verify-collector-snapshot.py` checks that every enabled query has a
   file with a recognized ticket-ID header; it does not yet provide full
   provenance or certification.
5. `scripts/radarlib.py` discovers datasets, normalizes rows, loads review and
   outcome state, scores tickets, and groups results.
6. `scripts/generate-report.py` and `scripts/generate-dashboard.py` create the
   committed report and UI projections.
7. `docs/radar/admin-data.json` is a generated admin/UI payload, not a stable
   machine API.
8. `.github/workflows/refresh-dashboard.yml` regenerates and commits generated
   dashboard files after review-state changes.
9. `scripts/run-scheduled-radar.sh` contains host-specific compatibility,
   synchronization, commit, and push behavior.

### Current security and product boundaries

- Public Radar output contains public Trac data and display-safe review state.
- `/admin/` is protected and may write constrained review metadata only to
  `data/reviews/reviews.json`.
- Secrets belong in provider/runtime custody, never in the repository.
- Radar has no Eden/HWP logic, private contributor credentials, autonomous work
  queue, or WordPress public-write authority.
- GitHub becomes durable truth after collected and generated data is published.

## TARGET ARCHITECTURE

```text
Collector contract
  → collection.v1
  → validate-collection
  → snapshot.v1
  → deterministic normalize/score/rank
  → opportunity.v1
  → certify + verify
  → GitHub canonical certified data
  → dashboard/admin/report/API projections
```

The browser collector remains one valid implementation of the collector
contract. Downstream Radar logic must not depend on Firefox, a particular host,
LaunchAgent, local paths, credential custody, or runtime routing.

The target application is `radar.wp.org.nz`, with protected administration at
`/admin/` and a future certified machine feed at `/api/v1/...`. The HTTP API is
a projection of canonical certified GitHub data, not another authority.

Dashboard, admin, reports, and API/feed will consume one canonical normalized
opportunity model. Certification must include canonical hashes and provenance
and fail closed when evidence is incomplete.

The future private WordPress Contributor is a separate product. It consumes
certified opportunities, independently revalidates live WordPress state, and
routes any public contribution delivery through Eden/HWP policy. It is not part
of this repository's Radar implementation.

Federal Eagle Operations is an external dependency. Radar may define executor
requirements, but it does not implement Thor MCP, scheduling, host provisioning,
credentials, or runtime routing.

## HISTORICAL/COMPATIBILITY

- The established live hostname is `radar.james.bregenzer.dev` during the
  migration window.
- Cloudflare Pages may remain part of the live rollback path until WP-6 proves
  the Worker migration.
- `/Users/thor/Sites/wp-core-radar`, its Python path, and its six-hour scheduler
  cadence are current compatibility details documented in
  `docs/mac-mini-collector.md`; they are not core Radar architecture.
- Legacy raw archive layouts remain readable today because dataset discovery is
  recursive. WP-2 will replace permissive discovery with explicit selection for
  certified generation.

Architecture changes require an ADR or explicit amendment to
`docs/WORDPRESS-AUTOMATION-PROGRAM.md`; they must not enter through silent code
or documentation drift.
