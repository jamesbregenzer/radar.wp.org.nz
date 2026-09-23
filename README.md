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

WP Core Radar is a deterministic, human-in-the-loop contribution discovery and prioritization workflow for WordPress Core tickets.

The authoritative architecture, product boundaries, and frozen roadmap for the
broader WordPress Automation Program are in
[`docs/WORDPRESS-AUTOMATION-PROGRAM.md`](docs/WORDPRESS-AUTOMATION-PROGRAM.md).

**Live project:** [View the WP Core Radar public dashboard](https://radar.james.bregenzer.dev/)

It collects public ticket data from WordPress Trac, archives raw CSV exports, scores opportunities with explainable rules including freshness and activity momentum, and publishes a public dashboard, public contribution history page, plus a protected review console so a human contributor can decide what to test, watch, reject, or act on manually.

Freshness and ticket-age signals are calculated from Trac `Created`/`Modified` timestamps, including Trac's AM/PM CSV format. Momentum is calculated when a collected CSV includes a usable comment-count field; when Trac does not provide that field, Radar leaves momentum out instead of inventing it.

## What this project is

WP Core Radar helps answer:

- Which WordPress Core tickets are worth reviewing today?
- Which tickets look like good patch-testing opportunities?
- Which tickets are fresh or recently active enough to be worth prioritizing now?
- Which opportunities have clear signals such as patches, testing needs, owner activity, or feedback requests?
- Which tickets have already been reviewed, rejected, watched, tested, commented on, or completed?

## What this project is not

WP Core Radar does not auto-comment on Trac, automate contribution activity, hold private contributor credentials, manage autonomous work queues, or bypass WordPress.org access controls. A future private Federal Eagle WordPress Contributor is a separate product and is not implemented in Radar.

## CURRENT IMPLEMENTATION

```text
WordPress Trac
  → Mac Mini browser-assisted collector
  → archived raw CSV datasets
  → validated collection evidence + explicit run context
  → canonical opportunity normalization, deterministic scoring, and grouping
  → Markdown report + public dashboard + contribution history + admin data JSON
  → GitHub repository
  → current live delivery and committed Cloudflare Worker target

Review saves from /admin/
  → data/reviews/reviews.json
  → GitHub Action dashboard refresh
  → regenerated docs/radar/index.html + docs/radar/contributions/index.html + docs/radar/admin-data.json
  → committed generated output
```

The local browser environment currently associated with Thor is the collection/build runner because hosted/server Trac collection has historically been unreliable or blocked. It opens configured Trac CSV searches in Firefox, downloads `query.csv`, imports it into the raw archive, and removes the temporary download. This proven browser-assisted collection path must be preserved until a replacement is proven.

After publication, GitHub is Radar's durable source of truth. The repository now contains a Cloudflare Worker plus Static Assets target, but the established live hostname remains `radar.james.bregenzer.dev` until the WP-6 migration is deployed and verified. Committed target configuration must not be confused with completed production migration.

The collector/build runner creates the admin **data export** at `docs/radar/admin-data.json`. It does not create or serve the protected admin page. The admin UI is rendered by the Cloudflare Worker. `admin-data.json` is a current UI payload, not a stable machine API.

Review-only updates use a separate near-real-time path. When the protected admin console commits a change to `data/reviews/reviews.json`, the `Refresh dashboard after review update` GitHub Action regenerates `docs/radar/index.html`, `docs/radar/contributions/index.html`, and `docs/radar/admin-data.json` so public contribution history and admin grouping stay accurate without waiting for the next Mac Mini collection run.

## Public and protected routes

```text
https://radar.james.bregenzer.dev/                Public static dashboard generated into docs/radar/index.html
https://radar.james.bregenzer.dev/contributions/ Public static contribution history generated into docs/radar/contributions/index.html
https://radar.james.bregenzer.dev/admin/         Protected Worker-rendered admin console
```

The public dashboard includes **Contributions** and **Admin Console** links in the header. Those links are generated by `scripts/generate-dashboard.py` and are routed by the Cloudflare Worker.

The protected admin console authenticates in the Worker, reads the committed `docs/radar/admin-data.json` asset, and writes constrained review metadata only to `data/reviews/reviews.json` through the GitHub API. It supports normal ticket review decisions plus a dedicated historical props workflow for tickets that are no longer present in the current opportunity export. It does not regenerate dashboard files directly. Dashboard regeneration after review saves is handled by GitHub Actions so the Worker stays narrowly scoped.

## TARGET ARCHITECTURE

The target application hostname is `radar.wp.org.nz`, with protected Radar administration at `/admin/` and a future certified machine-readable API/feed at `/api/v1/...`. The apex and `www` hosts will redirect to `https://wordpress.org/`; the old Radar hostname will be redirected and retired after successful migration.

WP-2 isolates the current browser implementation behind a collector/result
boundary, supplies deterministic time and explicit dataset selection, uses one
executable scoring configuration, and gives every current renderer one
canonical internal opportunity model. WP-3 will add versioned schemas and
fail-closed certification; WP-5 will add the certified API/feed. GitHub remains
durable truth; HTTP is a projection.

The proposed future repository name is `jamesbregenzer/radar.wp.org.nz`. The current repository remains `jamesbregenzer/wp-core-radar`; no rename is part of WP-1.

## Main commands

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

Generate only the public dashboard and admin data export:

```bash
python3 scripts/generate-dashboard.py
```

Generate only the Markdown report:

```bash
python3 scripts/generate-report.py
```

Record a review decision locally:

```bash
python3 scripts/review-ticket.py 33073 shortlist "Good first contribution candidate"
```

The local review command updates `data/reviews/reviews.json` directly and regenerates `docs/radar/index.html` plus `docs/radar/admin-data.json` so local review grouping does not become stale. In production, review decisions should normally be recorded through the protected `/admin/` Worker console.

## Review workflow

Normal review decisions should be made in the protected Cloudflare Worker admin console at `https://radar.james.bregenzer.dev/admin/`. Props are not a review decision; they are recorded through the separate **Record props** workflow after contributor credit appears on WordPress.org. Historical props can be recorded even when a ticket no longer appears in the current Trac CSV exports.

For local-only maintenance or recovery work, `scripts/review-ticket.py` can update `data/reviews/reviews.json` directly. The local script regenerates dashboard files immediately by default. If a review is saved through the production admin console, GitHub Actions performs that regeneration after the review commit lands on `main`.

## Outputs

- `docs/radar/index.html` is the public static dashboard.
- `docs/radar/contributions/index.html` is the public static contribution history page.
- `docs/radar/admin-data.json` is the static data payload used by the protected Worker admin console.
- `reports/latest.md` is the latest Markdown report.
- `reports/radar-YYYY-MM-DD.md` is the dated Markdown report.
- `data/reviews/reviews.json` stores human review decisions and props outcomes as constrained metadata keyed by ticket ID.
- `data/outcomes/outcomes.csv` stores older/manual scoring outcomes used to avoid repeatedly recommending tickets that already produced props or were already tested.
- `data/raw/manual/YYYY-MM-DD/<query_slug>.csv` stores archived Trac CSV exports.

## CURRENT IMPLEMENTATION — deployment and security boundaries

The established public dashboard remains at `https://radar.james.bregenzer.dev/` during migration. Cloudflare Pages may remain a rollback dependency until the canonical Worker migration is proven. The public contribution history page is served at `/contributions/` on the same host.

The protected `/admin/` route is rendered by a Cloudflare Worker. It should use narrowly scoped secrets configured in Cloudflare, not committed to this repository:

- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `GITHUB_TOKEN`

The Worker should remain narrowly scoped. It may read the generated admin data JSON and update `data/reviews/reviews.json`; it should not become a general-purpose repository editor. Review-save dashboard regeneration belongs in GitHub Actions, not in the Worker.

Local helper scripts may be committed when they contain no secrets and do not expose a public service. Secrets, passwords, API tokens, and Cloudflare Worker environment variables must never be committed.

## Project docs

- `docs/architecture.md` — system architecture, routing, and boundaries
- `docs/WORDPRESS-AUTOMATION-PROGRAM.md` — authoritative program architecture, product boundaries, guardrails, and roadmap
- `docs/WP-2-CORE-HARDENING.md` — WP-2 implementation record, runtime classification, and deferrals
- `docs/mac-mini-collector.md` — local collection and scheduled runner workflow
- `.github/workflows/refresh-dashboard.yml` — near-real-time dashboard refresh after review saves
- `cloudflare/worker-radar.js` — production Worker source for public routing and protected admin UI
- `docs/scoring-rubric.md` — deterministic scoring rules
- `docs/outcome-tracking.md` — review and contribution state
- `docs/failed-approaches.md` — decisions not to repeat without a clear reason
- `docs/vision.md` — product and technical direction

Future architecture changes require an ADR or an explicit update to the authoritative program document rather than silent drift.
