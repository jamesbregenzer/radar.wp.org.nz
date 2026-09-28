# Scoring Rubric

WP Core Radar uses deterministic scoring before review. The goal is to surface WordPress Core tickets that are likely to be actionable, useful, and aligned with repeatable contribution work.

The single executable source of truth for scoring values and thresholds is
`config/scoring.json`. `score_ticket()` in `scripts/radarlib.py` applies that
