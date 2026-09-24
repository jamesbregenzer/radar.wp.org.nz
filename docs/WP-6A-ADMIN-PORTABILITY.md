# WP-6A — Admin portability correction

Status: implementation candidate.

## Purpose

WP-6A removes GitHub from the Cloudflare Worker read path while preserving
GitHub as durable truth. The Worker no longer needs `GITHUB_TOKEN`,
`GITHUB_OWNER`, or `GITHUB_REPO` to render the admin console.

## Safe deployed review projection

Radar generation reads canonical `data/reviews/reviews.json` and emits
`docs/radar/review-state.json` as `radar-review-state.v1`.

Allowed per-ticket fields:

- `status`
- `reason`
- `updated_at`
- `received_props`
- `props_recorded_at`
- `changeset`

Free-form `notes` are deliberately excluded. The complete review record,
including private/internal notes, remains only in canonical durable source
state and is not required for Worker rendering.

`admin-data.json` is likewise restricted to the safe review projection.

## Runtime reads

Authenticated `/admin/` reads only deployed Static Assets:

- `admin-data.json`
- `review-state.json`

No GitHub API call is made during admin rendering.

## Runtime writes

The Worker does not persist review or props changes directly. Authenticated,
CSRF-valid write attempts return HTTP 503 with `EXECUTOR_UNAVAILABLE` and
identify the unmet product requirement:

- `PERSIST_REVIEW_DECISION`
- `RECORD_PROPS_OUTCOME`

No success redirect is returned and no durable mutation is implied.

## Executor boundary

The external executor owns provider credentials, authorization, conflict
handling, idempotency, durable persistence, and resulting publication identity.
WP-6A does not implement a provider runtime or token broker.

## Production implication

The target Worker requires only its local authentication/session secrets for
the current protected admin:

- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`

Cloudflare Access remains the intended outer human/machine access boundary.
