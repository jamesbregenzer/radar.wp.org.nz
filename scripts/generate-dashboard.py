#!/usr/bin/env python3
"""Generate the public static WP Core Radar dashboard."""

from __future__ import annotations

from collections import Counter
import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from radarcore import DatasetSelection, RunContext, parse_run_time, select_datasets

from radarlib import (
    KEYWORDS_KEYS,
    DATA_RAW,
    TICKET_ID_KEYS,
    STATUS_KEYS,
    SUMMARY_KEYS,
    collect_items,
    discovery_track_label,
    first_value,
    group_items,
    load_queries,
    pretty_label,
    priority_tier,
    signal_class,
    signal_labels,
    ranking_signal_labels,
    score_breakdown,
    trac_url,
)

PUBLIC_TOP_LIMIT = 50


def html_badge(label: str, css_prefix: str = "signal") -> str:
    return f'<span class="{css_prefix}-badge {css_prefix}-{html.escape(signal_class(label))}">{html.escape(label)}</span>'


def signal_badges(keywords: str, reasons: list[str]) -> str:
    """Render compact public signal pills with explicit scoring context."""
    labels = ranking_signal_labels(reasons)

    # Keep non-scoring Trac keywords visible after the scoring rationale because
    # keywords like needs-refresh and needs-screenshots are still useful triage
    # context even when they do not directly affect the score.
    scored_keys = {label.lower().replace("-", " ") for label in labels}
    for keyword_label in signal_labels(keywords, []):
        normalized = keyword_label.lower().replace("-", " ")
        if normalized not in scored_keys:
            labels.append(keyword_label)

    return " ".join(html_badge(label, "signal") for label in labels)


def ticket_row(item: dict[str, Any], duplicate_sources: dict[str, set[str]]) -> str:
    row = item["row"]
    ticket_id = item["ticket_id"]
    tier_class, tier_label = priority_tier(item)

    summary = first_value(row, SUMMARY_KEYS, "Untitled ticket")
    keywords = first_value(row, KEYWORDS_KEYS, "")
    signals = signal_badges(keywords, item["reasons"])
    trac_status = pretty_label(first_value(row, STATUS_KEYS, ""))
    discovery_track = discovery_track_label(duplicate_sources[ticket_id])
    track = item["query"].get("name", item["query"].get("track", "unknown"))

    return f"""
<tr class="tier-{html.escape(tier_class)}">
  <td class="score" data-label="Score">{item["score"]}</td>
  <td data-label="Tier"><span class="tier-label tier-label-{html.escape(tier_class)}">{html.escape(tier_label)}</span></td>
  <td data-label="Ticket"><a href="{html.escape(trac_url(ticket_id))}">#{html.escape(ticket_id)}</a></td>
  <td data-label="Summary">{html.escape(summary)}</td>
  <td data-label="Track">{html.escape(track)}</td>
  <td data-label="Trac Status">{html.escape(trac_status)}</td>
  <td data-label="Discovery Track">{html.escape(discovery_track)}</td>
  <td data-label="Signals" class="signals">{signals}</td>
</tr>
"""


def section_html(
    title: str,
    items: list[dict[str, Any]],
    duplicate_sources: dict[str, set[str]],
    limit: int | None = None,
) -> str:
    display_items = items if limit is None else items[:limit]
    rows = "\n".join(ticket_row(item, duplicate_sources) for item in display_items)

    if not rows:
        rows = '<tr><td colspan="8" class="empty">No tickets in this section.</td></tr>'

    return f"""
<section>
  <h2>{html.escape(title)} <span>{len(items)}</span></h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Score</th>
          <th>Tier</th>
          <th>Ticket</th>
          <th>Summary</th>
          <th>Track</th>
          <th>Trac Status</th>
          <th>Discovery Track</th>
          <th>Signals</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</section>
"""


