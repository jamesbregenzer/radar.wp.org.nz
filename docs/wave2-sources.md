# WordPress Observatory Wave 2 Sources

Status: **SOURCE-SIDE CERTIFIED**

Certified: **6 October 2026**

Deployment state: **Not deployed**

Wave 2 adds independently certifiable public source families to Radar V2. Each adapter retains exact raw response bytes, records a retrieval receipt and SHA-256, preserves source-native identity, emits a material revision, reports its own health, extracts explicit relationships, and maps only specific public demand signals to the accepted contribution-family registry.

Source collection does not create executable work, compose human-facing contribution content, schedule activity, or authorize public mutation.

## Certification summary

| Source family | Authoritative source and machine access | Identity and revision | Candidate signals and mapped families | Freshness and health | Quality-yield sample |
| --- | --- | --- | --- | --- | --- |
| `MAKE_TEST_RELEASE_SIGNALS` | [Make Test](https://make.wordpress.org/test/) through the public WordPress REST posts endpoint | WordPress post ID; `modified_gmt`; content hash | Direct, recent calls for testing with authoritative target links. Maps to `CORE_PATCH_TEST`, `GUTENBERG_TEST`, or `BETA_RC_TEST` only when the post supports that target. | Latest 50 modified posts; `PARTIAL`; independently `certified` | 50 resources, 1 current candidate. Meeting notes, schedules, summaries, older calls, and source presence alone produced no candidate. |
| `CONTRIBUTOR_PATHWAYS` | [Contributor Pathways](https://make.wordpress.org/handbook/pathways/) through the public handbook REST endpoint | Handbook post ID; `modified_gmt`; content hash | The exact Review a Pathway Guide resource maps to `PATHWAY_REVIEW`. Parent pages and ordinary guide listings do not. | Complete recursive subtree of 54 pages; `COMPLETE`; independently `certified` | 54 resources, 1 candidate. The quality sample rejected four broad parent-page matches found during the first collection pass. |
| `CORE_DEVELOPER_DOCS` | [WordPress Documentation Issue Tracker](https://github.com/WordPress/Documentation-Issue-Tracker) through the GitHub Issues API | GitHub immutable node ID; issue number alias; `updated_at`; body hash | Open, unassigned DevHub, developer-documentation, developer-note, or Documentation Team handbook issues map to `DOCS_REVIEW`. HelpHub-only records do not. | 100 most recently updated open records; `PARTIAL`; independently `certified` | 100 resources, 20 candidates. The current sample is bounded to Core and developer documentation rather than all end-user documentation work. |
| `ACCESSIBILITY_REQUESTS` | [Make Accessibility](https://make.wordpress.org/accessibility/) through the public WordPress REST posts endpoint | WordPress post ID; `modified_gmt`; content hash | Direct, recent testing, review, or feedback requests map to `ACCESSIBILITY_TEST`. Meeting agendas and notes do not. | Latest 50 modified posts; `PARTIAL`; independently `certified` | 50 resources, 2 candidates: the Accessibility Lab feedback request and the DataForm testing call. |
| `THEME_CHECK_GITHUB` | [WordPress Theme Check](https://github.com/WordPress/theme-check) through the GitHub Issues and Pull Requests APIs | GitHub immutable node ID; issue or PR number alias; `updated_at`; body hash | Recent open, unassigned issues map to `THEME_CHECK_TRIAGE`. A non-draft PR maps to `THEME_CHECK_CODE` only with an explicit review request. | 51 unique current records; `PARTIAL`; independently `certified` | 51 resources, 7 candidates: 6 recent triage candidates and 1 explicitly requested code review. Old open issues remain observable but do not become candidates. |
| `MAKE_THEMES_REQUESTS` | [Make Themes](https://make.wordpress.org/themes/) through the public WordPress REST posts endpoint | WordPress post ID; `modified_gmt`; content hash | Direct, recent theme testing or review requests map to `THEME_REVIEW`. Cross-posts, team updates, and ordinary source presence do not. | Latest 50 modified posts; `PARTIAL`; independently `certified` | 50 resources, 0 candidates. Zero is the accepted result for the current sample. |
| `WORDPRESS_RELEASES` | [WordPress version-check API](https://api.wordpress.org/core/version-check/1.7/) using the beta and development channels | Channel, locale, version, and response identity; exact offer hash | A current beta or release-candidate offer maps to `BETA_RC_TEST`. Stable offers and ordinary alpha/nightly availability remain resources without candidates. | Complete current beta and development channel responses; `COMPLETE`; independently `certified` | 29 resources, 0 candidates. The development channel exposes a current alpha/nightly build, but no beta or RC request is present. |

Themes Trac was evaluated as a possible machine source. Its CSV route returned an interactive browser check instead of authoritative CSV bytes. Radar does not certify or normalize that route. Theme Check GitHub and Make Themes remain the certified Theme-side sources until a reliable authoritative Themes review interface is available.

## Raw acquisition and freshness

`config/wave2-sources.json` defines the authoritative scope for each adapter. `scripts/collect-wave2-sources.py` stores every exact response under a timestamped, append-only `data/raw/sources/<source-family>/` run directory and writes a retrieval receipt containing:

- exact source URL;
- retrieval time;
- HTTP status and public cache revision headers;
- byte length and SHA-256;
- immutable raw artifact path;
- pagination evidence;
- adapter, scope, and acquisition result.

Current normalized snapshots live under `data/sources/`. `scripts/certify-wave2-sources.py` verifies snapshot hashes, source-native identity uniqueness, raw byte hashes, receipt identity, and registry-valid contribution-family signals. A source can fail or go stale without invalidating a healthy independent source family.

## Relationships and feed compatibility

Every normalized resource retains outbound public links. Radar resolves an edge only when the target URL belongs to another observed public resource. The edge records `REFERENCES`, provenance, source snapshot identity, and the two independent resource IDs. A relationship never merges identities.

The 6 October source sample produced 336 explicit Wave 2 relationship edges and 31 Wave 2 candidates. The normal Radar V2 resource, relationship, candidate, change, diagnostics, source-health, family-registry, and score-vector projections accept the new sources without introducing a second lifecycle model.

All candidates retain the accepted score-vector dimensions:

- upstream demand strength;
- expected upstream impact;
- James affinity as `unknown` because Radar does not own private qualification;
- novelty confidence;
- evidence feasibility;
- timeliness;
- estimated execution cost;
- delivery reputational risk.

The derived priority remains ordering-only. It cannot override source integrity, freshness, eligibility, or safety gates.

## Outcome observers

The source adapters expose possible observer inputs without creating follow-up work:

- WordPress post or handbook revisions and supersession;
- GitHub issue assignment, update, closure, or linked documentation revision;
- pull-request review or merge;
- linked Core, Gutenberg, accessibility, or theme resource updates;
- follow-up testing or result-summary posts;
- prerelease offer changes and stable-release supersession.

Observer evidence remains a public observation. Private qualification, execution, human-facing composition, and delivery stay outside Radar.
