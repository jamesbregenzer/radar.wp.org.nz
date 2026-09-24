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
  → explicit run context and collection evidence
  → canonical opportunity normalization, scoring, and grouping
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

WP-2 separated collection and generation behind `scripts/pipeline.py` while
preserving the command-line entrypoint and browser behavior. `scripts/radarlib.py`
normalizes rows into a canonical `Opportunity` model and applies the executable
`config/scoring.json` policy. A single explicit `RunContext` supplies time to
scoring and generation. Recursive archive discovery remains a compatibility
path; explicit `DatasetSelection` is available for deterministic downstream
work. The scheduled wrapper's timestamp-only commit workaround remains a
runtime compatibility detail pending operational migration.

The repository includes a migration-ready Cloudflare Worker plus Static Assets
target that serves `docs/radar`, projects the certified API, and renders the
protected admin interface. No active product request depends on a Pages origin
or the legacy hostname. Provider-side deployment, binding, and redirect changes
remain external WP-6 cutover actions.

### Current files and responsibilities

1. `config/queries.json` defines enabled query tracks.
2. `scripts/browser-fetch.py` opens each query in Firefox and waits for
   `query.csv`.
3. `scripts/import-download.py` archives the CSV and deletes the temporary
   browser download after successful import.
4. `scripts/radarcore.py` selects exact artifacts and records collection
   evidence including validation state, row count, file time, and SHA-256.
   `scripts/verify-collector-snapshot.py` remains the compatibility verifier;
   the scheduled wrapper then invokes WP-3/WP-4 certification and verification.
5. `scripts/radarlib.py` normalizes rows into canonical opportunities, loads
   review/outcome state, applies executable scoring, deduplicates, and groups.
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
- `/admin/` is protected and reads deployed projections without GitHub
  credentials. Durable writes fail closed until an approved executor satisfies
  Radar's persistence contract.
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
`/admin/` and a certified machine feed at `/api/v1/...`. The HTTP API is
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

## IMPLEMENTED — WP-3 certified data

An explicit complete `DatasetSelection` can now produce strict `collection.v1`,
`opportunity.v1`, `snapshot.v1`, and `execution-result.v1` data. Centralized
canonical JSON and deterministic IDs/hashes make the committed
`data/certified/current/` bundle independently verifiable offline. Failed or
incomplete certification leaves the prior current bundle unchanged.

The current dashboard, report, contribution history, and admin payload remain
compatibility projections from the WP-2 internal model. Full consumption of the
public versioned schema and `/api/v1/...` remain WP-5 work.

## IMPLEMENTED — WP-4 stable operations

`scripts/radar.py` is the canonical application entrypoint for `collect`,
`validate-collection`, `generate`, `certify`, `verify`, `publish`, and
`pipeline`. Every command emits a validated `execution-result.v1` JSON document,
and the pipeline stops at the first failed stage. `publish` is a deterministic
eligibility plan over the verified certified bundle; executors retain custody
of Git authentication, repository writes, scheduling, and delivery. The exact
boundary is in `docs/contracts/executor.md`.

## IMPLEMENTED — WP-5 machine feed and aligned projections

The Worker projects the committed, verified `data/certified/current/` bundle at
`/api/v1/`. Generated Static Assets are byte-preserving copies or deterministic
derivatives; the Worker checks manifest, dataset, collection, and identity
relationships before returning healthy data. Dashboard, admin data, and reports
use `scripts/certifiedmodel.py` to adapt the same `opportunity.v1` records for
existing renderers without rescoring raw CSV.

Human review data remains a separate mutable GitHub-backed overlay. It may
change dashboard/admin grouping between certifications, but it never rewrites
the immutable certified snapshot or enters the machine feed as current private
notes. Production hostname and Access/service-token policy are specified by
WP-6 and remain provider-side cutover work.

## IMPLEMENTED — WP-6 production architecture

The canonical repository is `jamesbregenzer/radar.wp.org.nz`. The Worker has no
GitHub repository setting or credential because dashboard, API, and admin reads
come from deployed projections. `wrangler.jsonc` names the durable Worker and
Static Assets directory; the canonical hostname binding and Cloudflare Access
policy remain provider-owned configuration. The target topology, machine-access
policy, DNS/redirect semantics, acceptance tests, rollback, and Pages-retirement gates are frozen in
`docs/WP-6-RADAR-PRODUCTION-MIGRATION.md` and
`config/production-migration.json`.

The Worker is bound at `radar.wp.org.nz` behind the human Access policy. The API
is private by default until separately governed machine identity is provided.
The historical Pages project remains rollback infrastructure. Provider-side
redirect and legacy-host state must be verified independently of repository
configuration.

## HISTORICAL/COMPATIBILITY

- The legacy hostname is retained during the migration window as the recorded
  rollback/redirect source.
- Cloudflare Pages may remain part of the live rollback path until WP-6 proves
  the Worker migration.
- `/Users/thor/Sites/wp-core-radar`, its Python path, and its six-hour scheduler
  cadence are current compatibility details documented in
  `docs/mac-mini-collector.md`; they are not core Radar architecture.
- Legacy raw archive layouts remain readable through recursive compatibility
  discovery. WP-2 added explicit selection for deterministic generation; WP-3
  made certification fail closed over selected inputs.

Architecture changes require an ADR or explicit amendment to
`docs/WORDPRESS-AUTOMATION-PROGRAM.md`; they must not enter through silent code
or documentation drift.
