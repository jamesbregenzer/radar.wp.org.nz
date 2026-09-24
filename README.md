<p align="center">
  <img src="docs/assets/banner.svg" alt="WP Core Radar — A scheduled intelligence dashboard for finding approachable WordPress Core contribution opportunities.">
</p>

<p align="center">
  <img alt="Project Status" src="https://img.shields.io/badge/status-active-brightgreen">
  <img alt="Built with Python" src="https://img.shields.io/badge/python-3.14-blue">
  <img alt="Cloudflare Pages" src="https://img.shields.io/badge/deploy-Cloudflare%20Pages-f38020">
  <img alt="Cloudflare Worker" src="https://img.shields.io/badge/admin-Cloudflare%20Worker-f38020">
  <img alt="WordPress Core" src="https://img.shields.io/badge/focus-WordPress%20Core-21759b">
  <img alt="Maintained by James Bregenzer" src="https://img.shields.io/badge/maintained%20by-James%20Bregenzer-111827">
</p>

# WP Core Radar

WP Core Radar is an independent public product for deterministic WordPress Core
contribution discovery and prioritization. Its authoritative product boundary
and architectural rules live in
[`docs/RADAR-PRODUCT.md`](docs/RADAR-PRODUCT.md).

**Canonical production hostname:** `https://radar.wp.org.nz/`, protected by
Cloudflare Access. The machine API is private by default in the current
production deployment.

It collects public ticket data from WordPress Trac, archives raw CSV exports,
scores opportunities with explainable rules including freshness and activity
momentum, and publishes a Radar dashboard, contribution history page, and
protected review console so a human contributor can decide what to test, watch,
reject, or act on manually. WP-6 places all production HTTP surfaces behind
Cloudflare Access while keeping repository data public-safe.

Freshness and ticket-age signals are calculated from Trac `Created`/`Modified` timestamps, including Trac's AM/PM CSV format. Momentum is calculated when a collected CSV includes a usable comment-count field; when Trac does not provide that field, Radar leaves momentum out instead of inventing it.

## What this project is

WP Core Radar helps answer:

- Which WordPress Core tickets are worth reviewing today?
- Which tickets look like good patch-testing opportunities?
- Which tickets are fresh or recently active enough to be worth prioritizing now?
- Which opportunities have clear signals such as patches, testing needs, owner activity, or feedback requests?
- Which tickets have already been reviewed, rejected, watched, tested, commented on, or completed?

## What this project is not

WP Core Radar discovers, scores, and presents WordPress Core contribution
opportunities. It does not modify WordPress.org, comment on Trac, submit
patches, or hold WordPress.org contribution credentials.

## CURRENT IMPLEMENTATION

```text
WordPress Trac
  → Mac Mini browser-assisted collector
  → archived raw CSV datasets
  → validated collection evidence + explicit run context
  → canonical opportunity normalization, deterministic scoring, and grouping
  → Markdown report + Radar dashboard + contribution history + admin data JSON
  → GitHub repository
  → current live delivery and committed Cloudflare Worker target

Review state
  → canonical data/reviews/reviews.json in GitHub
  → deterministic safe deployed review-state projection
  → credential-free /admin/ runtime reads

Admin write intent
  → PERSIST_REVIEW_DECISION or RECORD_PROPS_OUTCOME
  → external governed executor (not implemented in Radar)
  → durable GitHub state
```

The local browser collection environment is used because hosted/server Trac
collection has historically been unreliable or blocked. It opens configured
Trac CSV searches in Firefox, downloads `query.csv`, imports it into the raw
archive, and removes the temporary download. This proven browser-assisted
collection path must be preserved until a replacement is proven.

The scheduled wrapper freezes one reference time, collection identity, source
revision, and required query set before collection begins. Browser imports and
every downstream fail-closed stage receive that same context, so crossing a UTC
date boundary cannot split one collection across archive identities. Failed
attempts retain ignored local evidence and restore attempted repository changes
before the next scheduled pull.

After publication, GitHub is Radar's durable source of truth. The repository
contains the migration-ready Cloudflare Worker plus Static Assets target. The
legacy hostname remains a rollback/redirect concern until the governed WP-6
cutover is deployed and accepted; committed configuration is not proof of a
production change.

The collector/build runner creates the admin **data export** at `docs/radar/admin-data.json`. It does not create or serve the protected admin page. The admin UI is rendered by the Cloudflare Worker. `admin-data.json` is a current UI payload, not a stable machine API.

WP-6A removes synchronous GitHub access from the Worker. Generation publishes
`docs/radar/review-state.json` from canonical review state. The projection contains
status/reason/outcome metadata but excludes free-form private notes. Until an
external governed executor satisfies the write contracts, admin write attempts
fail closed and explicitly report that nothing was persisted.

## Public and protected routes

