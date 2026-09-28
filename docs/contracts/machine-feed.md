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
| `GET /api/v1/machine-feed` | compact `radar-machine-feed.v1` handoff for autonomous consumers |
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

## Autonomous contributor handoff

Every certified `opportunity.v1` record includes:

- `opportunityKey`: deterministic identity in the form `core-trac:{ticketId}`;
- `opportunityRevision`: deterministic hash of material opportunity state.

The revision preimage includes ticket state, discovery tracks, and material
ranking inputs. It excludes generated timestamps, collection artifact paths,
snapshot identity, and API publication details. A Controller can therefore
compare the current snapshot identity and each opportunity revision to decide
whether reevaluation is necessary.

`/api/v1/machine-feed` is the cheapest polling surface for an always-on
Controller. It contains:

- current snapshot identity and dataset hash;
- ordered `{ticketId, opportunityKey, opportunityRevision, rank, tier, score}`;
- verified public contribution outcomes.

The machine feed is a trigger surface only. It does not grant execution
authority, does not contain credentials, and does not replace live Trac/GitHub
revalidation.

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

The API is public and its data is designed to be public-safe. No client should
infer contribution authority from access or from an opportunity record.

A consumer **MUST independently revalidate live WordPress/Trac state before
acting**. Radar is discovery intelligence, may be stale when consumed, and does
not authorize a contribution. Breaking changes require `/api/v2/` or an
explicitly governed compatibility strategy.
