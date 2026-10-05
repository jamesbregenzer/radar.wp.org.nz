# WP Core Radar Product

Status: **AUTHORITATIVE**

This document defines WP Core Radar's durable product boundary. Architecture changes require an Architecture Decision Record or an explicit update here.

## Purpose

WP Core Radar collects public WordPress Core Trac datasets and turns them into a current, ranked view of contribution opportunities. It validates each collection, normalizes ticket data, applies deterministic scoring rules, certifies the resulting dataset, and publishes reader-facing and machine-readable views.

Radar does not only ask which ticket is interesting. It also asks what useful public contribution appears to be missing: current PR testing, regression coverage, reproduction, patch verification, PR review, REST/API edge-case review, performance measurement, PHP compatibility verification, accessibility/UI verification, technical documentation review, follow-up after upstream change, stale but actionable refresh, or no clear nonduplicative contribution.

Radar is a standalone public project built around human review. It is independently useful. It does not modify WordPress.org, comment on Trac, submit patches, or hold WordPress.org contribution credentials.

Its machine-readable interfaces are public data products. The identity, architecture, behavior, or existence of any downstream system that reads those interfaces is outside Radar's product boundary and should not be described as part of Radar.

Radar observes and publishes public opportunity intelligence. Any human or tool
may consume the public API. No consumer is part of Radar's architecture.

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
| Frozen compatibility API | `https://radar.wp.org.nz/api/v1/` |
| Source-neutral API | `https://radar.wp.org.nz/api/v2/` |

The canonical repository is `jamesbregenzer/radar.wp.org.nz`.

## Durable rules

- Use one immutable run context for collection, validation, generation, certification, verification, and publication planning.
- Require every enabled query in a certifiable collection. Partial collections fail closed.
- Keep scoring, normalization, selection, and generation deterministic.
- Keep canonical hashes and source provenance with certified data.
- Describe likely contribution classes and proportionate evidence as advisory
  qualification derived from certified public ticket signals.
- For each certified opportunity, expose a public-safe contribution hypothesis
  with `recommendedContributionClass`, confidence, reason, evidence freshness,
  and source coverage.
- Treat `NO_CLEAR_CONTRIBUTION` as a noise-control class when public evidence
  shows the ticket is resolved, superseded, fully covered, or lacks a concrete
  nonduplicative contribution path.
- Preserve stable opportunity revisions when advisory qualification is added;
  live upstream validation remains required before anyone acts.
- Leave the previously certified dataset intact when a new run fails.
- Keep public output free of private notes, credentials, runtime details, and private downstream-system details.
- Treat HTTP as a projection, never as a second source of truth.
- Require users of machine-readable data to revalidate live Trac state before acting because Radar data can become stale.
- Keep downstream consumers outside the Radar product model; public Radar documentation must not advertise or imply any specific downstream consumer.
- Separate public resources from contribution opportunities. A resource is an
  upstream public object such as a Core Trac ticket, patch, wordpress-develop
  pull request, review, test result, or release signal. An opportunity is a
  source-neutral hypothesis that useful public contribution may be possible
  based on one or more resources.
- Certify source families independently. Fresh certified Core Trac data may be
  published even when another source family is stale, missing, or degraded, as
  long as the degraded family is reported truthfully.
- Keep discovery supply separate from qualification. Discovery decides what
  public work Radar observes. Qualification decides whether current public
  evidence shows a clear, possible, stale, covered, changed, or no-clear
  contribution opportunity.
- Make why-now, evidence coverage, limitations, freshness, deterministic
  ranking, and material opportunity revision part of public opportunity data.

## Collection boundary

The current collector retrieves configured Trac CSV exports through a local browser session, imports them into the raw archive, and removes temporary downloads. This implementation remains behind a collection contract so downstream Radar logic does not depend on a browser, host, scheduler, or local path.

Direct hosted HTTP collection is not supported unless it is separately proven reliable. Operational details belong in [`collection-operations.md`](collection-operations.md), not in the public product model.

## Source-neutral v2 boundary

`/api/v2/` is a public observation API. It preserves v1 Core Trac identity while
presenting opportunities as source-neutral records with a canonical resource,
supporting resources, contribution family, qualification state, coverage,
limitations, freshness, ranking dimensions, and deterministic material revision.

The current v2 source-family set is:

- `CORE_TRAC`: certified from the existing fail-closed Trac collection.
- `WORDPRESS_DEVELOP_GITHUB`: certified from a bounded public snapshot of
  recently updated open `WordPress/wordpress-develop` pull requests.

Gutenberg and public test/release signals should follow the same contract only
when a stable public source can be certified without weakening the existing
Trac collection.
