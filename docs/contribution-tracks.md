# Contribution Tracks

Contribution tracks define the kinds of WordPress Core tickets Radar should collect and prioritize.

The active tracks live in `config/queries.json`. Each track has:

- `slug`: stable machine name used for filenames and source tracking
- `name`: human-readable label shown in reports
- `track`: broad contribution area
- `priority`: baseline score before ticket-level signals are added
- `description`: explanation of why the track exists

## Current tracks

- `media_has_patch`: Media tickets with patches that may be ready for testing or review.
- `accessibility_has_patch`: Accessibility tickets with patches that may need verification.
- `docs_needs_testing`: Documentation tickets where testing or confirmation may help.
- `good_first_bugs`: Beginner-friendly tickets useful for repeatable contribution practice.
- `general_needs_testing`: General tickets where a test report could move the ticket forward.

## Track principles

Tracks should be narrow enough to produce useful candidate lists and broad enough that the collector does not need constant manual tuning.

A new track should only be added when it represents a repeatable contribution path, not a one-off search.