def dashboard_css() -> str:
    return """
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f6f7f7;
      color: #1d2327;
    }
    header {
      position: relative;
      padding: 32px;
      background: #1d2327;
      color: white;
    }
    .header-content {
      max-width: calc(100% - 160px);
    }
    header h1 {
      margin: 0 0 8px;
      font-size: 32px;
    }
    header p {
      margin: 0;
      color: #c3c4c7;
    }
    .header-actions {
      position: absolute;
      top: 32px;
      right: 32px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .admin-link,
    .header-pill {
      display: inline-flex;
      align-items: center;
      padding: 9px 13px;
      border: 1px solid rgba(255, 255, 255, .24);
      border-radius: 999px;
      background: rgba(255, 255, 255, .1);
      color: #fff;
      font-size: 13px;
      font-weight: 700;
      line-height: 1;
      text-decoration: none;
    }
    .admin-link:hover,
    .header-pill:hover {
      background: rgba(255, 255, 255, .18);
      color: #fff;
      text-decoration: none;
    }
    main {
      padding: 24px 32px 48px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: white;
      border: 1px solid #dcdcde;
      border-radius: 8px;
      padding: 16px;
    }
    .card strong {
      display: block;
      font-size: 28px;
      margin-bottom: 4px;
    }
    .card-blue { border-left: 6px solid #2563eb; }
    .card-purple { border-left: 6px solid #7c3aed; }
    .card-amber { border-left: 6px solid #d97706; }
    section { margin-top: 32px; }
    h2 {
      display: flex;
      gap: 8px;
      align-items: baseline;
    }
    h2 span {
      font-size: 14px;
      color: #646970;
      font-weight: 500;
    }
    .table-wrap {
      overflow-x: auto;
      background: white;
      border: 1px solid #dcdcde;
      border-radius: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid #f0f0f1;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: #f0f0f1;
      white-space: nowrap;
      position: sticky;
      top: 0;
    }
    tr.tier-immediate { border-left: 6px solid #2563eb; }
    tr.tier-strong { border-left: 6px solid #7c3aed; }
    tr.tier-watching { border-left: 6px solid #d97706; }
    tr.tier-standard { border-left: 6px solid transparent; }
    td.score {
      font-weight: 700;
      font-size: 18px;
    }
    .signals { min-width: 300px; }
    .signal-badge,
    .tier-label {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 8px;
      margin: 0 4px 5px 0;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .signal-standard,
    .tier-label-standard { background: #f3f4f6; color: #4b5563; }
    .signal-priority,
    .signal-owner { background: #e0f2fe; color: #075985; }
    .signal-patch,
    .tier-label-immediate { background: #dbeafe; color: #1d4ed8; }
    .signal-testing { background: #dcfce7; color: #166534; }
    .signal-first,
    .tier-label-watching { background: #fef3c7; color: #92400e; }
    .signal-feedback,
    .tier-label-strong { background: #ede9fe; color: #6d28d9; }
    .signal-refresh { background: #ffedd5; color: #9a3412; }
    .signal-recent,
    .signal-freshness { background: #ccfbf1; color: #115e59; }
    .signal-momentum { background: #ecfccb; color: #365314; }
    .signal-age { background: #fef9c3; color: #854d0e; }
    .signal-component { background: #fce7f3; color: #9d174d; }
    .signal-complexity { background: #fee2e2; color: #991b1b; }
    a {
      color: #2271b1;
      font-weight: 600;
    }
    .empty {
      color: #646970;
      font-style: italic;
    }
    footer {
      padding: 24px 32px;
      color: #646970;
      font-size: 13px;
    }
    footer a {
      color: #646970;
      font-weight: 600;
      text-decoration: none;
    }
    footer a:hover {
      color: #2271b1;
      text-decoration: underline;
    }
    .footer-separator {
      margin: 0 6px;
      color: #8c8f94;
    }
    @media (max-width: 900px) {
      header { padding: 24px 18px; }
      .header-content { max-width: none; }
      .header-actions {
        position: static;
        margin-top: 16px;
        justify-content: flex-start;
      }
      header h1 { font-size: 26px; }
      main { padding: 18px; }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      table,
      thead,
      tbody,
      th,
      td,
      tr { display: block; }
      thead { display: none; }
      tr {
        padding: 14px;
        border-bottom: 1px solid #dcdcde;
      }
      td {
        border: 0;
        padding: 6px 0;
      }
      td::before {
        content: attr(data-label);
        display: block;
        color: #646970;
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        margin-bottom: 2px;
      }
      td.score { font-size: 24px; }
    }
    @media (max-width: 520px) {
      .summary { grid-template-columns: 1fr; }
    }
    """


