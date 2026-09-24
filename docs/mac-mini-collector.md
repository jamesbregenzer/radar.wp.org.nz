# Mac Mini Collector

This document records the **CURRENT IMPLEMENTATION** and
**HISTORICAL/COMPATIBILITY** details of the proven browser-assisted collector.
The authoritative target architecture is
`docs/WORDPRESS-AUTOMATION-PROGRAM.md`.

The local browser environment currently associated with Thor is the
collection/build runner because hosted/server Trac CSV collection has
historically been unreliable or blocked. This known-working path is an
intentional compatibility constraint and must not be redesigned away.

## CURRENT IMPLEMENTATION — responsibilities

The Mac Mini is responsible for:

1. Opening configured WordPress Trac CSV queries in Firefox.
2. Waiting for `query.csv` to finish downloading.
3. Importing the CSV into `data/raw/manual/YYYY-MM-DD/<query_slug>.csv`.
4. Removing the temporary local browser download after a successful import.
5. Regenerating the Markdown report, public dashboard, and admin data export.
6. Committing and pushing changed data/report/dashboard files to GitHub, which
   becomes durable truth after publication.
7. Reconciling the latest review state during scheduled full Radar runs.

The Mac Mini creates `docs/radar/admin-data.json`, which the protected Worker
admin console reads. It does not create, host, authenticate, or migrate the
production `/admin/` page. Scheduled runs still reconcile review writes from
GitHub with regenerated dashboard/admin data, but they are no longer the only
review-sync mechanism. Review-only commits to `data/reviews/reviews.json` are
also handled by GitHub Actions so the dashboard does not remain stale for up to
six hours. Repository paths and remotes in this document are
**HISTORICAL/COMPATIBILITY runtime concerns** owned outside WP-6.

GitHub is the durable source of truth after the collector publishes changes.
The repository contains a Cloudflare Worker plus Static Assets target. The
established Pages-era delivery may remain part of the live/rollback path until
WP-6 migration is deployed and verified.

## CURRENT IMPLEMENTATION — why GitHub Actions does not collect data

GitHub-hosted runners do not have the same local browser/network context as the Mac Mini. Because the Trac export flow depends on that environment, normal GitHub Actions should not replace the collector.

GitHub Actions may still be useful for checks and review-only dashboard regeneration after review commits, but direct hosted collection must not be described as supported unless it is independently proven.

## TARGET ARCHITECTURE — collector contract

WP-2 isolates this browser implementation behind a collector/result boundary.
Downstream validation, normalization, scoring, certification, and
publication will consume explicit collection results rather than depend on
Firefox, Thor, a LaunchAgent, or host paths. The browser implementation remains
valid unless and until a replacement is proven.

Thor MCP, scheduler redesign, credential custody, host provisioning, and runtime
routing belong to Federal Eagle Operations, not Radar core.

## Main commands

Run all enabled query tracks:

```bash
python3 scripts/run-radar.py
```

Run one query track:

```bash
python3 scripts/run-radar.py --query general_needs_testing
```

Skip collection and rebuild reports only:

```bash
python3 scripts/run-radar.py --skip-fetch
```

Continue collecting remaining tracks if one browser fetch fails:

```bash
python3 scripts/run-radar.py --continue-on-error
```

Direct browser-fetch diagnostics must receive the collection identity captured
for that run; they must not derive it from the current wall clock:

```bash
python3 scripts/browser-fetch.py general_needs_testing --collection-id 2026-09-23
```


## Review-only dashboard refreshes

The protected Worker admin console reads the deployed safe review projection
without GitHub credentials. It does not commit review decisions. Durable write
requests fail closed until an approved executor satisfies Radar's persistence
contract.

When an approved source changes `data/reviews/reviews.json`, the refresh Action
regenerates dashboard files. The Mac Mini remains the source of fresh Trac data
and still regenerates dashboard files during full collection runs.

## Generated dashboard files

The dashboard generation step writes both the static dashboard asset and the data payload consumed by the protected Worker admin console:

```text
docs/radar/index.html
docs/radar/admin-data.json
```

The Radar dashboard includes a header link to the protected admin console. The
protected admin route itself is rendered by the Cloudflare Worker, not by the
static asset bundle. References to Pages in older operational material are
historical/rollback context, not an active product dependency.

## HISTORICAL/COMPATIBILITY — scheduled runner

Scheduled collection should use the wrapper script:

