#!/usr/bin/env python3
"""Generate a unified ranked WP Core Radar opportunity report."""

from __future__ import annotations

import argparse

from radarcore import DatasetSelection, RunContext, parse_run_time, select_datasets

from radarlib import (
    COMMENTS_KEYS,
    COMPONENT_KEYS,
    CREATED_KEYS,
    KEYWORDS_KEYS,
    MILESTONE_KEYS,
    MODIFIED_KEYS,
    OWNER_KEYS,
    REPORTS_DIR,
    DATA_RAW,
    TICKET_ID_KEYS,
    STATUS_KEYS,
    SUMMARY_KEYS,
    collect_items,
    discovery_track_label,
    first_value,
    group_items,
    load_outcomes,
    load_queries,
    load_reviews,
    pretty_label,
    score_breakdown,
    trac_url,
)

REPORT_LIMIT = 50


def append_ticket(lines: list[str], index: int, item: dict, duplicate_sources: dict[str, set[str]]) -> None:
    row = item["row"]
    ticket_id = item["ticket_id"]
    review = item.get("review") or {}

    summary = first_value(row, SUMMARY_KEYS, "Untitled ticket")
    sources = discovery_track_label(duplicate_sources[ticket_id])
    reasons = ", ".join(item["reasons"][:8])

    lines.append(f"#### {index}. [#{ticket_id}]({trac_url(ticket_id)}) — {summary}")
    lines.append("")
    lines.append(f"- Score: **{item['score']}**")
    lines.append(f"- Track/query: {item['query'].get('name', item['query'].get('track', 'unknown'))}")
    lines.append(f"- Discovery track: {sources}")
    lines.append(f"- Component: {first_value(row, COMPONENT_KEYS, 'Unknown')}")
    lines.append(f"- Trac status: {pretty_label(first_value(row, STATUS_KEYS, 'Unknown'))}")

    optional_fields = [
        ("Milestone", first_value(row, MILESTONE_KEYS, "")),
        ("Owner", first_value(row, OWNER_KEYS, "")),
        ("Keywords", first_value(row, KEYWORDS_KEYS, "")),
        ("Comments", first_value(row, COMMENTS_KEYS, "")),
        ("Created", first_value(row, CREATED_KEYS, "")),
        ("Modified", first_value(row, MODIFIED_KEYS, "")),
    ]

    for label, value in optional_fields:
        if value:
            lines.append(f"- {label}: {value}")

    if review:
        review_fields = [
            ("Review status", review.get("status", "")),
            ("Review reason", review.get("reason", "")),
            ("Review notes", review.get("notes", "")),
            ("Review updated", review.get("updated_at", "")),
        ]
        for label, value in review_fields:
            if value:
                lines.append(f"- {label}: {value}")

    lines.append(f"- Why it ranked: {reasons}")
    lines.append("- Score breakdown:")
    for row in score_breakdown(item["reasons"]):
        points = row["points"] or "0"
        lines.append(f"  - {points}: {row['label']}")
    lines.append("- Human next step: open ticket, verify current state, test locally if appropriate, then decide whether to comment manually.")
    lines.append("")


def append_section(
    lines: list[str],
    title: str,
    items: list[dict],
    duplicate_sources: dict[str, set[str]],
    limit: int | None = None,
    empty_message: str = "No tickets in this section.",
) -> None:
    lines.append(f"## {title}")
    lines.append("")

    display_items = items if limit is None else items[:limit]

    if not display_items:
        lines.append(empty_message)
        lines.append("")
        return

    for index, item in enumerate(display_items, start=1):
        append_ticket(lines, index, item, duplicate_sources)


def build_report(limit: int = REPORT_LIMIT, context: RunContext | None = None, selection: DatasetSelection | None = None) -> str:
    context = context or RunContext.now()
    ranked, duplicate_sources, summary = collect_items(context, selection)
    groups = group_items(ranked)
    now = context.generated_display
    outcomes = load_outcomes()
    reviews = load_reviews()
    datasets = summary["datasets"]

    lines: list[str] = []
    lines.append("# WP Core Radar Report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Datasets discovered: {len(datasets)}")
    lines.append(f"- Unique tickets scored: {len(ranked)}")
    lines.append(f"- Outcomes loaded: {len(outcomes)}")
    lines.append(f"- Reviews loaded: {len(reviews)}")
    lines.append(f"- Top opportunity limit: {limit}")
    lines.append("")
    lines.append("## Review Workflow")
    lines.append("")
    lines.append("| Section | Count | Meaning |")
    lines.append("|---|---:|---|")
    lines.append(f"| Priority Targets | {len(groups['priority'])} | Highest-scoring unreviewed tickets with clear action and manageability signals. |")
    lines.append(f"| Top Opportunities | {len(groups['top'])} | Remaining unreviewed tickets ranked by score. |")
    lines.append(f"| Shortlisted | {len(groups['shortlist'])} | Tickets manually marked as strong candidates. |")
    lines.append(f"| Watching | {len(groups['watch'])} | Tickets worth monitoring but not acting on yet. |")
    lines.append(f"| Completed / Acted On | {len(groups['completed'])} | Tickets already tested, commented on, propped, or committed. |")
    lines.append(f"| Rejected | {len(groups['rejected'])} | Tickets manually rejected as poor fits. |")
    lines.append("")

    append_section(lines, "Priority Targets", groups["priority"], duplicate_sources)
    append_section(
        lines,
        "Top Opportunities",
        groups["top"],
        duplicate_sources,
        limit=limit,
        empty_message="No top opportunities found. Run the collector or review rejected/watch statuses.",
    )
    append_section(lines, "Shortlisted", groups["shortlist"], duplicate_sources)
    append_section(lines, "Watching", groups["watch"], duplicate_sources)
    append_section(lines, "Completed / Acted On", groups["completed"], duplicate_sources)
    append_section(lines, "Rejected", groups["rejected"], duplicate_sources)

    lines.append("## Dataset Inventory")
    lines.append("")
    if datasets:
        lines.append("| Query | Date | Rows | File |")
        lines.append("|---|---:|---:|---|")
        for dataset in datasets:
            lines.append(f"| {dataset.query_slug} | {dataset.collected_date} | {dataset.row_count} | `{dataset.path}` |")
    else:
        lines.append("No CSV datasets discovered.")

    lines.append("")
    lines.append("## Guardrail")
    lines.append("")
    lines.append("Radar does not auto-comment on Trac. All contribution decisions remain human-reviewed.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-time", help="ISO-8601 run time for deterministic generation")
    parser.add_argument("--collection-id", help="Use exactly this raw collection identity (YYYY-MM-DD)")
    args = parser.parse_args()
    context = parse_run_time(args.reference_time)
    selection = None
    if args.collection_id:
        selection = select_datasets(DATA_RAW, args.collection_id, [q["slug"] for q in load_queries()], TICKET_ID_KEYS)
        if not selection.complete:
            parser.error(f"collection {args.collection_id} is incomplete or invalid")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(context=context, selection=selection)
    latest = REPORTS_DIR / "latest.md"
    dated = REPORTS_DIR / f"radar-{context.collection_date}.md"
    latest.write_text(report, encoding="utf-8")
    dated.write_text(report, encoding="utf-8")
    print(f"Wrote {latest}")
    print(f"Wrote {dated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
