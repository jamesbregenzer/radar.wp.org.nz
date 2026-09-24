# `radar.wp.org.nz` migration runbook

Status: **WP-6 REPOSITORY PREPARATION COMPLETE — GOVERNED CUTOVER PENDING**

The complete authoritative WP-6 plan is
[`WP-6-RADAR-PRODUCTION-MIGRATION.md`](WP-6-RADAR-PRODUCTION-MIGRATION.md).
This short runbook exists as the operator entrypoint and must not be interpreted
as evidence that provider-side changes have occurred.

## Frozen target

- repository: `jamesbregenzer/radar.wp.org.nz` after governed rename;
- Worker: `radar-wp-org-nz`, serving Static Assets from `docs/radar`;
- application/admin/API: `radar.wp.org.nz`, protected with Cloudflare Access;
- apex and `www`: `301` to exactly `https://wordpress.org/`, discarding source
  path and query;
- legacy Radar: after acceptance, `301` to the same path/query on
  `https://radar.wp.org.nz`.

## Operator sequence

1. Merge WP-6 and record the merge SHA and all existing rollback state.
2. Rename the GitHub repository and verify old-URL redirects, Actions, branch
   settings, Federal Eagle Runtime GitHub App access, HQ registry identity, and
   external remotes.
3. Configure the Worker's explicit repository variables and existing secrets.
4. Deploy the exact SHA without production traffic and record candidate/prior
   Worker versions.
5. Inspect existing DNS, bind `radar.wp.org.nz`, and configure human plus
   service-token Access policies.
6. Execute the documented human, machine, hash/ETag, error, and authentication
   acceptance matrix.
7. Add the apex/`www` redirect and verify its exact destination semantics.
8. Only after acceptance, enable the path/query-preserving legacy redirect.
9. Observe a normal publication/confidence window; then retire obsolete Pages
   only after confirming it has no remaining domain or preview dependency.

No live Trac collection is required for deployment acceptance. Do not modify
Thor, scheduler, credentials, Cloudflare, DNS, Access, or redirects from an
ungoverned lane.
