# WP-6 Radar Production Migration

Status: **CANONICAL WORKER BOUND — PRODUCTION CLOSEOUT IN PROGRESS**

WP-6 prepared the canonical Worker, repository identity, access boundary, DNS,
redirects, verification, and rollback plan. The repository rename, Worker
deployment, `radar.wp.org.nz` binding, and human Cloudflare Access boundary are
now in place. The machine API is private by default. Apex/`www` redirects,
workers.dev closure, acceptance evidence, and legacy-host handling are tracked
as explicit closeout gates. The authoritative product boundary remains in
`RADAR-PRODUCT.md`.

## Target topology

| Surface | Target |
| --- | --- |
| Repository | `jamesbregenzer/radar.wp.org.nz` |
| Worker | `radar-wp-org-nz` with Static Assets from `docs/radar` |
| Human application | `https://radar.wp.org.nz/` |
| Admin | `https://radar.wp.org.nz/admin/` |
| Machine feed | `https://radar.wp.org.nz/api/v1/*` |
| Apex and `www` | permanent redirect to `https://wordpress.org/` |
| Legacy Radar | path/query-preserving redirect to `https://radar.wp.org.nz` after acceptance |

GitHub remains durable truth. The Worker and its assets are projections. No
Pages origin, GitHub API read, Trac request, D1, KV, R2, or Durable Object is
required for dashboard or machine-feed reads.

## Repository rename decision and audit

The codebase is ready for the proposed rename, but the rename is not performed
by this PR. Repository settings, external integrations, and runtime checkout
remotes must be verified during the governed rename. Creating a replacement
repository is forbidden.

GitHub Actions use repository-relative checkout and repository context, so the
rename does not require workflow-specific credentials. Certified IDs and hashes
do not contain the repository name. API and admin runtime reads are
repository-independent. Remaining historical old-name references are retained
only where they document migration continuity or external runtime paths.

Active product code, Worker routing, API schema IDs, certification, and
generated outputs have no dependency on `wp-core-radar` or the legacy hostname.

## Worker deployment contract

`wrangler.jsonc` intentionally declares only the Worker service and Static
Assets binding. It does not declare production routes or custom domains, so a
repository command cannot silently bind or overwrite an unrelated hostname.
The custom-domain association is a separate governed Cloudflare action.

The Worker has no GitHub repository variables or GitHub runtime credential.

Required Worker secrets:

- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`

WP-6A removes GitHub credentials from the Worker runtime. Admin reads use a
deterministic deployed `radar-review-state.v1` projection. Durable review/props
writes are external executor requirements and fail closed while unavailable.

The existing application password/session/CSRF controls remain defense in
depth behind Cloudflare Access. Cloudflare Access and the application password/session controls serve different
defense-in-depth boundaries; neither grants durable review-write authority.

Deploy an exact merged SHA using governed Cloudflare custody, first without a
production hostname. `npx wrangler deploy --dry-run --outdir <temporary-dir>`
is the repository-level build proof. Bind `radar.wp.org.nz` only after the
uploaded version and variables/secrets are verified. Preserve the prior Worker
version ID as the rollback target.

## Cloudflare Access policy

Use Access at the `radar.wp.org.nz` hostname boundary:

1. a human application covering `radar.wp.org.nz/*`, allowing only James's
   verified identity;
2. a more specific machine policy for `radar.wp.org.nz/api/v1/*`, allowing
   provider-managed programmatic authentication when required; and
3. no bypass policy for health or static files unless deliberately approved.

Cloudflare policy specificity and evaluation order must be confirmed in the
dashboard so the API rule is not shadowed by the human rule. The
repository data remains public-safe if Access is misconfigured: authentication
controls access, not the secrecy model.

Programmatic Access credentials, if enabled, belong in provider/runtime secret
custody. They must be sent only over HTTPS, rotated and revoked outside Radar,
and never committed here. Radar response bodies, ETags, errors, and versioned
contracts remain unchanged behind Access.

## DNS and redirect desired state

Inspect the existing `wp.org.nz` zone before mutation; this repository does not
assert its current records. The desired end state is:

| Name | Desired Cloudflare state |
| --- | --- |
| `radar.wp.org.nz` | proxied custom hostname/route bound to Worker `radar-wp-org-nz`; remove or replace only a conflicting record after inspection |
| `wp.org.nz` | proxied DNS record sufficient for Cloudflare Redirect Rules; preserve mail and unrelated records |
| `www.wp.org.nz` | proxied DNS record sufficient for the same redirect; no origin service required |

Do not change nameservers or authoritative DNS. The exact record type/value for
apex and `www` depends on the zone's current state; use proxied placeholder DNS
only if Cloudflare requires a record and no compatible proxied record exists.

Create one permanent redirect rule matching hosts `wp.org.nz` and
`www.wp.org.nz`: status `301`, destination exactly `https://wordpress.org/`,
discard the source path, and discard the source query string. Thus every source
URL lands on the canonical WordPress.org homepage instead of manufacturing a
possibly misleading path.

After the new Radar hostname is accepted, redirect
`radar.james.bregenzer.dev/*` with status `301` to
`https://radar.wp.org.nz/<same path>?<same query>`. Keep the old host proxied
while this rule exists. Do not activate it before acceptance.

## Ordered cutover

1. Merge WP-6 after review and record the merge SHA.
2. In GitHub, rename `jamesbregenzer/wp-core-radar` to
   `jamesbregenzer/radar.wp.org.nz`.
3. Confirm the old GitHub URL redirects, Actions remain enabled, branch settings
   remain intact, and required repository integrations retain access.
4. Update any external integration registry and executor/local remotes.
5. Configure Worker variables/secrets for the renamed repository and deploy the
   exact merged SHA without binding production traffic.
6. Capture the deployed Worker version as the candidate and retain the prior
   known-good version.
7. Inspect DNS, bind `radar.wp.org.nz`, and apply the human and machine Access
   policies.
8. Run the acceptance plan below. No live Trac collection is needed.
9. Add and verify the apex/`www` redirect rule.
10. Only after Radar acceptance, enable the legacy hostname redirect.
11. Observe normal operation through an agreed confidence window, then remove
    the obsolete Pages project/integration if its current production role is
    confirmed absent.

This order renames before deploying the target Worker because the committed
target variable is the new repository identity. The existing production path
remains the rollback service until acceptance.

## Acceptance plan

Record HTTP status, relevant headers, body SHA-256, snapshot ID, Worker version,
and test time for each check.

Human checks:

- `/` renders the committed dashboard and its displayed certification metadata
  matches `data/certified/current/snapshot.json`;
- `/admin/` requires Access, then the application login, and displays the same
  opportunity count/identities;
- perform a reversible review write only with an approved disposable ticket
  state; otherwise explicitly defer the write test and verify GitHub read scope.

Authorized machine checks:

- health is `200` and healthy, with the expected snapshot ID;
- snapshot, collection, and opportunities bodies match committed artifact
  SHA-256 values;
- one known ticket record equals the record in the complete feed;
- `If-None-Match` returns `304`;
- malformed ticket returns `400`, unknown ticket returns `404`, unsupported
  method returns `405`, and a controlled invalid fixture—not production
  data—proves the `503` fail-closed contract;
- unauthenticated requests are rejected by Access and authorized requests
  retain the WP-5 response contract.

Redirect checks:

- HTTP and HTTPS forms of apex and `www` settle at exactly
  `https://wordpress.org/` without source path/query;
- after acceptance, legacy Radar paths including `/admin/` and `/api/v1/...`
  reach the corresponding canonical path with query preserved and no loop.

## Rollback

Rollback is restoration of recorded known-good state, not fix-forward:

- Worker: activate the captured prior Worker version;
- hostname: detach the candidate binding or restore its previous route/target;
- Access: restore the exported prior application/policy configuration;
- apex/`www`: disable the new redirect rule and restore the recorded prior rule
  state without changing unrelated DNS;
- legacy Radar: disable its redirect and restore the prior Worker/Pages route;
- repository: prefer keeping the GitHub rename because GitHub redirects the old
  URL; if rename itself causes a custody failure, rename back only after
  recording new repository activity and coordinating integrations/remotes to avoid
  split custody.

Before cutover, export or record Worker version IDs, route/custom-domain state,
Access applications/policies, redirect rules, relevant DNS records, Pages
project/domain bindings, repository settings, and GitHub App installation
selection.

## Pages retirement and human actions

The active Worker has no Pages-origin dependency. Existing Pages is therefore a
rollback/legacy delivery candidate, but its live custom-domain attachment
cannot be inferred from repository files. Retire it only after Worker
acceptance, legacy redirect success, at least one normal data publication, and
the agreed confidence window. Before deletion, detach custom domains, preserve
the last deployment identifier, and confirm no branch-preview workflow relies
on it.

Human/governed actions remaining are: inspect Cloudflare zone/project state;
record rollback state; rename the GitHub repository; confirm/update repository
integrations and registries; update external remotes; configure Worker variables
and secrets; deploy and bind the Worker; configure Access; create DNS/redirect
rules; execute acceptance; enable the legacy redirect; and later retire Pages.

No production action should proceed while any of these facts is unknown.
