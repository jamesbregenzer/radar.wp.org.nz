# `radar.wp.org.nz` migration runbook

Status: **TARGET ARCHITECTURE — WP-6, NOT YET EXECUTED**

The authoritative program sequence is
`docs/WORDPRESS-AUTOMATION-PROGRAM.md`. This runbook records the intended WP-6
migration without treating committed Worker configuration as a completed
deployment.

## CURRENT IMPLEMENTATION

- Repository: `jamesbregenzer/wp-core-radar`
- Established live hostname: `radar.james.bregenzer.dev`
- Proven collection: local Firefox browser session in an allowed network
  environment currently associated with Thor
- Durable truth after publication: GitHub
- Committed deployment target: Cloudflare Worker plus Static Assets from
  `docs/radar`
- Current compatibility/rollback dependency: existing Pages-era delivery

No repository rename, Cloudflare deployment, DNS change, redirect, or runtime
change occurs as part of WP-1.

## TARGET ARCHITECTURE

| Route | Target behavior |
| --- | --- |
| `radar.wp.org.nz` | Radar application |
| `radar.wp.org.nz/admin/` | Protected Radar admin |
| `radar.wp.org.nz/api/v1/...` | Future certified Radar feed/API |
| `wp.org.nz` | Redirect to `https://wordpress.org/` |
| `www.wp.org.nz` | Redirect to `https://wordpress.org/` |
| `radar.james.bregenzer.dev` | Redirect to canonical Radar host, then retire |

The proposed future repository name is
`jamesbregenzer/radar.wp.org.nz`, consistent with production-hostname naming
conventions. The rename is optional WP-6 work and requires an explicit decision;
this runbook does not authorize it.

## Migration invariants

- Preserve the browser-assisted collector and verify collection continuity
  across the migration.
- Do not make downstream Radar logic depend on a particular executor; WP-2 will
  introduce the collector/executor contract.
- GitHub remains canonical; HTTP surfaces are projections.
- Do not retire the existing delivery path before the canonical Worker passes
  controlled and scheduled-cycle verification.
- Do not grant the Radar admin general repository write access. Its current
  write boundary remains `data/reviews/reviews.json`.
- Do not let Radar admin control Eden, HWP, or the private contributor.
- Do not treat `docs/radar/admin-data.json` as the future stable machine API.
- Federal Eagle Operations owns Thor MCP, scheduling, credentials, host
  provisioning, and runtime routing.

## WP-6 migration gates

1. Complete WP-2 through WP-5 and identify the exact certified artifact to
   publish.
2. Record the current canonical GitHub SHA, live routing, rollback target,
   collection freshness, and collector evidence.
3. Decide explicitly whether to rename the repository to
   `jamesbregenzer/radar.wp.org.nz`; update integrations only if approved.
4. Deploy the canonical Worker from an exact GitHub SHA through governed
   Cloudflare custody.
5. Verify dashboard, protected admin, certified API/feed, health/provenance, and
   review write-back in staging.
6. Run a controlled browser-assisted collection and prove that all configured
   feeds publish through the new certified pipeline.
7. Observe at least two consecutive scheduled collector cycles.
8. Attach `radar.wp.org.nz` while preserving the established delivery path as a
   rollback target.
9. Configure `wp.org.nz` and `www.wp.org.nz` redirects to
   `https://wordpress.org/` and verify path/query policy explicitly.
10. Redirect `radar.james.bregenzer.dev` to the canonical Radar hostname while
    preserving required path/query behavior.
11. Retire the old Radar hostname and Pages-era delivery only after the agreed
    rollback window and fresh-data evidence pass.

Any change to these target boundaries or sequencing requires an ADR or explicit
update to `docs/WORDPRESS-AUTOMATION-PROGRAM.md`.
