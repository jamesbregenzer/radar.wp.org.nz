# Review and Outcome Tracking

WP Core Radar records review decisions and contribution outcomes separately from certified opportunity data.

## Review decisions

Review state lives in `data/reviews/reviews.json`, keyed by ticket ID. Supported statuses are:

- `shortlist`: strong candidate for follow-up
- `watch`: worth monitoring, but not actionable yet
- `reject`: poor fit for the current workflow
- `tested`: patch or behavior tested
- `commented`: a Trac comment was posted
- `committed`: the ticket was committed

`shortlist`, `watch`, and `reject` are planning states. `tested`, `commented`, and `committed` are acted-on states shown under Completed / Acted On.

Review data is a mutable overlay. Changing it can update dashboard grouping without changing the identity or content of an already certified snapshot.

Because the repository is public, review records must not contain secrets, credentials, or sensitive personal information. Generation publishes `docs/radar/review-state.json` as a display-safe projection and excludes free-form notes.

## Contribution outcomes

Low-volume outcome records live in `data/outcomes/outcomes.csv`. They describe results such as testing, an upstream comment, an accepted patch, a commit, or contributor props.

Props are not a review status. They are recorded independently after WordPress.org shows the attribution, with an optional changeset reference. Upstream maintainers decide props.

## Published views

`docs/radar/contributions/index.html` summarizes public-safe review and outcome metadata at [https://radar.wp.org.nz/contributions/](https://radar.wp.org.nz/contributions/). It includes totals, activity, component focus, and recorded props without exposing private notes or admin authentication data.

The `/admin/` application reads `docs/radar/admin-data.json` and the safe review overlay from deployed Static Assets. Rendering does not call GitHub and does not require a GitHub credential.

If durable review persistence is unavailable, admin write requests fail with `EXECUTOR_UNAVAILABLE`. They do not report success or create local-only state that appears durable. The required persistence interface is defined in [`contracts/executor.md`](contracts/executor.md).

For local maintenance, `scripts/review-ticket.py` updates `data/reviews/reviews.json` and regenerates the affected dashboard projections.