```text
https://radar.wp.org.nz/                Protected static dashboard generated into docs/radar/index.html
https://radar.wp.org.nz/contributions/ Protected contribution history generated into docs/radar/contributions/index.html
https://radar.wp.org.nz/admin/         Protected Worker-rendered admin console
https://radar.wp.org.nz/api/v1/...     Protected certified machine interface
```

The Radar dashboard includes **Contributions** and **Admin Console** links in the header. Those links are generated by `scripts/generate-dashboard.py` and are routed by the Cloudflare Worker.

The protected admin console authenticates in the Worker and reads only deployed
Static Assets: `docs/radar/admin-data.json` plus the safe
`docs/radar/review-state.json` overlay. It makes no GitHub API request while
rendering. Review and props forms express bounded write intents, but writes fail
closed with `EXECUTOR_UNAVAILABLE` until an external governed executor is
available; Radar never implies persistence succeeded.

## TARGET ARCHITECTURE

The target application hostname is `radar.wp.org.nz`, with protected Radar
administration at `/admin/` and the certified machine-readable API/feed at
`/api/v1/...`. The apex and `www` hosts will redirect to
`https://wordpress.org/`; the old Radar hostname will be redirected only after
the canonical host passes production acceptance.

WP-2 isolates the current browser implementation behind a collector/result
boundary, supplies deterministic time and explicit dataset selection, uses one
executable scoring configuration, and gives every current renderer one
canonical internal opportunity model. WP-3 adds versioned schemas and
fail-closed certification. WP-4 adds stable structured operations and a
fail-closed pipeline; WP-5 will add the certified API/feed. GitHub remains
durable truth; HTTP is a projection.

WP-3 adds the certified machine-data layer: strict versioned schemas,
deterministic canonical JSON and identities, complete source provenance,
fail-closed certification, and offline verification. The current certified
bundle lives in `data/certified/current/`; it is the future API's source, not an
HTTP API implementation itself.

WP-5 adds the Worker-projected certified machine interface:

- `GET /api/v1/health`
- `GET /api/v1/snapshot`
- `GET /api/v1/collection`
- `GET /api/v1/opportunities`
- `GET /api/v1/opportunities/{ticket_id}`

The feed, dashboard, protected admin projection, and report use the verified
certified opportunity model. GitHub remains durable truth; HTTP is a cached
projection. See [`docs/contracts/machine-feed.md`](docs/contracts/machine-feed.md).

The approved target repository name is `jamesbregenzer/radar.wp.org.nz`. WP-6
makes application code portable and migration-ready, but the current repository
must be renamed through GitHub repository settings after the PR merges and
after governed custody dependencies are ready. See
[`docs/WP-6-RADAR-PRODUCTION-MIGRATION.md`](docs/WP-6-RADAR-PRODUCTION-MIGRATION.md).

## Main commands

The canonical WP-4 interface is `scripts/radar.py`. Every operation requires an
explicit reference time and emits one validated `execution-result.v1` JSON
document to stdout:

```bash
python3 scripts/radar.py validate-collection --collection-id 2026-01-15 --reference-time 2026-01-15T12:00:00Z
python3 scripts/radar.py generate --collection-id 2026-01-15 --reference-time 2026-01-15T12:00:00Z
python3 scripts/radar.py certify --collection-id 2026-01-15 --source-revision 0123456789abcdef0123456789abcdef01234567 --reference-time 2026-01-15T12:00:00Z
python3 scripts/radar.py verify --reference-time 2026-01-15T12:00:00Z
python3 scripts/radar.py publish --reference-time 2026-01-15T12:00:00Z
python3 scripts/radar.py pipeline --skip-collect --collection-id 2026-01-15 --source-revision 0123456789abcdef0123456789abcdef01234567 --reference-time 2026-01-15T12:00:00Z
```

`publish` only returns a verified artifact/identity plan. It never authenticates,
commits, pushes, deploys, or schedules. See
[`docs/contracts/executor.md`](docs/contracts/executor.md).

The commands below remain supported compatibility interfaces:

Run the full pipeline:

```bash
python3 scripts/run-radar.py
```

Regenerate reports and dashboard files without fetching new Trac data:

```bash
python3 scripts/run-radar.py --skip-fetch
```

For reproducible generation, supply one ISO-8601 run time to the whole pipeline:

```bash
python3 scripts/run-radar.py --skip-fetch --reference-time 2026-01-15T12:00:00Z
```

Run one configured query:

```bash
python3 scripts/run-radar.py --query general_needs_testing
```

Generate only the Radar dashboard and admin data export:

```bash
python3 scripts/generate-dashboard.py
```

Generate only the Markdown report:

```bash
python3 scripts/generate-report.py
```

Verify the committed certified dataset without network or browser access:

