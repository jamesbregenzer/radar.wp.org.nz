# Radar Executor Contract

Status: **WP-4 STABLE CONTRACT**

This contract tells an external executor how to invoke Radar without moving
runtime custody into the product. It does not implement Federal Eagle
Operations, Thor MCP, scheduling, credentials, or host provisioning.

## Executor supplies

- a repository checkout at an identified revision;
- Python and the repository's declared dependencies;
- an ISO-8601 UTC reference time;
- an exact collection ID for downstream operations;
- a full 40-character source-revision SHA for certification/pipeline;
- for `collect` only, the supported local browser/network environment;
- durable log/result capture; and
- any authorization and delivery mechanism after a successful publish plan.

## Invocation

Invoke `python3 scripts/radar.py <operation> ...`. Treat stdout as one canonical
JSON result and stderr as diagnostic logging. Parse stdout as
`execution-result.v1`; do not infer success from files or log text. Exit status
zero means `success` or `no_data_delta`; nonzero means `failure`.

For an already archived collection:

```bash
python3 scripts/radar.py pipeline \
  --skip-collect \
  --collection-id 2026-01-15 \
  --reference-time 2026-01-15T12:00:00Z \
  --source-revision 0123456789abcdef0123456789abcdef01234567
```

Without `--skip-collect`, pipeline invokes the browser-assisted collector. An
executor must not assume that hosted/server or GitHub Actions HTTP collection
works.

## Result handling

Persist the complete result with the executor run record. Use `status`, `code`,
`errors`, and `stage_results` for decisions. Artifact entries are portable
repository/logical paths paired with SHA-256 values. A successful `publish`
result is an eligibility plan only; before performing any external write, the
executor must apply its own authorization policy and confirm the planned hashes
still match.

Retrying with unchanged inputs is safe. Pass `--published-snapshot-id` to
`publish` when known; a matching verified bundle returns `no_data_delta` and
`NO_DATA_DELTA`. Never continue a pipeline after failure, manufacture missing
identities, substitute a moving branch name for source revision, or publish an
unverified bundle.

## Custody boundary

Radar owns deterministic product logic and evidence. The executor owns process
launch, browser availability, time/revision injection, secrets, scheduling,
Git/provider authentication, network routing, publication side effects,
monitoring, retention, retry policy, and any desired scheduling. Radar grants no
WordPress contribution authority: execution capability alone does not grant
WordPress contribution authority.
