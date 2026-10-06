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
- Core Trac raw CSV acquisitions include immutable source receipt sidecars with
  exact source URL, retrieval timestamp, raw SHA-256, acquisition ID, receipt
  path, and parser metadata.
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

- Use one immutable run context for collection, validation, generation, certification, verification, and publication planning. V2 observations must also carry a per-run observation identity so multiple observations on the same date do not collapse into one source-family identity.
- Require every enabled query in the frozen v1 certifiable collection. V2 source-family shards certify independently: a failed secondary shard must report failure and lower completeness without pretending to be fresh or complete.
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
- Do not infer cross-source resource identity from numeric coincidence. A
  GitHub `#12345` reference is ambiguous unless accompanied by repo-aware or
  canonical public evidence.
- Publish public candidates as source-neutral machine records. A candidate is a
  public evidence bundle for downstream qualification; it is not final
  qualification, executable work, a schedule, or delivery authority.
- Retain multidimensional score vectors separately from the derived scalar
  priority. Unknown dimensions stay unknown, and a scalar priority cannot
  override failed eligibility, safety, or source-integrity gates.

## Collection boundary

The current collector retrieves configured Trac CSV exports through a local browser session, imports them into the raw archive, and removes temporary downloads. This implementation remains behind a collection contract so downstream Radar logic does not depend on a browser, host, scheduler, or local path.

Direct hosted HTTP collection is not supported unless it is separately proven reliable. Operational details belong in [`collection-operations.md`](collection-operations.md), not in the public product model.

## Source-neutral v2 boundary

`/api/v2/` is a pre-production public observation contract until a fresh
quality-yield sample demonstrates useful, nonduplicative contribution
intelligence. It preserves v1 compatibility while presenting resources,
relationships, and opportunities as separate public concepts.

A resource is a public upstream object with a family-qualified identity,
canonical URL, upstream state, observed material revision, observed time,
source-family snapshot identity, provenance, completeness, limitations, and a
deterministic hash. A resource is not an opportunity merely because it exists.

A relationship is a typed public edge between resources. Supported relationship
types are `IMPLEMENTS`, `REFERENCES`, `DUPLICATES`, `SUPERSEDES`,
`RELATED_TO`, `TESTS`, `REVIEW_OF`, `CI_FOR`, `PATCH_FOR`, and
`RELEASE_SIGNAL_FOR`. Every relationship must carry public provenance. Unknown
or ambiguous relations stay absent rather than becoming false graph edges.

An opportunity is a source-neutral missing contribution increment over a
resource cluster. One resource cluster can yield zero, one, or many
opportunities. Opportunity identity is separate from resource identity and from
material revision; v1 Core Trac keys remain available only as legacy
compatibility fields.

A candidate is the public machine-readable projection designed for downstream
qualification. It includes a canonical candidate ID, resource refs,
relationships, contribution-family candidates with confidence, a score vector,
derived ranking, source revision, freshness, source health, change information,
and candidate explanation. Candidate feeds are exposed at `/api/v2/candidates`
and `/api/v2/candidate-feed`.

The versioned contribution-family registry is exposed at
`/api/v2/contribution-families`. The initial source-neutral families are:
`CORE_CODE_REVIEW`, `CORE_PATCH_TEST`, `CORE_BUG_REPRODUCTION`,
`CORE_REGRESSION_TEST`, `CORE_PATCH_IMPLEMENTATION`,
`CORE_AUTOMATED_TEST`, `CORE_BUG_GARDENING`, `CORE_INLINE_DOCS`,
`GUTENBERG_CODE_REVIEW`, `GUTENBERG_TEST`, `GUTENBERG_REPRODUCTION`,
`GUTENBERG_PATCH`, `ACCESSIBILITY_TEST`, `BETA_RC_TEST`,
`PERFORMANCE_INVESTIGATION`, `DOCS_REVIEW`, `HANDBOOK_UPDATE`,
`PATHWAY_REVIEW`, `LEARN_TECHNICAL_REVIEW`, `THEME_CHECK_CODE`,
`THEME_CHECK_TRIAGE`, and `THEME_REVIEW`.

