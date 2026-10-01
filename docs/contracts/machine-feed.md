# Radar Machine Feed Contract

Status: **FROZEN `/api/v1/` CONTRACT**

Radar's HTTP interface is a read-only projection of the verified committed
bundle in `data/certified/current/`. GitHub is durable truth; HTTP, generated
Static Assets, and health documents are not independent authorities.

| Endpoint | Successful body source |
| --- | --- |
| `GET /api/v1/health` | deterministic summary of verified `snapshot.json` |
| `GET /api/v1/snapshot` | byte-preserving `snapshot.v1` artifact |
| `GET /api/v1/collection` | byte-preserving `collection.v1` artifact |
| `GET /api/v1/opportunities` | byte-preserving certified opportunity set |
| `GET /api/v1/opportunities/{ticket_id}` | exact `opportunity.v1` record from that set |
| `GET /api/v1/machine-feed` | compact public-safe `radar-machine-feed.v1` opportunity summary |
| `GET /api/v1/contributions` | public-safe `verified-contribution-outcomes.v1` projection |

`HEAD` is also supported. Other methods return `405 METHOD_NOT_ALLOWED`.
Malformed ticket IDs return `400 MALFORMED_TICKET_ID`; absent tickets return
`404 OPPORTUNITY_NOT_FOUND`. Missing, malformed, hash-inconsistent, or
identity-inconsistent bundles return `503` and never report healthy. Errors use
`radar-error.v1` and reveal no stack, host path, credential, or runtime detail.

Successful responses use `application/json`, include `X-Radar-Snapshot-ID`, and
use `Cache-Control: public, max-age=300, must-revalidate`. Strong ETags are
derived from response SHA-256. An exact `If-None-Match` returns `304`. Unchanged
snapshot bytes therefore retain the same ETag.

The certified snapshot is immutable. Its `radar_state`, if present, is state at
certification time. Current operator reviews, reasons, and private notes live in
the separate GitHub-backed review overlay. Dashboard/admin may apply that
overlay for current human workflow; the machine feed does not mutate or replace
the certified record when reviews change.

## Machine-readable opportunity identity

Every certified `opportunity.v1` record includes:

- `opportunityKey`: deterministic identity in the form `core-trac:{ticketId}`;
- `opportunityRevision`: deterministic hash of material opportunity state.

The revision preimage includes ticket state, discovery tracks, and material
ranking inputs. It excludes generated timestamps, collection artifact paths,
snapshot identity, and API publication details. These fields allow any API user
to distinguish stable opportunity identity from a materially changed record.

Current certified records may also include an advisory `qualification` object.
It describes the likely opportunity class and contribution type, proportionate
evidence profiles, visual-evidence relevance, useful skills, freshness,
duplication risk, likely public channel, engineering weight, and preliminary
eligibility blockers. Qualification is derived only from certified public
ticket signals. It is discovery guidance, not proof that work is still needed,
and does not by itself change a stable opportunity revision.

`/api/v1/machine-feed` contains:

- current snapshot identity and dataset hash;
- ordered `{ticketId, opportunityKey, opportunityRevision, rank, tier, score}`
  records, with the advisory `qualification` projection when available;
- verified public contribution outcomes.

The machine feed is read-only public data. It grants no execution or contribution
authority, contains no credentials, and does not replace live WordPress/Trac
verification.

`/api/v1/contributions` exposes the same verified public outcome projection
without the opportunity list. Outcome records include only public-safe fields:

- `ticketId`;
- `opportunityKey`;
- public contribution URL;
- contribution type;
- tested head and base SHA when known;
- verification timestamp;
- lifecycle state;
- optional changeset;
- optional props flag.

The API is public and its data is designed to be public-safe. Radar does not
identify, document, or depend on specific downstream consumers.

Anyone using Radar data to inform contribution work should independently
revalidate current WordPress/Trac state before acting. Radar is discovery
intelligence, may be stale when consumed, and does not authorize a contribution.
Breaking changes require `/api/v2/` or an explicitly governed compatibility
strategy.
