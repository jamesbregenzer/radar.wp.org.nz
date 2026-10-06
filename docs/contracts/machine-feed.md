# Radar Machine Feed Contract

Status: **FROZEN `/api/v1/` CONTRACT**

Radar's HTTP interface is a read-only projection of the verified committed
bundle in `data/certified/current/`. GitHub is durable truth; HTTP, generated
Static Assets, and health documents are not independent authorities.

| Endpoint | Successful body source |
| --- | --- |
| `GET /api/v1/health` | deterministic summary of verified `snapshot.json` |
| `GET /api/v1/snapshot` | byte-preserving `snapshot.v1` artifact |
| `GET /api/v1/collection` | byte-preserving `collection.v1` artifact |
| `GET /api/v1/opportunities` | byte-preserving certified opportunity set |
| `GET /api/v1/opportunities/{ticket_id}` | exact `opportunity.v1` record from that set |
| `GET /api/v1/machine-feed` | compact public-safe `radar-machine-feed.v1` opportunity summary |
| `GET /api/v1/contributions` | public-safe `verified-contribution-outcomes.v1` projection |

`HEAD` is also supported. Other methods return `405 METHOD_NOT_ALLOWED`.
Malformed ticket IDs return `400 MALFORMED_TICKET_ID`; absent tickets return
`404 OPPORTUNITY_NOT_FOUND`. Missing, malformed, hash-inconsistent, or
identity-inconsistent bundles return `503` and never report healthy. Errors use
`radar-error.v1` and reveal no stack, host path, credential, or runtime detail.

Successful responses use `application/json`, include `X-Radar-Snapshot-ID`, and
use `Cache-Control: public, max-age=300, must-revalidate`. Strong ETags are
derived from response SHA-256. An exact `If-None-Match` returns `304`. Unchanged
snapshot bytes therefore retain the same ETag.

The certified snapshot is immutable. Its `radar_state`, if present, is state at
certification time. Current operator reviews, reasons, and private notes live in
the separate GitHub-backed review overlay. Dashboard/admin may apply that
overlay for current human workflow; the machine feed does not mutate or replace
the certified record when reviews change.

## Machine-readable opportunity identity

Every certified `opportunity.v1` record includes:

- `opportunityKey`: deterministic identity in the form `core-trac:{ticketId}`;
- `opportunityRevision`: deterministic hash of material opportunity state.

The revision preimage includes ticket state, discovery tracks, and material
ranking inputs. It excludes generated timestamps, collection artifact paths,
snapshot identity, and API publication details. These fields allow any API user
to distinguish stable opportunity identity from a materially changed record.

Current certified records include an advisory `qualification` object. It
describes the likely opportunity class and contribution type, proportionate
evidence profiles, visual-evidence relevance, useful skills, freshness,
duplication risk, likely public channel, engineering weight, preliminary
eligibility blockers, and public contribution hypothesis. Qualification is
derived only from certified public WordPress and GitHub evidence. It is
discovery guidance, not proof that work is still needed, and does not by itself
change a stable opportunity revision.

The public contribution hypothesis adds:

- `recommendedContributionClass`: one of `TEST_EXISTING_PR`,
  `ADD_REGRESSION_TEST`, `REPRODUCE_BUG`, `VERIFY_EXISTING_PATCH`,
  `REVIEW_EXISTING_PR`, `REVIEW_API_EDGE_CASE`,
  `BENCHMARK_PERFORMANCE_CHANGE`, `VERIFY_PHP_COMPATIBILITY`,
  `ACCESSIBILITY_UI_VERIFY`, `DOCUMENT_TECHNICAL_BEHAVIOR`,
  `FOLLOW_UP_AFTER_UPSTREAM_CHANGE`, `STALE_BUT_ACTIONABLE`, or
  `NO_CLEAR_CONTRIBUTION`;
- `confidence`: high, medium, or low;
- `reason`: public-safe explanation of the missing contribution hypothesis;
- `evidenceFreshness`: freshness state and ticket modified age;
- `sourceCoverage`: public evidence families that informed the hypothesis,
  including Trac ticket fields, public patches or attachments, linked
  WordPress GitHub PRs, public PR discussion or review, changed files or diffs,
  public test or CI evidence, and related tickets when available.

