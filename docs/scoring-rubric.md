# Scoring Rubric

WP Core Radar uses deterministic scoring before any human or AI-assisted review. The goal is to surface WordPress Core tickets that are likely to be actionable, useful, and aligned with repeatable contribution work.

The single executable source of truth for scoring values and thresholds is
`config/scoring.json`. `score_ticket()` in `scripts/radarlib.py` applies that
configuration. This document explains the policy for reviewers; tests prevent
the executable configuration and behavior from drifting silently.

## Baseline Track Priority

Every enabled query in `config/queries.json` has a `priority` value. That value becomes the ticket's starting score before ticket-level signals are added.

Current enabled tracks:

| Query slug | Display name | Baseline |
|---|---|---:|
| `media_has_patch` | Media: Has Patch | +100 |
| `accessibility_has_patch` | Accessibility: Has Patch | +95 |
| `docs_needs_testing` | Docs: Needs Testing | +75 |
| `good_first_bugs` | Good First Bugs | +70 |
| `general_needs_testing` | General: Needs Testing | +65 |

Unknown archived datasets fall back to a baseline of +50.

## Freshness, Momentum, and Ticket Age

Freshness, momentum, and ticket age are scored separately and shown as explicit score details in the dashboard/admin payload. This keeps the scoring explainable enough for review decisions such as `Freshness: Recently updated <=14 days +20`, `Momentum: Healthy comment count +7`, or `Ticket age: Very old ticket -8`.

- **Freshness** is based on the ticket's `modified` or change time. It answers: has this ticket moved recently?
- **Momentum** is based on the comment count. It answers: does the ticket have enough discussion to be actionable without becoming a huge thread?
- **Ticket age** is based on the ticket's `created` date. It answers: is the ticket mature enough to have context, or so old that it may need extra caution?

A ticket can be old but still receive a freshness boost when it was recently updated. A mature ticket can receive a small ticket-age boost, while a very old ticket can be penalized if age suggests extra risk.

Freshness and ticket-age signals depend on Trac CSV fields such as `time`/`Created` and `changetime`/`Modified`. Browser-fetch requests those columns explicitly, and the parser accepts both ISO-style timestamps and Trac's AM/PM CSV timestamps such as `04/23/2026 03:37:20 PM`.

Momentum scoring depends on a usable comment-count column. Browser-fetch requests likely comment-count aliases (`comments` and `_comments`), and the scorer also recognizes stored aliases such as `comment_count` and `Comment Count`. If Trac does not return one of those fields for a query, momentum is omitted rather than guessed.

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
| Already produced props | -60 | `data/outcomes/outcomes.csv` records `props` |
| Already tested | -20 | `data/outcomes/outcomes.csv` records `tested` |
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

Those tickets now receive explicit setup-complexity penalties. The penalties do not reject tickets automatically; they lower ranking so quick, stock-WordPress testing opportunities rise first while more specialized tickets remain available in Top Opportunities or can be manually shortlisted.

## Priority Target Rules

A ticket appears in **Priority Targets** only when all of these are true:

1. It has no existing review decision.
2. Its score is at least 150.
3. It has at least one action signal: `needs testing`, `has patch`, or `good first bug`.
4. It has at least one manageability signal: ``freshness`, `momentum`, or `has owner`.
5. It does not include stale or already-acted-on penalties such as `very old ticket`, `stale activity`, `very large thread`, `already produced props`, or `already tested`.

Only the first 12 matching tickets are shown as Priority Targets.

## Review Grouping

Review decisions live in `data/reviews/reviews.json` and move tickets into workflow sections. Props are recorded separately as `received_props: true` and are included in contribution-history reporting without becoming a review status:

| Review status | Section |
|---|---|
| `shortlist` | Shortlisted |
| `watch` | Watching |
| `tested`, `commented`, `committed` | Completed / Acted On |
| `reject` | Rejected |
| no review status | Priority Targets or Top Opportunities |

## Guardrail

Scores are recommendations only. WP Core Radar does not auto-comment on Trac or perform contribution activity. A human reviewer opens the ticket, verifies current state, tests locally where appropriate, and decides what to do next.
