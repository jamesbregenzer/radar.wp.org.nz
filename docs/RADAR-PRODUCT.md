# WP Core Radar Product

Status: **AUTHORITATIVE**

This document defines WP Core Radar's durable product boundary. Architecture changes require an Architecture Decision Record or an explicit update here.

## Purpose

WP Core Radar collects public WordPress Core Trac datasets and turns them into a current, ranked view of contribution opportunities. It validates each collection, normalizes ticket data, applies deterministic scoring rules, certifies the resulting dataset, and publishes human and machine-readable views.

Radar is independently useful. It does not modify WordPress.org, comment on Trac, submit patches, or hold WordPress.org contribution credentials.

## Source of truth

GitHub is durable truth after publication.

- Raw collected data is archived under `data/raw/`.
- `data/certified/current/` contains the verified current collection, snapshot, opportunities, and manifest.
- The dashboard, reports, admin data, and HTTP API are projections of committed data.
- `docs/radar/admin-data.json` is a generated UI payload, not a stable API.
- Review state is a separate mutable overlay and does not alter an already certified snapshot.

## Product interfaces

| Interface | Location |
| --- | --- |
| Public dashboard | `https://radar.wp.org.nz/` |
| Contribution history | `https://radar.wp.org.nz/contributions/` |
| Admin login | `https://radar.wp.org.nz/admin/` |
| Machine-readable API | `https://radar.wp.org.nz/api/v1/` |

The canonical repository is `jamesbregenzer/radar.wp.org.nz`.

## Durable rules

- Use one immutable run context for collection, validation, generation, certification, verification, and publication planning.
- Require every enabled query in a certifiable collection. Partial collections fail closed.
- Keep scoring, normalization, selection, and generation deterministic.
- Keep canonical hashes and source provenance with certified data.
- Leave the previously certified dataset intact when a new run fails.
- Keep public output free of private notes, credentials, and runtime details.
- Treat HTTP as a projection, never as a second source of truth.
- Require consumers to revalidate live Trac state before acting because Radar data can become stale.

## Collection boundary

The current collector retrieves configured Trac CSV exports through a local browser session, imports them into the raw archive, and removes temporary downloads. This implementation remains behind a collection contract so downstream Radar logic does not depend on a browser, host, scheduler, or local path.

Direct hosted HTTP collection is not supported unless it is separately proven reliable. Operational details belong in [`collection-operations.md`](collection-operations.md), not in the public product model.
