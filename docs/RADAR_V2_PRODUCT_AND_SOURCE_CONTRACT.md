# Radar V2 Product And Source Contract

Radar V2 is the public WordPress opportunity observatory. It turns authoritative public WordPress source observations into normalized resources, source memberships, relationships, opportunity intelligence, and source-neutral candidate feeds.

Radar remains deterministic, read-only, public, and source-neutral. It does not own private work lifecycle, delivery authority, credential custody, scheduling authority, or final personal usefulness decisions.

## Status Vocabulary

Radar uses four distinct status levels. A source, feed, endpoint, or adapter may not skip levels by implication.

`IMPLEMENTED` means the repository contains code, schemas, fixtures, or documentation for the capability.

`CERTIFIED` means deterministic tests and repository certification prove the capability behaves according to the product contract for representative fixtures or committed source artifacts.

`OPERATIONAL` means the capability is connected to its approved recurring acquisition or publication path, has current source observations, truthful health reporting, and readback evidence from the intended runtime or public endpoint.

`MISSION_VALIDATED` means production observations have shown that the capability finds useful, nonduplicative WordPress contribution candidates with acceptable evidence quality and false-positive risk.

No source may be called `OPERATIONAL` merely because a parser, fixture, unit test, canary, or one-off diagnostic succeeds.

## Product Boundaries

Radar owns:

- authoritative public source acquisition contracts
- immutable source observations and receipts
- normalized resources
- source-native identities
- source memberships and public signals
- relationships between public resources
- material changes
- source health
- contribution-family candidate classification
- multidimensional scoring
- public, source-neutral machine-readable candidate feeds
- public contribution and outcome projections after verified public delivery is returned to Radar

Radar does not own:

- private work lifecycle
- scheduling authority
- private queue state
- provider custody
- credential state
- authorization state
- delivery authority
- final personal usefulness decisions

## Core Trac V2 Source Registry

Core Trac V2 discovery is driven by a versioned source registry, not by hardcoded report numbers.

Each registry entry must preserve:

- stable source ID
- WordPress Trac HTML URL
- WordPress Trac CSV URL
- upstream semantic meaning
- source role: `DIRECT_OPPORTUNITY`, `SIGNAL`, or `RECONCILIATION`
- expected fields
- semantic validation expectations
- source freshness expectation
- candidate-family mappings
- source limitations

Report numbers are source locators only. They are not the semantic contract. Radar must preserve expected semantics so upstream report drift can be detected.

Initial Core Trac V2 direct and signal sources:

- report 15: Has Patch + Needs Testing
- report 10: Dev / Bug Wrangler Feedback
- report 11: Reporter Feedback / Steps to Reproduce
- report 12: Needs Unit Tests
- report 13: Has Patch
- report 14: Needs Early Attention
- report 16: Needs Patch
- report 18: Release Blockers
- report 21: Latest Tickets
- report 22: Active Tickets
- report 36: Needs User Docs
- report 44: Good First Bugs
- report 45: Needs Patch but none uploaded
- report 46: Patches to Defects Needing Review
- report 69: Bugs Needing Reproduction
- report 1: broad active-ticket reconciliation
- custom query: `needs-testing` and not `has-patch`

The existing five V1 queries remain available only for `/api/v1/` compatibility and must be marked `LEGACY_V1_COMPATIBILITY`. They are not the primary Core Trac V2 discovery source.

## V2 Data Model

Radar V2 processing follows this flow:

```text
immutable observation
-> normalized resource
-> source memberships and signals
-> relationships
-> opportunity intelligence
-> candidate feed
```

For Core Trac, one Trac ticket ID is one normalized resource. If a ticket appears in several reports, Radar preserves every source membership and signal on the same resource. It must not create duplicate resources or candidates merely because source reports overlap.

Example:

```text
ticket 123
  report15
  report13
  report22
  report18
```

This remains one canonical Core resource. Demand, timeliness, release urgency, and review evidence are derived from all four observations.

## Source Failure Policy

One failed source must not invalidate unrelated successful source observations.

Last known good source observations remain available with truthful health state. Source health must become degraded or stale when a source fails, disappears, or is not refreshed within its freshness expectation.

Radar must never publish a false `COMPLETE` state. A source family can be partially healthy when some source shards are current and others are failed or stale.

Source disappearance must not delete a previously observed resource or candidate without a material change record and enough evidence to classify the resource as no longer actionable.

## Observation Contract

Prepared source observations contain:

- `runId`
- `scheduledSlot`
- `observedAt`
- `startedAt`
- `completedAt`
- `sourceId`
- exact upstream URL
- artifact hash
- row count
- semantic validation
- acquisition result
- source revision
- publication and readback state

Observation identity is timestamped per run. Resource and candidate identity are stable across observation timestamp noise.

## V2 Candidate Feed Contract

`/api/v2/candidate-feed` is the stable machine feed for public Radar candidates. Candidate records contain at minimum:

- `candidateId`
- `opportunityId`
- `resourceRefs`
- `relationships`
- `sourceFamilies`
- `sourceMemberships`
- `sourceRevision`
- `observedAt`
- `freshness`
- `familyCandidates`
- `scoreVector`
- `derivedPriority`
- `estimatedExecutionClass`
- `whyNow`
- `sourceHealth`
- `changeInformation`

The feed is source-neutral. Consumers should not need to understand Trac report numbers to interpret candidate meaning.

Radar may expose public opportunity intelligence, candidate families, scoring dimensions, source evidence, freshness, and limitations. Radar must not encode downstream private lifecycle, queue, delivery, credential, authorization, or final decision state.

## Contribution Return Contract

Radar accepts verified public delivery and outcome records from downstream contribution systems when those records are public-safe and source-backed.

The return contract is:

```text
verified public delivery or outcome
-> Radar contribution record
-> Radar contribution and outcome projection
```

A contribution return record must include:

- stable return ID
- public delivery URL
- public outcome URL when available
- source resource reference
- source family
- public contribution type
- observed public delivery time
- verified public outcome time when available
- verification source
- outcome flags, such as accepted, merged, closed, reopened, props observed, or follow-up needed
- public-safe summary
- source revision or observation reference

This allows public contributions such as Core ticket comments, patches, test reports, reviews, and outcomes to be reflected automatically. Radar should not depend on stale manual maintenance of `data/public-contributions.json` when a verified public return feed is available.

Radar contribution records remain public projections. They do not expose private delivery authority, queue state, or private causality.

## Current Acceptance Boundary

This contract authorizes repository implementation and certification work only. It does not certify production deployment, recurring acquisition, source freshness, or mission yield.

The first acceptable repository increment is:

- this contract
- a versioned Core Trac V2 source registry
- deterministic observation and normalization code
- overlap-safe resource and candidate identity
- source health behavior for failed and stale shards
- candidate-feed stabilization
- contribution return ingestion contract
- deterministic tests for the approved edge cases

Production deployment and mission validation remain separate acceptance gates.
