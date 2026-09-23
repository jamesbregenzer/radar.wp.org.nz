# WordPress Automation Program

Status: **AUTHORITATIVE — WP-1 PROGRAM FREEZE**

This document is the north-star architecture and roadmap for the WordPress
Automation Program. It distinguishes the current WP Core Radar implementation,
the target Radar architecture, the future private contributor, and the external
Federal Eagle Operations dependency.

If another document conflicts with this one, this document controls. Future
architecture changes require an Architecture Decision Record (ADR) or an
explicit update to this program plan. Architecture must not drift silently
through implementation changes.

## Mission and product boundaries

### Product 1 — WP Core Radar

WP Core Radar continuously collects WordPress Core Trac opportunity data,
validates it, deterministically normalizes, scores, and ranks it, produces
certified machine-readable opportunity data, and presents that information
through a dashboard, admin surface, and API.

The target application hostname is `radar.wp.org.nz`.

Radar contains no Eden or HWP logic, autonomous contribution logic, private
contributor credentials, work queues, or contribution execution authority.
Radar is independently useful without Federal Eagle.

### Product 2 — Private WordPress Contributor

The Private WordPress Contributor is a separate, private Federal Eagle
capability. It will:

1. consume certified Radar opportunities;
2. independently revalidate live WordPress state;
3. decide whether to abstain or work;
4. reproduce, test, and implement;
5. perform engineering and coordination QA;
6. create durable evidence;
7. route public-write authority through Eden/HWP policy;
8. deliver contributions only when authorized; and
9. monitor outcomes.

This product is not implemented in Radar.

### External dependency — Federal Eagle Operations

Runtime and execution are being redesigned separately. Radar and the future
contributor may express executor requirements, but they do not implement Thor
MCP, scheduling, credentials, host provisioning, or runtime routing.

## CURRENT IMPLEMENTATION

### Browser-assisted Trac collection

The known-working collector is an intentional compatibility constraint. Hosted
and server environments historically encountered unreliable or blocked Trac
collection. The proven implementation retrieves configured Trac CSV exports
through a browser session in an allowed local network environment, currently
associated with Thor.

The current browser collector:

1. opens configured Trac CSV searches in Firefox;
2. waits for the browser to download `query.csv`;
3. imports it into `data/raw/manual/YYYY-MM-DD/<query_slug>.csv`;
4. removes the temporary local browser download; and
5. allows GitHub to become durable truth after the resulting repository changes
   are published.

GitHub Actions or direct cloud HTTP collection must not be described as
supported until separately proven. Radar 2.0 must preserve this working path
while isolating it behind a collector/executor contract so downstream Radar
logic does not depend on how collection is performed.

### Current data and application flow

`scripts/run-radar.py` currently combines collection orchestration and output
generation. Shared Python code recursively discovers archived CSV files,
normalizes and scores tickets, and generates Markdown reports, dashboard HTML,
contribution history, and `docs/radar/admin-data.json`.

The scheduled compatibility wrapper pulls `main`, runs the browser-assisted
pipeline, verifies that all configured CSV exports exist with recognizable
headers, stages generated changes, suppresses timestamp-only commits, rebases,
and pushes. These host paths and scheduler mechanics are compatibility/runtime
details, not the target core architecture.

The repository contains a Cloudflare Worker plus Static Assets target
configuration. The established live hostname remains
`radar.james.bregenzer.dev` until the WP-6 migration is independently deployed
and verified.

### Durable truth

GitHub is Radar's durable source of truth after collection is published. A
future HTTP API is a projection of canonical, certified Radar data; it is not a
second source of truth.

`docs/radar/admin-data.json` is a current generated UI payload. It is not a
stable public machine API and must not become one accidentally.

## TARGET ARCHITECTURE

### Domain architecture

| Route | Target responsibility |
| --- | --- |
| `radar.wp.org.nz` | Radar application |
| `radar.wp.org.nz/admin/` | Protected Radar administration |
| `radar.wp.org.nz/api/v1/...` | Future certified machine-readable Radar API/feed |
| `wp.org.nz` | Future redirect to `https://wordpress.org/` |
| `www.wp.org.nz` | Future redirect to `https://wordpress.org/` |
| `radar.james.bregenzer.dev` | Redirected and retired after successful migration |