```bash
python3 scripts/radar.py verify --reference-time 2026-01-15T12:00:00Z
```

Record a review decision locally:

```bash
python3 scripts/review-ticket.py 33073 shortlist "Good first contribution candidate"
```

The local review command updates `data/reviews/reviews.json` directly and regenerates `docs/radar/index.html` plus `docs/radar/admin-data.json` so local review grouping does not become stale. In production, the protected `/admin/` Worker console is currently read-only at the durable-state boundary. Review/props writes require the external executor contract and fail closed until that capability exists.

## Review workflow

The protected Cloudflare Worker admin console is available at
`https://radar.wp.org.nz/admin/` for credential-free deployed reads. Durable
review and props persistence is currently unavailable and its controls are
clearly marked read-only. Props are not a review decision; once the executor
contract is implemented, they remain a separate outcome recorded after
contributor credit appears on WordPress.org.
Historical props can be recorded even when a ticket no longer appears in the
current Trac CSV exports.

For local-only maintenance or recovery work, `scripts/review-ticket.py` can update `data/reviews/reviews.json` directly. The local script regenerates dashboard files immediately by default. Production admin write requests fail closed with `EXECUTOR_UNAVAILABLE`; they do not create local-only state or trigger regeneration.

## Outputs

- `docs/radar/index.html` is the static Radar dashboard asset.
- `docs/radar/contributions/index.html` is the static contribution history asset.
- `docs/radar/admin-data.json` is the static opportunity payload used by the protected Worker admin console.
- `docs/radar/review-state.json` is the safe deployed review overlay; it excludes free-form private notes.
- `reports/latest.md` is the latest Markdown report.
- `reports/radar-YYYY-MM-DD.md` is the dated Markdown report.
- `data/reviews/reviews.json` stores human review decisions and props outcomes as constrained metadata keyed by ticket ID.
- `data/outcomes/outcomes.csv` stores older/manual scoring outcomes used to avoid repeatedly recommending tickets that already produced props or were already tested.
- `data/raw/manual/YYYY-MM-DD/<query_slug>.csv` stores archived Trac CSV exports.

## CURRENT IMPLEMENTATION — deployment and security boundaries

The canonical production hostname is `https://radar.wp.org.nz/`. The historical
Cloudflare Pages project remains an explicit rollback path; repository code has
no Pages-origin dependency. The contribution history page is served at
`/contributions/` on the same host and follows the human Access policy.

The protected `/admin/` route is rendered by a Cloudflare Worker. It should use narrowly scoped secrets configured in Cloudflare, not committed to this repository:

- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`

Admin reads are credential-free and use the deployed safe review-state projection.
Radar does not require a GitHub credential at Worker runtime. Durable admin writes
are intentionally executor-owned and fail closed until that executor capability exists.

The canonical repository after the governed rename is
`jamesbregenzer/radar.wp.org.nz`. The Worker does not require repository
identity or GitHub credentials at runtime.

The Worker remains narrowly scoped to deployed projections and application authentication. It does not edit repository files. Future persistence must satisfy the executor contract without adding provider credentials to Radar's runtime.

Local helper scripts may be committed when they contain no secrets and do not expose a public service. Secrets, passwords, API tokens, and Cloudflare Worker environment variables must never be committed.

## Project docs

- `docs/architecture.md` — system architecture, routing, and boundaries
- `docs/RADAR-PRODUCT.md` — authoritative Radar product boundary, architecture rules, and roadmap
- `docs/WP-2-CORE-HARDENING.md` — WP-2 implementation record, runtime classification, and deferrals
- `docs/WP-3-CERTIFIED-RADAR-DATA.md` — schemas, canonicalization, certification, retention, and verification
- `docs/WP-4-STABLE-RADAR-OPERATIONS.md` — stable operation behavior, failures, and idempotency
- `docs/WP-5-MACHINE-FEED-UI-ALIGNMENT.md` — feed/UI implementation and WP-6 handoff
- `docs/WP-6-RADAR-PRODUCTION-MIGRATION.md` — production topology, cutover, acceptance, rollback, and human actions
- `docs/contracts/executor.md` — executor-facing invocation and custody contract
- `docs/contracts/machine-feed.md` — frozen `/api/v1/` consumer contract
- `docs/mac-mini-collector.md` — local collection and scheduled runner workflow
- `.github/workflows/refresh-dashboard.yml` — near-real-time dashboard refresh after review saves
- `cloudflare/worker-radar.js` — production Worker source for public routing and protected admin UI
- `docs/scoring-rubric.md` — deterministic scoring rules
- `docs/outcome-tracking.md` — review and contribution state
- `docs/failed-approaches.md` — decisions not to repeat without a clear reason
- `docs/vision.md` — product and technical direction

Future architecture changes require an ADR or an explicit update to the authoritative program document rather than silent drift.