def admin_item_payload(item: dict[str, Any], duplicate_sources: dict[str, set[str]]) -> dict[str, Any]:
    """Return compact structured ticket data for the protected admin UI."""
    row = item["row"]
    ticket_id = item["ticket_id"]
    tier_class, tier_label = priority_tier(item)
    keywords = first_value(row, KEYWORDS_KEYS, "")

    return {
        "ticket_id": ticket_id,
        "url": trac_url(ticket_id),
        "score": item["score"],
        "tier_class": tier_class,
        "tier_label": tier_label,
        "summary": first_value(row, SUMMARY_KEYS, "Untitled ticket"),
        "track": item["query"].get("name", item["query"].get("track", "unknown")),
        "status": pretty_label(first_value(row, STATUS_KEYS, "Unknown")),
        "component": first_value(row, ("component", "Component"), "Unknown"),
        "owner": first_value(row, ("owner", "Owner"), ""),
        "comments": first_value(row, ("comments", "Comments"), "Unknown"),
        "created": first_value(row, ("created", "Created", "time", "Created Time"), "Unknown"),
        "modified": first_value(row, ("modified", "Modified", "changetime", "Change Time"), "Unknown"),
        "keywords": keywords,
        "signals": [
            {"label": label, "class": signal_class(label)}
            for label in ranking_signal_labels(item["reasons"])
        ],
        "score_breakdown": score_breakdown(item["reasons"]),
        "discovery_track": discovery_track_label(duplicate_sources[ticket_id]),
        "review": item.get("review") or {},
    }


def admin_data_payload(context: RunContext | None = None, selection: DatasetSelection | None = None) -> dict[str, Any]:
    """Build structured data used by the protected Cloudflare Worker admin UI."""
    context = context or RunContext.now()
    ranked, duplicate_sources, summary = collect_items(context, selection)
    groups = group_items(ranked)

    return {
        "generated": context.generated_iso,
        "summary": {
            "unique_tickets": len(ranked),
            "priority_targets": len(groups["priority"]),
            "immediate": sum(1 for item in groups["priority"] if priority_tier(item)[0] == "immediate"),
            "strong": sum(1 for item in groups["priority"] if priority_tier(item)[0] == "strong"),
            "watching": sum(1 for item in groups["top"] if priority_tier(item)[0] == "watching"),
            "reviews_loaded": len(summary["reviews"]),
        },
        "groups": {
            name: [admin_item_payload(item, duplicate_sources) for item in items]
            for name, items in groups.items()
        },
    }


def parse_review_datetime(value: str) -> datetime | None:
    """Parse review timestamps for contribution-history ordering."""
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def status_label(status: str) -> str:
    return pretty_label(status or "reviewed")


