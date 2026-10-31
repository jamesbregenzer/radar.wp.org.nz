# Archived Core Trac description read

`scripts/description_lookup.py` reads an initial ticket description from a
verified Radar CSV archive. It does not fetch Trac or declare the ticket's
discussion complete.

The caller supplies a trusted SHA-256 of the exact candidate feed, a candidate
ID, and a Core Trac source ID. The reader requires one matching feed candidate
and source membership. It uses that membership's source revision and observed
time to select the corresponding archived `run.json` and raw CSV. It verifies
the observation, raw artifact hash and length, parsed row count, ticket identity,
and every normalized row against the archive. The selected row must exactly
match the membership's delivered evidence. A stale membership reads its own
earlier archive; it never falls forward to the latest run.

The result includes the exact description text, its UTF-8 length and SHA-256,
source and feed identities, observed and ticket modification times, and archive
path. `discussionAvailable` and `contextComplete` are always false. Missing,
ambiguous, conflicting, corrupt, or oversized content is refused. The current
bound is 65,536 UTF-8 bytes for one description, 32 MB for a raw CSV, 40 MB for
a run record, and 50 MB for the candidate feed. This is a local read contract;
no Controller admission or public publication follows from a successful read.
Archive reads are anchored to the supplied raw directory. Every descendant
directory and file is opened without following symbolic links, regular files
are required, and the byte limit is enforced as bytes are read. A file that
changes while being read is refused.

Example using the pinned public archive (the feed hash must come from an
independently trusted source):

```sh
python3 scripts/description_lookup.py \
  --feed data/candidate-feed.json \
  --feed-sha256 40d99420963fa75de83d6b647e6655c4e164a58b29ccd55e7c4016f8559cb26a \
  --candidate-id candidate:v2:44c2748a75a9dccefb99bf0220d62fc0 \
  --source-id core-trac-report-18-release-blockers
```

Future production use needs a pinned feed and its matching retained raw
archives. The existing candidate feed is still a discovery and scoring product;
it does not contain complete ticket comments or authorize engineering work.
