# `radar.wp.org.nz` migration runbook

This runbook moves WP Core Radar from the current Pages-backed deployment to a
single Cloudflare Worker with Static Assets. GitHub remains authoritative and
Thor remains the Trac collection runtime.

## Invariants

- Do not rename Thor's local directory: `/Users/thor/Sites/wp-core-radar`.
- Do not rename the GitHub repository. It remains
  `jamesbregenzer/wp-core-radar`.
- Do not retire the current Pages project before the new Worker passes the
  controlled collection and scheduled-cycle gates.
- Do not publish a collector snapshot unless all five enabled query exports
  exist and contain a recognized ticket ID column. A valid Trac query may
  return zero tickets, so zero rows is recorded but is not itself a failure.
- Do not grant the Radar admin Worker general repository write access. Its
  write boundary remains `data/reviews/reviews.json`.
- Do not let Radar's admin surface control Eden execution.

## Target

- Repository: `jamesbregenzer/wp-core-radar`
- Worker: `radar-wp-org-nz`
- Canonical host: `radar.wp.org.nz`
- Static assets: `docs/radar`, deployed atomically with the Worker
- Human routes: `/`, `/contributions/`, and protected `/admin/`
- Health routes: `/health/live` and `/health/ready`

## Ordered cutover

1. Merge and validate the Worker-readiness change on the current repository.
2. Record the current main SHA, latest snapshot date, five feed row counts,
   LaunchAgent state, and recent collector logs.
3. Confirm Thor's `origin` still points at
   `https://github.com/jamesbregenzer/wp-core-radar.git`.
4. Dispatch a staging Worker deployment from the exact GitHub SHA through the
   canonical Federal Eagle/Thor Cloudflare runtime. Do not create a second
   repository-specific Cloudflare credential merely for this migration.
5. Run one controlled Thor collection and require
   `scripts/verify-collector-snapshot.py` to pass.
6. Verify the resulting commit, GitHub validation, deployed SHA, dashboard,
   contributions page, admin read/write path, and both health routes.
7. Observe two consecutive automatic six-hour Thor cycles.
8. Attach `radar.wp.org.nz`, preserving the current Pages deployment as the
   rollback target.
9. Redirect `radar.james.bregenzer.dev` to the canonical host while preserving
    path and query string.
10. After a seven-day rollback window with fresh collector data, retire the
    previous Pages deployment.

## Thor remote check

Run this before staging deployment:

```bash
cd /Users/thor/Sites/wp-core-radar
git remote -v
git fetch origin
git pull --rebase origin main
```

The GitHub repository and Thor local folder name are intentionally excluded from
the hostname cutover.
