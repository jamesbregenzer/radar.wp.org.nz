# Outcome Tracking

WP Core Radar tracks contribution outcomes and review decisions so scoring and workflow sections can improve over time without automating contribution activity.

## Contribution outcomes

Contribution outcomes describe what happened after a ticket was acted on manually in WordPress Trac.

Examples:

- Ticket tested
- Trac comment posted
- Patch accepted
- Props received
- Ticket committed
- Follow-up requested

Outcome records live in:

```text
data/outcomes/outcomes.csv
```

This file remains intentionally simple because outcomes are low-volume and manually maintained.

## Review decisions

Review decisions describe how Radar triaged a ticket before or after human review.

Examples:

- `shortlist` — strong candidate for follow-up
- `watch` — worth monitoring, but not actionable yet
- `reject` — poor fit for this workflow
- `tested` — patch or behavior tested
- `commented` — manual Trac comment posted
- `committed` — ticket was committed

Props are not a review decision. They are recorded as an independent outcome after contributor credit appears on WordPress.org.

Review decisions live in:

```text
data/reviews/reviews.json
```

Reviews are stored as JSON keyed by ticket ID because this format is easy for both local tooling and the protected Cloudflare Worker admin route to validate safely.

Example:

```json
{
  "33073": {
    "status": "tested",
    "reason": "Patch tested successfully",
    "notes": "Verified locally and reported results on Trac.",
    "received_props": true,
    "props_recorded_at": "2026-06-19T00:00:00Z",
    "changeset": "62481",
    "updated_at": "2026-06-19T00:00:00Z"
  }
}
```

The review data file should remain constrained metadata only. It should not become a general-purpose repository write surface.

Because the repository is public, review notes should be written as publishable metadata. Do not store secrets, private credentials, or sensitive personal notes in `data/reviews/reviews.json`.

## Public-safe contribution history

Review decisions also power a public-safe contribution history page generated at:

```text
docs/radar/contributions/index.html
```

This static page is served at `/contributions/` on the Radar application host.
Under the WP-6 production policy it sits behind the human Cloudflare Access
boundary, although its content remains public-safe if accidentally exposed. It
summarizes display-safe review metadata only: total reviewed tickets,
tested/commented/watch counts, props received, component focus, activity by
month, and recent review activity. It does not expose admin authentication,
secrets, or private notes.

## Protected admin write path

The production `/admin/` console is rendered by the Cloudflare Worker. It authenticates the user, loads generated ticket data from `docs/radar/admin-data.json`, and writes review decisions and historical props records to `data/reviews/reviews.json` through the GitHub API.

The Worker does not regenerate dashboard files itself. When `data/reviews/reviews.json` changes on `main`, `.github/workflows/refresh-dashboard.yml` runs `scripts/generate-dashboard.py` and commits regenerated `docs/radar/index.html`, `docs/radar/contributions/index.html`, and `docs/radar/admin-data.json`. This keeps workflow sections like Shortlisted, Watching, Completed / Acted On, and Rejected current shortly after review saves.

Local review writes through `scripts/review-ticket.py` also regenerate dashboard files immediately so review grouping stays in sync during manual maintenance.

Allowed review statuses are intentionally limited to the workflow states above. This keeps the admin route useful for review decisions without turning it into a broad repository write surface.

Statuses represent workflow state only. `shortlist`, `watch`, and `reject` are planning states. `tested`, `commented`, and `committed` are acted-on outcomes and are grouped under Completed / Acted On. Props are not a status; they are an independent outcome recorded as `received_props: true`, with optional `changeset` metadata for future reporting.