The scoring contract is exposed at `/api/v2/scoring`. Each candidate keeps
`upstreamDemandStrength`, `expectedUpstreamImpact`, `jamesAffinity`,
`noveltyConfidence`, `evidenceFeasibility`, `timeliness`,
`estimatedExecutionCost`, and `deliveryReputationalRisk` as separate dimension
records with value, confidence, source evidence, and explanation.

The current v2 source-family set is:

- `CORE_TRAC`: certified from the existing fail-closed Trac collection.
- `WORDPRESS_DEVELOP_GITHUB`: certified from a bounded public snapshot of
  recently updated open `WordPress/wordpress-develop` pull requests.
- `GUTENBERG`: certified from bounded public snapshots of recently updated open
  `WordPress/gutenberg` issues and pull requests.

Public test/release signals should follow the same contract only when a stable
public source can be certified without weakening existing source families.

V2 source-native opportunity production is allowed when a non-Trac resource has
specific public evidence for a missing contribution increment. Current native
signals include public testing labels, review requests, accessibility/API/
performance cues, public bug labels, and stale but active public discussion.
Radar must suppress or omit resources where the only fact is that a PR or issue
exists.

## Current v2 architecture audit

The existing v1 Core Trac query configuration intentionally remains frozen for
compatibility, but it is not an adequate V2 discovery model. Each current query
uses the same predicate shape: `status=!closed` and `keywords~=<track>`.

| Query | Actual predicate | Certified rows |
| --- | --- | ---: |
| `media_has_patch` | open tickets with keyword containing `media` | 26 |
| `accessibility_has_patch` | open tickets with keyword containing `accessibility` | 0 |
| `docs_needs_testing` | open tickets with keyword containing `documentation` | 0 |
| `good_first_bugs` | open tickets with keyword containing `starter` | 0 |
| `general_needs_testing` | open tickets with keyword containing `testing` | 264 |

The zero-result feeds are explained by query semantics, not by absence of
WordPress work: their labels imply component, beginner, or testing intent, but
the implemented predicate searches only the configured keyword string. For V2,
replace implicit keyword-track discovery with explicit versioned predicates.
Prefer the smallest reliable shard set that gives broad Core coverage, such as
needs-testing, has-patch, needs-unit-tests, needs-refresh, feedback signals,
actual good-first-bug markers, selected components, active milestone/release
work, and recently materially changed open work.

Do not extend v1's all-required browser CSV rule to a much larger V2 supply
net. V2 Core shards need independent evidence, latency/truncation checks, and
truthful partial/degraded reporting. False `COMPLETE` is a release failure.

## Observation and storage design

V2 observation identity must be per run, not date-only. Each observation should
record run ID, observed time, collector version, source/config revision, exact
predicates or scope, upstream watermark where available, artifact hash, and
certification result. The current raw Trac archive averages about 59.6 KB per
day across 109 archived days; a 90-day retention window is about 5.1 MB at the
current shape, or about 5.3 MB using the current observed maximum. The current
bounded wordpress-develop source snapshot is about 67 KB. These numbers support
bounded immutable observations without large duplicate Git history, but V2
should retain compact source-family observations and deterministic current
projections rather than committing redundant generated projections as the
immutability source.

## Quality gates before first v2 production release

V2 is not production-ready merely because tests pass. Before first public V2
deployment, run a fresh quality-yield sample over high-ranked opportunities and
independently reread authoritative public sources. Measure raw resources,
clusters, opportunity hypotheses, qualification distribution, dedupe collapse,
evidence completeness, freshness, contribution-family diversity, setup and
effort, and useful-work yield. A smaller high-yield pool is better than a large
feed that collapses into already-covered or redundant work.

The first native-source sample proves the model can produce opportunities from
`WORDPRESS_DEVELOP_GITHUB` and `GUTENBERG` without a Core Trac root. It is not
yet a production acceptance sample. The Core reread path needs a repeatable
collector-compatible current-state read because direct shell HTTP access can be
blocked even when the public page is browser-readable.