`jamesbregenzer/radar.wp.org.nz` is the proposed future repository name,
consistent with production-hostname naming conventions. The repository remains
`jamesbregenzer/wp-core-radar` unless and until WP-6 explicitly approves and
performs that optional rename.

### Radar 2.0 boundaries

Radar 2.0 will separate collection, validation, generation, certification,
verification, and publication. The browser collector remains valid but becomes
one implementation of an explicit collector/executor contract.

Dashboard, admin, report, and API/feed projections will consume one canonical
normalized opportunity model. Certification will fail closed when required
inputs, provenance, validation, or hashes are absent or invalid.

Radar publishes opportunity intelligence. It does not select work on behalf of
the private contributor, hold contributor credentials, or authorize public
WordPress writes.

## Frozen roadmap

1. **WP-1 Program Freeze** — this documentation and architecture PR.
2. **WP-2 Radar Core Hardening** — collector abstraction while preserving
   browser collection; deterministic time/input handling; single executable
   scoring configuration; explicit dataset selection; comprehensive fixture,
   unit, and pipeline tests; stronger collection evidence; isolate runtime
   assumptions.
3. **WP-3 Certified Radar Data** — `collection.v1`, `snapshot.v1`,
   `opportunity.v1`, `execution-result.v1`, canonical hashing/provenance, and
   fail-closed certification.
4. **WP-4 Stable Radar Operations** — `collect`, `validate-collection`,
   `generate`, `certify`, `verify`, `publish`, and `pipeline` application
   entrypoints with structured results.
5. **WP-5 Machine Feed + UI Alignment** — API/feed from certified data;
   dashboard/admin consume the same canonical opportunity model; provenance and
   health UI.
6. **WP-6 Radar Migration** — optional repository rename to
   `radar.wp.org.nz`; deploy the canonical Worker; migrate to
   `radar.wp.org.nz`; protect appropriate surfaces; redirect apex and `www` to
   WordPress.org; redirect and retire the old Radar hostname.
7. **WP-7 Private Contributor Contract.**
8. **WP-8 Private Contributor Implementation** — initially patch testing and
   reproduction.
9. **WP-9 Shadow/evidence mode.**
10. **WP-10 Governed contribution delivery and evidence-earned expansion.**

## WP-2 deep-review backlog

The following are confirmed improvement targets. They are recorded here, not
implemented by WP-1:

- keep the valid browser collector but make it replaceable behind a contract;
- separate collection from generation in `run-radar.py`;
- extend collector verification beyond file/header presence to richer
  provenance and evidence;
- eliminate the two scoring sources of truth: `config/scoring.yaml` currently
  documents rules while executable scoring lives in Python;
- replace direct `datetime.now()` dependencies with deterministic time/input
  handling and remove the need for timestamp-only commit workarounds;
- replace permissive recursive CSV discovery with explicit certified dataset
  selection;
- make dashboard, report, admin, and API/feed use one canonical normalized
  opportunity model;
- prevent `admin-data.json` from becoming the stable machine API;
- add sufficient fixture, unit, contract, and end-to-end pipeline coverage for
  autonomous machine consumption;
- review and harden CI/workflow behavior;
- review generated-file churn in the review-refresh workflow; and
- move runtime paths and scheduler details into compatibility/runtime layers
  instead of core Radar architecture.

## Program guardrails

- Preserve the proven browser-assisted collector until a replacement is proven
  in the required environment.
- GitHub remains Radar's durable source of truth.
- Radar remains independently useful without Federal Eagle.
- Radar data does not grant contribution execution authority.
- The private contributor independently revalidates live WordPress state and
  may abstain at every gate.
- Public writes require Eden/HWP policy authorization and evidence.
- Federal Eagle Operations owns execution mechanics; product repositories state
  requirements without absorbing runtime implementation.
- Architecture changes require an ADR or explicit amendment to this document.
