# WP-5 Machine Feed + UI Alignment

Status: **IMPLEMENTED**

WP-5 projects the WP-3 certified bundle through the existing Worker and aligns
human opportunity views with that same model. It does not implement
WordPress.org writes, an executor, deployment, domain migration, or production
access policy.

## Data flow

`scripts/generate-api.py` first runs WP-3 offline verification, then creates
byte-preserving Static Asset copies of the three canonical JSON artifacts and
detached manifest plus a deterministic health document. On every API read, the
Worker rechecks snapshot, collection, dataset hashes, certification state,
identities, and opportunity count. No request reads raw CSV, calls Trac/GitHub,
or scores data.

`scripts/certifiedmodel.py` is a compatibility adapter, not a new model. It
verifies and maps certified `opportunity.v1` records into the established
renderer shape. Dashboard, admin data, contribution enrichment, and Markdown
report thereby retain useful UX while ticket identities, scores, order,
provenance, and ranking reasons come from certified truth.

Because these projections now require a snapshot identity, WP-5 refines the
canonical pipeline ordering to validate → certify → verify → generate →
publication plan (after optional collection). This ensures generation reads the
new verified snapshot rather than the prior current pointer. All WP-4 operations
and first-failure stopping semantics remain unchanged.

## Review overlay semantics

The immutable snapshot retains only public-safe review state present when it
was certified. Current `data/reviews/reviews.json` is a separate mutable overlay
used for admin/dashboard grouping and contribution history. Saving a review
does not change certified bytes, IDs, or hashes. Notes are not added to the
machine feed. The existing protected Worker write remains constrained to the
review file and the review-refresh workflow regenerates UI projections only.

## Compatibility

- Browser collection and WP-3/WP-4 operations are unchanged.
- Existing admin authentication, CSRF checks, review/props saves, and GitHub
  durability remain intact.
- Existing static Worker fallback and contribution history remain intact.
- `admin-data.json` remains a UI compatibility payload, now derived from
  certified opportunities plus current review overlay; it is not an API.

## WP-6 handoff

WP-6 owns the optional repository rename decision; canonical Worker deployment
to `radar.wp.org.nz`; Cloudflare Access policy for human and machine surfaces;
redirects from `wp.org.nz` and `www.wp.org.nz` to
`https://wordpress.org/`; and redirect/retirement of the legacy Radar hostname.
No part of that production migration is performed by WP-5.