```bash
scripts/run-scheduled-radar.sh
```

The wrapper intentionally keeps scheduling, Git synchronization, and publishing
concerns outside the collector itself. At startup it captures one UTC reference
time, its `YYYY-MM-DD` collection identity, the source revision, and the enabled
query set. Those values remain immutable for the entire run, including when the
wall clock crosses a date boundary. It performs this sequence:

1. `git pull --rebase origin main`
2. capture the immutable run context and required query set
3. run canonical `radar collect` for every enabled query with that context
4. verify the exact collection identity through the compatibility verifier
5. run the fail-closed WP-4 pipeline with `--skip-collect` and the same context
6. stage `data`, `docs`, and `reports`
7. if only generated timestamps changed, restore generated files and skip the commit
8. otherwise, commit changed files with `Update radar data`
9. `git pull --rebase origin main` again immediately before push
10. push to `origin/main`

Collection, validation, certification, verification, generation, and
publication planning therefore cannot split across collection dates.

### Failed-run recovery

The wrapper refuses to begin from a dirty worktree. If collection or any later
pipeline stage fails, it records the frozen context, worktree status/diff, and
available collection artifacts beneath ignored `logs/failed-runs/<run-id>/`,
then restores tracked `data`, `docs`, and `reports` and removes only untracked
outputs created in the attempted collection/output locations. The previous
certified current dataset is restored, no partial data is committed, and the
next scheduled pull is not blocked by the failed attempt.

For a controlled proof that exercises the collector and complete pipeline but
never commits or pushes, use:

```bash
RADAR_PUBLISH_MODE=validate-only scripts/run-scheduled-radar.sh
```

The wrapper retains a local evidence summary and restores the attempted
repository changes after a successful validate-only run.

The final pre-push rebase is intentional. Review-only dashboard refreshes may be committed by GitHub Actions while the longer Mac Mini collection job is running; rebasing immediately before push makes the scheduled collector more resilient to those near-real-time updates.

The local LaunchAgent should call the wrapper rather than embedding workflow logic directly in the `.plist` file.

## HISTORICAL/COMPATIBILITY — LaunchAgent cadence

The current recommended cadence is every six hours:

```xml
<key>StartInterval</key>
<integer>21600</integer>
```

Use `RunAtLoad` while testing so the job runs immediately after loading. After the job is confirmed stable, `RunAtLoad` can remain enabled or be removed depending on whether immediate catch-up behavior is desired after login/restart.

## HISTORICAL/COMPATIBILITY — logs

The LaunchAgent writes logs to:

```text
logs/launchagent.out.log
logs/launchagent.err.log
```

Check them with:

```bash
tail -n 100 logs/launchagent.out.log
tail -n 100 logs/launchagent.err.log
```

## HISTORICAL/COMPATIBILITY — macOS privacy note

When the LaunchAgent runs outside Terminal, macOS privacy controls may prevent Python from reading files in `~/Downloads`, even when the same command works manually in Terminal.

If the log contains an error like:

```text
PermissionError: [Errno 1] Operation not permitted: '/Users/thor/Downloads/query.csv'
```

then grant Full Disk Access, or at minimum Files and Folders access for Downloads, to the Python executable used by the scheduled runner:

```text
/usr/local/opt/python@3.14/bin/python3.14
```

This is a macOS permission issue, not a repository or GitHub issue. The manual run can succeed because Terminal already has access, while the LaunchAgent process does not.

## CURRENT IMPLEMENTATION — archive convention

Imported CSV files are archived under:

```text
data/raw/manual/YYYY-MM-DD/<query_slug>.csv
```

This makes dataset history inspectable and lets reports be regenerated from committed raw data.

## HISTORICAL/COMPATIBILITY — timestamp-only change guard

The scheduled wrapper intentionally avoids commits that only update generated timestamps in report/dashboard output. This keeps the repository history useful: scheduled commits should represent fresh raw CSV data, review state changes, or meaningful dashboard/report changes, not a six-hour heartbeat.

The guard currently normalizes timestamp-only differences in:

```text
docs/radar/index.html
docs/radar/admin-data.json
reports/latest.md
reports/radar-YYYY-MM-DD.md
```

If any raw CSV, review JSON, contribution history, or substantive dashboard/report content changes, the wrapper still commits and pushes normally.

Future architecture changes require an ADR or explicit update to
`docs/WORDPRESS-AUTOMATION-PROGRAM.md` rather than silent drift.