def contribution_records(
    ranked: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return public-safe contribution/review records enriched with ticket data.

    Reviews are the long-lived archive. Some reviewed or props-producing tickets
    may no longer exist in the current Trac CSV opportunity export, so the
    contribution page must continue to render those historical records with
    graceful fallback labels.
    """
    items_by_ticket = {item["ticket_id"]: item for item in ranked}
    records: list[dict[str, Any]] = []

    for ticket_id, review in reviews.items():
        item = items_by_ticket.get(ticket_id)
        row = item["row"] if item else {}
        tier_class, tier_label = priority_tier(item) if item else ("standard", "Historical")
        updated_at = str(review.get("updated_at", ""))
        parsed_updated = parse_review_datetime(updated_at)
        status = str(review.get("status", "")).strip().lower() or "reviewed"
        received_props = review.get("received_props") is True or status == "props"

        records.append(
            {
                "ticket_id": ticket_id,
                "url": trac_url(ticket_id),
                "summary": first_value(row, SUMMARY_KEYS, "Historical ticket not present in current opportunity data"),
                "component": first_value(row, ("component", "Component"), "Historical") or "Historical",
                "track": item["query"].get("name", item["query"].get("track", "unknown")) if item else "Historical review",
                "score": item["score"] if item else "",
                "tier_class": tier_class,
                "tier_label": tier_label,
                "status": status,
                "reason": str(review.get("reason", "")),
                "notes": str(review.get("notes", "")),
                "received_props": received_props,
                "props_recorded_at": str(review.get("props_recorded_at", "")),
                "changeset": str(review.get("changeset", "")),
                "updated_at": updated_at,
                "updated_dt": parsed_updated,
                "updated_label": parsed_updated.strftime("%b %d, %Y") if parsed_updated else "Unknown",
                "month_label": parsed_updated.strftime("%b %Y") if parsed_updated else "Unknown",
            }
        )

    return sorted(records, key=lambda record: record["updated_dt"] or datetime.min, reverse=True)

def contribution_css() -> str:
    return dashboard_css() + """
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(300px, .8fr);
      gap: 18px;
      align-items: stretch;
      margin-bottom: 24px;
    }
    .hero-card {
      background: white;
      border: 1px solid #dcdcde;
      border-radius: 12px;
      padding: 22px;
      margin-top: 0;
      box-sizing: border-box;
      height: 100%;
    }
    .hero-card h2,
    .hero-card h3 { margin-top: 0; }
    .latest-card {
      display: flex;
      flex-direction: column;
    }
    .latest-card p:last-child { margin-bottom: 0; }
    .hero-card p { color: #50575e; line-height: 1.55; }
    .metric-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .mini-metric {
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      padding: 14px;
      background: #f9fafb;
    }
    .mini-metric strong { display: block; font-size: 28px; margin-bottom: 2px; }
    .mini-metric span { color: #646970; font-size: 13px; }
    .props-card { border-left: 6px solid #d97706; }
    .props-note { color: #646970; font-size: 13px; margin-top: 8px; }
    .chart-card {
      background: white;
      border: 1px solid #dcdcde;
      border-radius: 12px;
      padding: 22px;
      margin-top: 18px;
    }
    .bar-list { display: grid; gap: 12px; }
    .bar-row {
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr) 44px;
      gap: 12px;
      align-items: center;
      font-size: 14px;
    }
    .bar-label { font-weight: 700; }
    .bar-track {
      height: 12px;
      border-radius: 999px;
      background: #eef2f7;
      overflow: hidden;
    }
    .bar-fill {
      display: block;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #2563eb, #7c3aed);
    }
    .timeline { display: grid; gap: 12px; }
    .timeline-item {
      display: grid;
      grid-template-columns: 120px minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      border: 1px solid #dcdcde;
      border-radius: 12px;
      background: white;
    }
    .timeline-date { color: #646970; font-weight: 700; font-size: 13px; }
    .timeline-main strong { display: block; margin-bottom: 6px; }
    .timeline-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .changeset-link { color: #2271b1; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .note-preview { margin-top: 8px; color: #50575e; line-height: 1.45; max-width: 860px; }
    .component-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
    .component-card { background: white; border: 1px solid #dcdcde; border-radius: 10px; padding: 16px; }
    .component-card strong { display: block; font-size: 22px; }
    .component-card span { color: #646970; }
    .contribution-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .footer-pill {
      display: inline-flex;
      align-items: center;
      padding: 9px 13px;
      border: 1px solid #c3c4c7;
      border-radius: 999px;
      background: #fff;
      color: #1d2327;
      font-size: 13px;
      font-weight: 700;
      line-height: 1;
      text-decoration: none;
      white-space: nowrap;
    }
    .footer-pill:hover {
      border-color: #2271b1;
      background: #f0f6fc;
      color: #135e96;
      text-decoration: none;
    }
    @media (max-width: 900px) {
      .hero-grid { grid-template-columns: 1fr; }
      .bar-row { grid-template-columns: 110px minmax(0, 1fr) 36px; }
      .timeline-item { grid-template-columns: 1fr; }
    }
    """


def contribution_bar_chart(title: str, counts: Counter[str], labeler=status_label) -> str:
    if not counts:
        return '<p class="empty">No contribution data yet.</p>'
    max_count = max(counts.values()) or 1
    rows = []
    for key, count in counts.most_common():
        width = max(6, round(count / max_count * 100))
        rows.append(
            f'''<div class="bar-row">
  <div class="bar-label">{html.escape(labeler(key))}</div>
  <div class="bar-track"><span class="bar-fill" style="width: {width}%"></span></div>
  <div>{count}</div>
</div>'''
        )
    return f'''<div class="chart-card"><h3>{html.escape(title)}</h3><div class="bar-list">{"".join(rows)}</div></div>'''


def build_contributions_page(context: RunContext | None = None, selection: DatasetSelection | None = None) -> str:
    context = context or RunContext.now()
    ranked, duplicate_sources, summary = collect_items(context, selection)
    records = contribution_records(ranked, summary["reviews"])
    generated = context.generated_display

    status_counts = Counter(record["status"] for record in records)
    component_counts = Counter(record["component"] for record in records)
    month_counts = Counter(record["month_label"] for record in records)
    month_order = Counter(dict(sorted(month_counts.items(), key=lambda item: next((record["updated_dt"] for record in records if record["month_label"] == item[0]), datetime.min), reverse=True)))
    props_count = sum(1 for record in records if record["received_props"])
    acted_on_count = sum(status_counts.get(status, 0) for status in ("tested", "commented", "committed"))
    props_rate = round((props_count / acted_on_count) * 100) if acted_on_count else 0
    latest = records[0] if records else None

    component_cards = "".join(
        f'''<div class="component-card"><strong>{count}</strong><span>{html.escape(component)}</span></div>'''
        for component, count in component_counts.most_common(8)
    ) or '<p class="empty">No components recorded yet.</p>'

    timeline_rows = []
    for record in records[:20]:
        note = record["notes"].replace("\r\n", "\n").replace("\r", "\n").strip()
        note_preview = " ".join(line.strip() for line in note.splitlines() if line.strip())
        if len(note_preview) > 260:
            note_preview = note_preview[:257].rstrip() + "..."

        props_badge = html_badge("🏆 Props Received", "signal") if record["received_props"] else ""
        changeset_link = ""
        if record["changeset"]:
            changeset = html.escape(record["changeset"])
            changeset_link = f'<a class="changeset-link" href="https://core.trac.wordpress.org/changeset/{changeset}">Changeset {changeset}</a>'

        timeline_rows.append(
            f'''<article class="timeline-item tier-{html.escape(record["tier_class"])}">
  <div class="timeline-date">{html.escape(record["updated_label"])}</div>
  <div class="timeline-main">
    <strong><a href="{html.escape(record["url"])}">#{html.escape(record["ticket_id"])}</a> {html.escape(record["summary"])}</strong>
    <div class="timeline-meta">
      {html_badge(status_label(record["status"]), "signal")}
      {html_badge(record["component"], "signal")}
      {html_badge(record["tier_label"], "tier-label")}
      {props_badge}
      {changeset_link}
    </div>
    <p class="note-preview">{html.escape(record["reason"] or note_preview or "Review recorded.")}</p>
  </div>
</article>'''
        )

    timeline = "".join(timeline_rows) or '<p class="empty">No review activity recorded yet.</p>'
    latest_html = '<p>No activity recorded yet.</p>'
    if latest:
        latest_props = '<br>🏆 Props received' if latest["received_props"] else ''
        latest_html = f'''<p><strong><a href="{html.escape(latest["url"])}">#{html.escape(latest["ticket_id"])}</a></strong><br>{html.escape(status_label(latest["status"]))} — {html.escape(latest["summary"])}{latest_props}</p><p>{html.escape(latest["updated_label"])}</p>'''

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>WP Core Radar Contributions</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
{contribution_css()}
  </style>
</head>
<body>
  <header>
    <div class="header-content">
      <h1>WP Core Radar Contributions</h1>
      <p>Generated {html.escape(generated)}. A public record of human review, testing, and props outcomes powered by WP Core Radar.</p>
    </div>
    <div class="header-actions">
      <a class="header-pill" href="/">Dashboard</a>
      <a class="header-pill" href="/contributions/">Contributions</a>
      <a class="admin-link" href="/admin/">Admin Console</a>
    </div>
  </header>

  <main>
    <div class="hero-grid">
      <section class="hero-card">
        <h2>Contribution history</h2>
        <p>This page turns Radar review decisions into a public contribution record: tickets reviewed, patches tested, areas of focus, and props that were later recorded from WordPress.org. Radar still only recommends opportunities; all WordPress Core contribution actions remain manual and human-reviewed.</p>
        <div class="metric-row">
          <div class="mini-metric"><strong>{len(records)}</strong><span>Tickets reviewed</span></div>
          <div class="mini-metric"><strong>{status_counts.get("tested", 0)}</strong><span>Tickets tested</span></div>
          <div class="mini-metric"><strong>{acted_on_count}</strong><span>Completed / acted on</span></div>
          <div class="mini-metric props-card"><strong>{props_count}</strong><span>Props received</span><div class="props-note">{props_rate}% of acted-on tickets</div></div>
          <div class="mini-metric"><strong>{len(component_counts)}</strong><span>Components touched</span></div>
        </div>
      </section>
      <aside class="hero-card latest-card">
        <h3>Latest activity</h3>
        {latest_html}
      </aside>
    </div>

    <div class="summary">
      <div class="card card-blue"><strong>{status_counts.get("tested", 0)}</strong>Tested</div>
      <div class="card"><strong>{status_counts.get("commented", 0)}</strong>Commented</div>
      <div class="card"><strong>{status_counts.get("watch", 0)}</strong>Watching</div>
      <div class="card"><strong>{status_counts.get("shortlist", 0)}</strong>Shortlisted</div>
      <div class="card"><strong>{status_counts.get("reject", 0)}</strong>Rejected</div>
      <div class="card card-purple"><strong>{status_counts.get("committed", 0)}</strong>Committed</div>
      <div class="card card-amber"><strong>{props_count}</strong>Props received</div>
    </div>

    <section>
      <h2>Decision breakdown <span>{len(records)}</span></h2>
      {contribution_bar_chart("Reviews by decision", status_counts)}
    </section>

    <section>
      <h2>Activity by month <span>{sum(month_counts.values())}</span></h2>
      {contribution_bar_chart("Review activity over time", month_order, lambda value: value)}
    </section>

    <section>
      <h2>Component focus <span>{len(component_counts)}</span></h2>
      <div class="component-grid">{component_cards}</div>
    </section>

    <section>
      <h2>Recent activity <span>{len(records)}</span></h2>
      <div class="timeline">{timeline}</div>
    </section>
  </main>

  <footer class="contribution-footer">
    <span>Generated from public-safe review metadata in <code>data/reviews/reviews.json</code>.</span>
    <a class="footer-pill" href="/">Back to dashboard</a>
  </footer>
</body>
</html>
'''

def build_dashboard(context: RunContext | None = None, selection: DatasetSelection | None = None) -> str:
    context = context or RunContext.now()
    ranked, duplicate_sources, summary = collect_items(context, selection)
    groups = group_items(ranked)
    generated = context.generated_display

    immediate_count = sum(1 for item in groups["priority"] if priority_tier(item)[0] == "immediate")
    strong_count = sum(1 for item in groups["priority"] if priority_tier(item)[0] == "strong")
    watching_count = sum(1 for item in groups["top"] if priority_tier(item)[0] == "watching")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>WP Core Radar Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
{dashboard_css()}
  </style>
</head>
<body>
  <header>
    <div class="header-content">
      <h1>WP Core Radar Dashboard</h1>
      <p>Generated {html.escape(generated)}. Radar recommends opportunities only. Humans make contribution decisions.</p>
    </div>
    <div class="header-actions">
      <a class="header-pill" href="/contributions/">Contributions</a>
      <a class="admin-link" href="/admin/">Admin Console</a>
    </div>
  </header>

  <main>
    <div class="summary">
      <div class="card"><strong>{len(ranked)}</strong>Unique tickets scored</div>
      <div class="card"><strong>{len(groups["priority"])}</strong>Priority targets</div>
      <div class="card card-blue"><strong>{immediate_count}</strong>Immediate Review</div>
      <div class="card card-purple"><strong>{strong_count}</strong>Strong Candidates</div>
      <div class="card card-amber"><strong>{watching_count}</strong>Worth Watching</div>
      <div class="card"><strong>{len(summary["reviews"])}</strong>Reviews loaded</div>
    </div>

    {section_html("Priority Targets", groups["priority"], duplicate_sources)}
    {section_html("Top Opportunities", groups["top"], duplicate_sources, limit=PUBLIC_TOP_LIMIT)}
    {section_html("Shortlisted", groups["shortlist"], duplicate_sources)}
    {section_html("Watching", groups["watch"], duplicate_sources)}
    {section_html("Completed / Acted On", groups["completed"], duplicate_sources)}
    {section_html("Rejected", groups["rejected"], duplicate_sources)}
  </main>

  <footer>
    WP Core Radar does not auto-comment on Trac or automate contribution activity.
  </footer>
</body>
</html>
"""


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
    radar_dir = Path("docs") / "radar"
    radar_dir.mkdir(parents=True, exist_ok=True)

    output = radar_dir / "index.html"
    output.write_text(build_dashboard(context, selection), encoding="utf-8")

    admin_data = radar_dir / "admin-data.json"
    admin_data.write_text(json.dumps(admin_data_payload(context, selection), indent=2) + "\n", encoding="utf-8")

    contributions_dir = radar_dir / "contributions"
    contributions_dir.mkdir(parents=True, exist_ok=True)
    contributions_output = contributions_dir / "index.html"
    contributions_output.write_text(build_contributions_page(context, selection), encoding="utf-8")

    print(f"Wrote {output}")
    print(f"Wrote {admin_data}")
    print(f"Wrote {contributions_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
