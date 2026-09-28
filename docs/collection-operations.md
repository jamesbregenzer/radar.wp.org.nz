# Collection Operations

This runbook covers Radar's current browser-assisted collection workflow. It is an operating detail, not part of the opportunity data contract.

## How collection works

The scheduled wrapper is `scripts/run-scheduled-radar.sh`. At startup it fixes one run context containing:

- reference time;
- collection ID;
- source revision; and
- every enabled query from `config/queries.json`.

For each query, `scripts/browser-fetch.py` opens the configured Trac CSV export in Firefox and waits for `query.csv`. `scripts/import-download.py` then validates the download, archives it as `data/raw/manual/<collection-id>/<query-slug>.csv`, and removes the temporary browser file.

The wrapper uses the same run context for collection, validation, generation, certification, verification, and publication planning. This prevents one run from being split across collection identities when it crosses a date boundary.

## Fail-closed behavior

A canonical collecting pipeline requires every enabled query to succeed during that attempt. Existing same-date files cannot fill in for a query that was not collected. A standalone query subset is useful for diagnostics, but it does not establish a complete certifiable collection.

On failure, the wrapper:

1. records ignored evidence under `runtime/scheduled-attempts/`;
2. restores tracked files changed by the failed attempt;
3. leaves the previous certified current dataset untouched; and
4. exits without committing or pushing partial data.

This cleanup prevents a failed run from blocking the next scheduled update while retaining enough evidence for diagnosis.

## Safe validation mode

Use validate-only mode to exercise collection and every downstream check without committing or pushing:

```bash
RADAR_PUBLISH_MODE=validate-only scripts/run-scheduled-radar.sh
```

Accept the run only when all configured queries share one collection identity, certification and verification succeed, no commit or push occurs, evidence is retained, and the checkout returns clean.

## Manual interfaces

Collect all enabled queries through the canonical pipeline:

```bash
python3 scripts/radar.py pipeline \
  --collection-id 2026-01-15 \
  --reference-time 2026-01-15T12:00:00Z \
  --source-revision 0123456789abcdef0123456789abcdef01234567
```

Collect one query for diagnosis:

```bash
python3 scripts/radar.py collect \
  --query general_needs_testing \
  --collection-id 2026-01-15 \
  --reference-time 2026-01-15T12:00:00Z
```

Do not use query subsets in the canonical pipeline. Do not replace the browser collector with direct cloud HTTP collection without proving equivalent reliability and evidence.

## Generated output

Successful generation updates the committed dashboard, report, admin payload, safe review projection, contribution history, and API assets. Publication occurs only after the exact certified bundle verifies successfully.
