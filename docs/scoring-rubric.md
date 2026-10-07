# Scoring Rubric

WP Core Radar uses deterministic scoring and classification to surface public WordPress resources that are likely to be actionable, useful, and aligned with repeatable contribution work.

The single executable source of truth for scoring values and thresholds is
`config/scoring.json`. `score_ticket()` in `scripts/radarlib.py` applies that
configuration. This document explains the policy; tests prevent
the executable configuration and behavior from drifting silently.

## Baseline Track Priority

Each approved source family contributes source-native signals. The processor combines those signals into a stable score vector before candidate emission.

Core Trac signal examples:

| Query slug | Display name | Baseline |
|---|---|---:|
| `media_has_patch` | Media: Has Patch | +100 |
| `accessibility_has_patch` | Accessibility: Has Patch | +95 |
| `docs_needs_testing` | Docs: Needs Testing | +75 |
| `good_first_bugs` | Good First Bugs | +70 |
| `general_needs_testing` | General: Needs Testing | +65 |

Unknown source signals are retained as evidence but do not receive an invented priority.

## Freshness, Momentum, and Ticket Age

Freshness, momentum, and ticket age are scored separately in the candidate score vector. This keeps classification explainable.

- **Freshness** is based on the ticket's `modified` or change time. It answers: has this ticket moved recently?
- **Momentum** is based on the comment count. It answers: does the ticket have enough discussion to be actionable without becoming a huge thread?
- **Ticket age** is based on the ticket's `created` date. It answers: is the ticket mature enough to have context, or so old that it may need extra caution?

A ticket can be old but still receive a freshness boost when it was recently updated. A mature ticket can receive a small ticket-age boost, while a very old ticket can be penalized if age suggests extra risk.

Freshness and ticket-age signals depend on Trac fields such as `time`/`Created` and `changetime`/`Modified`. Approved acquisition adapters preserve these fields, and the parser accepts both ISO-style and AM/PM timestamps.

Momentum scoring depends on a usable comment-count field. If an approved source does not provide one, momentum is omitted rather than guessed.

## Positive Ticket Signals

| Signal | Points | Source |
|---|---:|---|
| Has patch | +35 | `keywords` contains `has-patch` or `has patch` |
| Needs testing | +30 | `keywords` contains `needs-testing` or `needs testing` |
| Good first bug | +20 | `keywords` contains `good-first-bug` or `good first bug` |
| Media component | +20 | `component` is `Media` |
| Accessibility signal | +18 | component or keywords mention accessibility |
| Dev feedback | +18 | `keywords` contains `dev-feedback` or `dev feedback` |
| Reporter feedback | +10 | `keywords` contains `reporter-feedback` or `reporter feedback` |
| Freshness: recently updated <=14 days | +20 | modified/change time |
| Freshness: updated within 60 days | +10 | modified/change time |
| Ticket age: mature but not ancient | +8 | created date is 30–730 days old |
| Concrete milestone | +8 | milestone is present and not `Awaiting Review` or `Future Release` |
| Momentum: healthy comment count | +7 | 2–20 comments |
| Has owner | +6 | owner exists and is not `anonymous` or `nobody` |

## Negative Ticket Signals

| Signal | Points | Source |
|---|---:|---|
| Closed or non-actionable status | -100 | status is `closed`, `fixed`, `wontfix`, `duplicate`, or `invalid` |
| Freshness: stale activity >2 years | -10 | modified/change time older than 730 days |
| Missing summary | -10 | summary field is empty |
| Ticket age: very old ticket | -8 | created date older than 3650 days |
| Momentum: very large thread | -8 | more than 80 comments |
| Setup complexity: requires WooCommerce | -18 | summary, keywords, or component mention WooCommerce |
| Setup complexity: specialized image library | -18 | summary, keywords, or component mention AVIF, ImageMagick, Imagick, GD, or image library setup |
| Setup complexity: server/runtime configuration | -16 | summary, keywords, or component mention OPcache, PHP ini, server configuration, or header-level behavior |
| Setup complexity: external service or API | -16 | summary, keywords, or component mention external API/service integration or remote requests |
| Setup complexity: multisite environment | -14 | summary, keywords, or component mention multisite |
| Setup complexity: custom content type setup | -12 | summary, keywords, or component mention CPTs, custom post types, or custom comment types |
| Setup complexity: browser-specific behavior | -12 | summary, keywords, or component mention browser-specific behavior or a named browser engine |

## Complexity Guardrails

Radar is optimized for fast, legitimate contribution opportunities: tickets where a reviewer can read the discussion, reproduce the issue, test a patch, and leave useful feedback without spending most of the session building a special environment. Some tickets are still valuable Core work but are less efficient for this workflow because they require third-party plugins, seeded custom data, unusual PHP configuration, specific image-library support, multisite setup, browser-specific debugging, or external services.

Those resources receive explicit setup-complexity penalties. The penalties do not reject resources automatically; they lower ranking while preserving the underlying evidence in the candidate feed.

## Contribution Hypothesis

Score answers "how promising is this ticket relative to the current Radar
policy?" The contribution hypothesis answers "what useful public contribution
appears to be missing?"

The hypothesis is derived from certified public signals, including Trac ticket
fields, keywords, status, component, public patch signals, linked public PR
signals when available, public review or CI evidence, changed files or diffs,
related tickets, and freshness. It does not change the ticket score by itself.

Current hypothesis classes are:

- `TEST_EXISTING_PR`
- `ADD_REGRESSION_TEST`
- `REPRODUCE_BUG`
- `VERIFY_EXISTING_PATCH`
- `REVIEW_EXISTING_PR`
- `REVIEW_API_EDGE_CASE`
- `BENCHMARK_PERFORMANCE_CHANGE`
- `VERIFY_PHP_COMPATIBILITY`
- `ACCESSIBILITY_UI_VERIFY`
- `DOCUMENT_TECHNICAL_BEHAVIOR`
- `FOLLOW_UP_AFTER_UPSTREAM_CHANGE`
- `STALE_BUT_ACTIONABLE`
- `NO_CLEAR_CONTRIBUTION`

`NO_CLEAR_CONTRIBUTION` is the noise-control class. It is used when public
evidence indicates the ticket is resolved, superseded, already covered, or does
not reveal a concrete nonduplicative contribution path.

## Guardrail

Scores and hypotheses are recommendations only. WP Core Radar does not comment
on Trac, submit patches, or perform contribution activity. Current WordPress
state should be rechecked before acting on any opportunity.
