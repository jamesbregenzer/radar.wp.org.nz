# Wave 2 public sources

`config/wave2-sources.json` lists the approved public WordPress and GitHub
endpoints. `scripts/acquire.py` fetches their response bytes into the current
`data/raw/<run-id>/` directory, checks that each response has the JSON shape
required by its adapter, and passes the response through the proven
normalizers in `scripts/wave2_sources.py`.

The normalizers preserve source-native identity, public URLs, source revision,
and explicit contribution signals. Only `CLEAR_OPPORTUNITY` and
`POSSIBLE_OPPORTUNITY` signals become candidate-family mappings. Routine
resources, `NEEDS_MORE_EVIDENCE`, and `NO_CLEAR_CONTRIBUTION` remain evidence
without manufacturing a candidate.

The normalized resources are placed in the same `radar-observation.v2` rows as
Core Trac observations. Processing, scoring, source-health handling, and feed
publication therefore have one input path and one source-observation model.
