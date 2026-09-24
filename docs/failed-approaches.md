# Failed Approaches and Constraints

This file preserves implementation history and compatibility lessons. The
authoritative Radar product architecture is `docs/RADAR-PRODUCT.md`.

## CURRENT IMPLEMENTATION — replacing browser-assisted collection with hosted collection

Hosted/server collection of WordPress Trac exports has historically been
unreliable or blocked. GitHub-hosted Actions and direct cloud HTTP collection
are therefore not supported collector replacements today.

The proven collector opens configured Trac CSV searches in a browser session in
an allowed local network environment, downloads `query.csv`, imports it into the
raw archive, and deletes the temporary download. Preserve that implementation
until another collector is proven. WP-2 placed it behind a result boundary; it must
not redesign it away.

## HISTORICAL/COMPATIBILITY — local Python admin server

An earlier local Python review-console workflow was retired after the protected
admin console moved into the Cloudflare Worker. Do not reintroduce a public
local write-capable server, commit its secrets, or expose it through a tunnel.

## PRODUCT BOUNDARY — treating Radar as a contribution bot

Radar must not auto-comment on Trac, submit tickets or patches, hold
WordPress.org contribution credentials, or perform contribution actions. Its
output is discovery intelligence, not contribution authorization.

## PRESENTATION LESSON — exposing every raw field

Early dashboard versions exposed too many source columns and resembled a CSV
export. The current dashboard intentionally emphasizes score, tier,
ticket, summary, track, status, discovery track, and signals. Detailed controls
belong on protected surfaces.

## HISTORICAL/COMPATIBILITY — direct GitHub Pages custom-domain publishing

GitHub Pages did not provide the desired routing and protected dynamic admin
surface. The repository now contains a Cloudflare Worker plus Static Assets
target. Deployment and hostname migration remain WP-6 work; committed target
configuration must not be described as already deployed.

Future architectural reversals or exceptions require an ADR or an explicit
update to `docs/RADAR-PRODUCT.md`.
