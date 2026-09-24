# Vision

`docs/RADAR-PRODUCT.md` is the authoritative product boundary. This document
summarizes Radar's product vision; it does not expand Radar's authority.

## CURRENT IMPLEMENTATION

WP Core Radar is a deterministic, human-in-the-loop contribution intelligence
tool. It collects public WordPress Core Trac CSV data through the proven local
browser workflow, archives the source data in GitHub, explains ticket rankings,
and generates a dashboard, contribution history, reports, and protected review
workflow.

The legacy hostname remains an external rollback/redirect concern during the
controlled migration period.

## TARGET ARCHITECTURE

Radar becomes a reliable, independently useful source of certified WordPress
Core opportunity intelligence at `radar.wp.org.nz`. Its dashboard, admin, and
implemented API/feed project one canonical opportunity model with provenance
and health evidence.

Radar does not modify WordPress.org, comment on Trac, submit patches, or hold
WordPress.org contribution credentials. API consumers must independently
revalidate live WordPress state before acting.

Radar should remain deterministic, explainable, safe by default, respectful of
WordPress.org resources, and small enough to audit. The protected admin surface
may manage Radar review metadata; it does not grant contribution authority.

The target production hostname is `radar.wp.org.nz`, and the approved target
repository is `jamesbregenzer/radar.wp.org.nz`. WP-6 makes the product ready for
both; provider-side rename and production cutover actions remain governed
external work.

Architecture changes require an ADR or an explicit update to
`docs/RADAR-PRODUCT.md` rather than silent drift.
