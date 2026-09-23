# Vision

`docs/WORDPRESS-AUTOMATION-PROGRAM.md` is the authoritative north-star for the
WordPress Automation Program. This document summarizes Radar's product vision;
it does not expand Radar's authority.

## CURRENT IMPLEMENTATION

WP Core Radar is a deterministic, human-in-the-loop contribution intelligence
tool. It collects public WordPress Core Trac CSV data through the proven local
browser workflow, archives the source data in GitHub, explains ticket rankings,
and generates a dashboard, contribution history, reports, and protected review
workflow.

The established live hostname remains `radar.james.bregenzer.dev` during the
migration period.

## TARGET ARCHITECTURE

Radar becomes a reliable, independently useful source of certified WordPress
Core opportunity intelligence at `radar.wp.org.nz`. Its dashboard, admin, and
future API/feed project one canonical opportunity model with provenance and
health evidence.

Radar does not perform autonomous contribution work. A separate private
Federal Eagle WordPress Contributor may consume certified opportunities,
revalidate live state, perform governed engineering work, and deliver public
contributions only through Eden/HWP authorization.

Radar should remain deterministic, explainable, safe by default, respectful of
WordPress.org resources, and small enough to audit. The protected admin surface
may manage Radar review metadata; it must not control the private contributor.

The target production hostname is `radar.wp.org.nz`. Repository renaming to
`jamesbregenzer/radar.wp.org.nz` is proposed for WP-6 but is not approved or
performed by the current architecture freeze.

Architecture changes require an ADR or an explicit update to the authoritative
program document rather than silent drift.
