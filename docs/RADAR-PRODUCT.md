# WP Core Radar Product Boundary

Status: **AUTHORITATIVE**

This document defines WP Core Radar's public product boundary and architectural
rules. If another current document conflicts with it, this document controls.
Architecture changes require an Architecture Decision Record (ADR) or an
explicit update here; they must not enter through silent implementation drift.

## Mission

WP Core Radar continuously collects public WordPress Core Trac opportunity
data, validates it, deterministically normalizes, scores, and ranks it, produces
certified machine-readable opportunity data, and presents that information
through a dashboard, protected administration surface, reports, and a
versioned API.

Radar is a complete, independently useful public product. It discovers and
presents contribution opportunities; it does not modify WordPress.org, comment
on Trac, submit patches, or hold WordPress.org contribution credentials.

## Durable truth and projections

GitHub is Radar's durable source of truth after a collection is published.
`data/certified/current/` contains the canonical verified bundle. HTTP API,
dashboard, admin, and report output are read-only or deterministic projections
of committed Radar data, not additional authorities.

`docs/radar/admin-data.json` is a generated UI payload, not the stable machine
API. Mutable review state is a separate durable overlay and must not silently
change an immutable certified snapshot.

## Collection constraint

The proven collector retrieves configured Trac CSV exports through a local
Firefox browser session because hosted/server collection has historically been
unreliable or blocked. It:

1. opens every configured enabled Trac CSV search;
2. downloads `query.csv`;
3. imports it into `data/raw/manual/<collection-id>/<query-slug>.csv`;
4. removes the temporary browser download; and
5. allows GitHub to become durable truth only after validation and publication.

One scheduled run freezes a single reference time, collection identity, source
revision, and required query set before collection. Every collection,
validation, generation, certification, verification, and publication-planning
stage uses that context even across a date boundary. A collecting canonical
pipeline must successfully collect every enabled required query; partial
collections cannot become certifiable.

Direct cloud HTTP or GitHub Actions collection is not supported unless proven
separately. The browser collector remains replaceable behind Radar's generic
collector/executor contracts so core logic does not depend on a host or browser.

## Application topology

| Route | Responsibility |
| --- | --- |
| `https://radar.wp.org.nz/` | Protected Radar dashboard |
| `https://radar.wp.org.nz/contributions/` | Protected contribution history |
| `https://radar.wp.org.nz/admin/` | Protected Radar administration |
| `https://radar.wp.org.nz/api/v1/...` | Protected certified machine-readable API |

The canonical repository is `jamesbregenzer/radar.wp.org.nz`. The Worker serves
committed Static Assets and verified certified API artifacts. It does not
rescore data, fetch live Trac data, or depend on GitHub for normal runtime reads.
The API is private by default in the current production deployment, while its
payload remains public-safe because access control is not the secrecy model.

## Runtime and write boundaries

Radar core owns deterministic collection, validation, normalization, scoring,
certification, verification, rendering, and structured operation results.
Generic external execution supplies process scheduling, browser availability,
time and revision injection, provider credentials, repository publication,
monitoring, and retry behavior.

The deployed admin reads credential-free static projections. Durable review and
props writes are abstract executor requirements and fail closed with
`EXECUTOR_UNAVAILABLE` until implemented. Radar never reports an unpersisted
write as successful and does not store provider credentials in source.

## Implemented roadmap

1. **WP-1 Product Freeze** — product boundary and architectural guardrails.
2. **WP-2 Core Hardening** — collector abstraction, deterministic inputs,
   executable scoring configuration, explicit dataset selection, and tests.
3. **WP-3 Certified Data** — versioned schemas, canonical hashes and provenance,
   fail-closed certification, and offline verification.
4. **WP-4 Stable Operations** — structured collect, validate, generate, certify,
   verify, publish-plan, and pipeline entrypoints.
5. **WP-5 Machine Feed + UI Alignment** — versioned API and human projections
   backed by the same certified opportunity model.
6. **WP-6 Production Migration** — canonical repository/hostname, Worker Static
   Assets delivery, Access boundary, redirects, acceptance, and rollback.

## Guardrails

- Preserve the proven browser-assisted collector until a replacement is proven.
- Keep scoring, selection, certification, and generation deterministic.
- Fail closed on missing queries, invalid provenance, malformed artifacts, or
  hash/identity mismatch.
- Keep GitHub as durable truth and HTTP as a projection.
- Keep certified snapshot content immutable; treat review state as an overlay.
- Keep generated public data free of private notes and secrets.
- Require consumers to independently revalidate live WordPress/Trac state
  before acting; Radar data may be stale and is not contribution authorization.
- Keep runtime/provider implementation details outside Radar core.
- Require an ADR or explicit update to this document for architecture changes.