`NO_CLEAR_CONTRIBUTION` is a suppression signal. It means Radar did not find a
clear, useful, nonduplicative contribution path from the certified public
evidence.

`/api/v1/machine-feed` contains:

- current snapshot identity and dataset hash;
- ordered `{ticketId, opportunityKey, opportunityRevision, rank, tier, score}`
  records, with the advisory `qualification` projection;
- verified public contribution outcomes.

The machine feed is read-only public data. It grants no execution or contribution
authority, contains no credentials, and does not replace live WordPress/Trac
verification.

`/api/v1/contributions` exposes the same verified public outcome projection
without the opportunity list. Outcome records include only public-safe fields:

- `ticketId`;
- `opportunityKey`;
- public contribution URL;
- contribution type;
- tested head and base SHA when known;
- verification timestamp;
- lifecycle state;
- optional changeset;
- optional props flag.

The API is public and its data is designed to be public-safe. Radar does not
identify, document, or depend on specific downstream consumers.

Anyone using Radar data to inform contribution work should independently
revalidate current WordPress/Trac state before acting. Radar is discovery
intelligence, may be stale when consumed, and does not authorize a contribution.
Breaking changes to v1 require `/api/v2/` or an explicitly governed
compatibility strategy.

## Source-neutral `/api/v2/`

Status: **PRE-PRODUCTION SOURCE-NEUTRAL CONTRACT**

V2 is a public observation API. It keeps v1 compatibility intact while exposing
resource, relationship, source-family, qualification, coverage, and change-feed
data in terms that are useful to any public consumer. Because public production
does not yet expose `/api/v2/`, this contract may still change before first V2
production deployment.

| Endpoint | Successful body source |
| --- | --- |
| `GET /api/v2/health` | v2 source-family and snapshot health |
| `GET /api/v2/sources` | independently certified source-family state |
| `GET /api/v2/snapshot` | source-neutral snapshot identity and hashes |
| `GET /api/v2/resources` | ordered `radar-resource.v2` records |
| `GET /api/v2/resources/{id}` | one v2 resource, such as `core-trac:63568` |
| `GET /api/v2/relationships` | typed public resource relationships |
| `GET /api/v2/opportunities` | ordered `radar-opportunity.v2` records |
| `GET /api/v2/opportunities/{id}` | one semantic missing-increment opportunity |
| `GET /api/v2/candidates` | public `radar-candidate-feed.v1` projection |
| `GET /api/v2/candidate-feed` | alias of the public candidate feed |
| `GET /api/v2/contribution-families` | versioned public contribution-family registry |
| `GET /api/v2/scoring` | versioned candidate scoring-vector contract |
| `GET /api/v2/changes` | reproducible public observation-change feed |
| `GET /api/v2/contributions` | public contribution records |
| `GET /api/v2/outcomes` | public outcome projection and attribution limits |
| `GET /api/v2/taxonomy` | qualification states, contribution families, sources, and coverage states |
| `GET /api/v2/diagnostics` | public supply and quality diagnostics |

Every v2 resource exposes:

- stable family-qualified identity;
- canonical public URL;
- resource type;
- upstream state;
- observed material revision;
- observed time;
- source-family snapshot identity;
- provenance;
- completeness and limitations;
- deterministic hash.

Every v2 relationship exposes a typed edge between resources and public
provenance. Bare numeric references, including GitHub `#12345` text, do not
create Core Trac relationships unless repo-aware or canonical public evidence
disambiguates the identity.

Every v2 opportunity separates:

- canonical resource: the primary public upstream object;
- supporting resources: linked public PRs, reviews, diffs, tests, or related
  resources when certified;
- contribution family: the likely useful public contribution path;
- qualification state: one of `CLEAR_OPPORTUNITY`,
  `POSSIBLE_OPPORTUNITY`, `NEEDS_MORE_EVIDENCE`, `UPSTREAM_CHANGED`,
  `LIKELY_ALREADY_COVERED`, or `NO_CLEAR_CONTRIBUTION`;
- why-now reasons: deterministic public reasons the contribution may be useful
  now;
