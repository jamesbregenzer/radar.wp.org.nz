# Radar V2 scoring policy

`config/scoring.json` is the only scoring configuration. `scripts/process.py`
loads it for every feed build and applies the same deterministic formula to
each normalized resource:

```text
base
+ direct-opportunity bonus, once when present
+ high-confidence family bonus, capped at two families
+ corroborating source-membership bonus, capped at two memberships
+ explicit needs-testing or needs-patch bonus
- stale-evidence penalty
```

The configuration also defines the `priority`, `standard`, and `watch` tier
thresholds. Source overlap preserves memberships but cannot inflate a score
without limit. Closed, resolved, fixed, invalid, and wontfix resources are
excluded before scoring. Unknown signals remain evidence but do not receive
invented points.

The result is emitted in `data/candidate-feed.json`. Radar does not maintain a
second scoring engine, query-priority table, dashboard score, or HTTP API.