- source coverage: `COMPLETE`, `PARTIAL`, `NONE`, or `STALE` for evidence
  families such as ticket fields, patches, PR discussion, diffs, CI/test
  evidence, related tickets, and release context;
- limitations: missing or stale public evidence that should constrain action;
- ranking dimensions: actionability, usefulness signal, evidence completeness,
  freshness, duplication risk, effort, timeliness, and confidence.

Core Trac v1 identities remain unchanged in `/api/v1/` and in each V2 record's
`legacyV1` compatibility object. V2 opportunity IDs identify the semantic
missing contribution increment, not the ticket itself. V2 material revisions
track supporting-resource and qualification changes without changing the frozen
v1 schema.

Every v2 candidate is a public evidence record derived from one opportunity
record. A candidate is not a final qualification decision, executable work, a
schedule, or delivery authority. Candidate records include canonical candidate
ID, resource refs, public relationships, family candidates and confidence,
score vector, derived ranking, source revision, freshness, source health,
change information, and a public explanation.

The contribution-family registry is versioned and source-neutral. Initial
families include Core code review, Core patch testing, bug reproduction,
regression and automated tests, Core docs, Gutenberg review/testing/
reproduction/patch work, accessibility testing, beta/RC testing, performance
investigation, documentation and handbook review, Learn technical review, and
Theme Check/theme review families. WordPress labels, keywords, pathways, and
legacy Radar signal names are aliases or evidence signals, not mandatory family
IDs.

The scoring contract keeps each score dimension separate:
`upstreamDemandStrength`, `expectedUpstreamImpact`, `jamesAffinity`,
`noveltyConfidence`, `evidenceFeasibility`, `timeliness`,
`estimatedExecutionCost`, and `deliveryReputationalRisk`. Each dimension
carries value, confidence, source evidence, and explanation. Unknown values
remain unknown. The derived scalar priority is only for ordering and cannot
override failed eligibility, safety, or source-integrity gates.

## Source-family certification

Source families certify independently.

`CORE_TRAC` remains fail-closed within the configured Trac collection. A
certified Trac snapshot requires every enabled Trac query to be collected and
validated. Each Trac CSV acquisition keeps the exact source URL, retrieval
timestamp, raw byte SHA-256, immutable acquisition ID, source receipt, and
parser metadata. Historical CSV snapshots are append-only; a rerun may reuse
identical bytes but may not silently overwrite different bytes under the same
collection/query identity.

`WORDPRESS_DEVELOP_GITHUB` is currently certified from a bounded public snapshot
of recently updated open `WordPress/wordpress-develop` pull requests. Its
completeness and limitations are reported separately from Trac. If GitHub
collection fails while Trac succeeds, Radar may keep publishing fresh Trac
intelligence while reporting the GitHub family as stale, missing, or degraded.
A pull request dropping outside the bounded window must not be represented as
closed, merged, superseded, disappeared, or resolved. Partial GitHub data must
never masquerade as complete.

`GUTENBERG` is certified from bounded public snapshots of open
`WordPress/gutenberg` issues and pull requests sorted by updated time.
Gutenberg identities remain native GitHub issue and pull request identities.
Radar may create Gutenberg-native opportunities when public labels, review
metadata, bug/accessibility/API/performance cues, or stale active discussion
support a specific missing contribution increment. It must not fabricate Core
Trac identities or make Gutenberg source health globally invalidate healthy Core
Trac or wordpress-develop data.

Native GitHub opportunities do not require a Core Trac root. They still require
a concrete public signal and expose `requiresLiveRevalidation=true`, evidence
observed, evidence missing, duplication risk, novelty signal, effort/setup
burden, confidence, and limitations. A resource with no clear public
contribution signal should be omitted or suppressed rather than promoted merely
because it exists.

## Public observation changes

`/api/v2/changes` is a reproducible material public observation-change feed
derived from certified public data. Event classes include resource first
observation, material resource changes, PR head changes, supporting-resource
additions, public test or review additions, qualification changes, clear
opportunity emergence, likely coverage, suppression, upstream reactivation,
closure or merge, and source coverage degradation. Event IDs are derived from
material state, not snapshot timestamp or output order.

The feed is not an execution log. It does not accept acknowledgements, assignment
state, delivery state, or private lifecycle data.
