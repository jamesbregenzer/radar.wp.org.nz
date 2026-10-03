#!/usr/bin/env python3
"""Generate the static WP Core Radar dashboard asset."""

from __future__ import annotations

from collections import Counter
import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from radarcore import DatasetSelection, RunContext, parse_run_time, select_datasets
from certifiedmodel import load_certified_projection

from radarlib import (
    KEYWORDS_KEYS,
    DATA_RAW,
    TICKET_ID_KEYS,
    STATUS_KEYS,
    SUMMARY_KEYS,
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
CONTRIBUTION_STATE = Path("data") / "contributions" / "contribution-state.json"
PUBLIC_CONTRIBUTIONS = Path("data") / "public-contributions.json"
PUBLIC_CONTRIBUTION_SOURCE_KINDS = {
    "wordpress_core_trac",
    "wordpress_trac_mail_archive",
    "wordpress_github",
    "wordpress_org_profile",
}
PRIVATE_CONTRIBUTION_TERMS = (
    "contributor automation",
    "contributor controller",
    "automation identity",
    "thor",
    "sentinel",
    "eden",
    "private hwp",
    "private queue",
    "internal ledger",
    "authorization hash",
)


def opportunity_data(context: RunContext, selection: DatasetSelection | None = None):
    """Use certified truth; ``selection`` remains a call-signature compatibility input."""
    return load_certified_projection()


def html_badge(label: str, css_prefix: str = "signal") -> str:
    return f'<span class="{css_prefix}-badge {css_prefix}-{html.escape(signal_class(label))}">{html.escape(label)}</span>'


def signal_badges(keywords: str, reasons: list[str]) -> str:
    """Render the most useful public signal pills without overwhelming a row."""
    labels = ranking_signal_labels(reasons)

    # Keep non-scoring Trac keywords available after the scoring rationale because
    # keywords like needs-refresh and needs-screenshots are still useful triage
    # context even when they do not directly affect the score.
    scored_keys = {label.lower().replace("-", " ") for label in labels}
    for keyword_label in signal_labels(keywords, []):
        normalized = keyword_label.lower().replace("-", " ")
        if normalized not in scored_keys:
            labels.append(keyword_label)

    visible = labels[:4]
    hidden = labels[4:]
    rendered = " ".join(html_badge(label, "signal") for label in visible)
    if hidden:
        extra = " ".join(html_badge(label, "signal") for label in hidden)
        rendered += (
            f' <details class="signal-more"><summary>+{len(hidden)} more</summary>'
            f'<span class="signal-more-items">{extra}</span></details>'
        )
    return rendered


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
    .signal-more {
      display: inline-block;
      position: relative;
      vertical-align: top;
    }
    .signal-more summary {
      display: inline-block;
      cursor: pointer;
      border-radius: 999px;
      padding: 4px 8px;
      margin: 0 4px 5px 0;
      background: #f3f4f6;
      color: #4b5563;
      font-size: 12px;
      font-weight: 700;
      list-style: none;
    }
    .signal-more summary::-webkit-details-marker { display: none; }
    .signal-more-items {
      display: block;
      margin-top: 4px;
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
    }
    .status-detail {
      margin-top: 14px;
      color: #50575e;
      line-height: 1.55;
    }
    .technical-details {
      margin-top: 14px;
      padding: 12px 14px;
      border: 1px solid #dcdcde;
      border-radius: 8px;
      background: #fff;
    }
    .technical-details summary {
      cursor: pointer;
      font-weight: 700;
    }
    .technical-details p {
      margin-bottom: 0;
      color: #50575e;
      line-height: 1.55;
    }
    .scoring-explainer {
      background: #fff;
      border: 1px solid #dcdcde;
      border-radius: 8px;
      padding: 18px;
      line-height: 1.6;
    }
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


def safe_review_projection(review: dict[str, Any] | None) -> dict[str, Any]:
    """Return deployed operator-safe review state.

    Free-form review notes are intentionally excluded from deployed Static Assets.
    GitHub remains durable truth for the complete review record.
    """
    review = review or {}
    safe: dict[str, Any] = {}
    for key in ("status", "reason", "updated_at", "props_recorded_at", "changeset"):
        value = str(review.get(key, "")).strip()
        if value:
            safe[key] = value
    if review.get("received_props") is True:
        safe["received_props"] = True
    return safe


def review_state_payload(reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic credential-free runtime review projection."""
    return {
        "schema": "radar-review-state.v1",
        "version": 1,
        "reviews": {
            ticket: safe_review_projection(review)
            for ticket, review in sorted(reviews.items(), key=lambda item: int(item[0]))
        },
    }


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
        "review": safe_review_projection(item.get("review")),
    }


def admin_data_payload(context: RunContext | None = None, selection: DatasetSelection | None = None) -> dict[str, Any]:
    """Build structured data used by the protected Cloudflare Worker admin UI."""
    context = context or parse_run_time(None)
    ranked, duplicate_sources, summary = opportunity_data(context, selection)
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
            "certification": summary["certification"],
        },
        "groups": {
            name: [admin_item_payload(item, duplicate_sources) for item in items]
            for name, items in groups.items()
        },
    }


def load_contribution_state(path: Path = CONTRIBUTION_STATE) -> dict[str, Any]:
    """Load the public-safe contribution ledger.

    Only PUBLIC_DELIVERY_VERIFIED records are eligible for public rendering.
    Reviews, watches, rejections, and test work without verified public delivery
    stay in the private/admin review model.
    """
    if not path.exists():
        return {"schema": "contribution-state.v1", "version": 1, "contributions": []}

    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema") != "contribution-state.v1"
        or payload.get("version") != 1
        or not isinstance(payload.get("contributions"), list)
    ):
        raise ValueError("CONTRIBUTION_STATE_INVALID")
    return payload


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
    contribution_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only verified public contribution records enriched with ticket data."""
    items_by_ticket = {item["ticket_id"]: item for item in ranked}
    records: list[dict[str, Any]] = []

    for contribution in contribution_state.get("contributions", []):
        if contribution.get("lifecycle_state") != "PUBLIC_DELIVERY_VERIFIED":
            continue

        ticket_id = str(contribution.get("ticket_id", "")).strip()
        if not ticket_id.isdigit():
            continue

        item = items_by_ticket.get(ticket_id)
        row = item["row"] if item else {}
        tier_class, tier_label = priority_tier(item) if item else ("standard", "Historical")
        updated_at = str(contribution.get("updated_at", ""))
        parsed_updated = parse_review_datetime(updated_at)
        status = str(contribution.get("status", "commented")).strip().lower() or "commented"
        received_props = contribution.get("received_props") is True and bool(contribution.get("props_observed_at"))

        records.append(
            {
                "ticket_id": ticket_id,
                "url": str(contribution.get("public_url") or trac_url(ticket_id)),
                "summary": first_value(row, SUMMARY_KEYS, str(contribution.get("summary") or "Verified WordPress Core contribution")),
                "component": first_value(row, ("component", "Component"), str(contribution.get("component") or "Historical")) or "Historical",
                "track": item["query"].get("name", item["query"].get("track", "unknown")) if item else str(contribution.get("track") or "Verified contribution"),
                "score": item["score"] if item else "",
                "tier_class": tier_class,
                "tier_label": tier_label,
                "status": status,
                "reason": str(contribution.get("reason") or "Public delivery verified."),
                "notes": "",
                "received_props": received_props,
                "props_recorded_at": str(contribution.get("props_observed_at", "")) if received_props else "",
                "changeset": str(contribution.get("changeset", "")) if received_props else "",
                "tested_sha": str(contribution.get("tested_sha", "")),
                "updated_at": updated_at,
                "updated_dt": parsed_updated,
                "updated_label": parsed_updated.strftime("%b %d, %Y") if parsed_updated else "Unknown",
                "month_label": parsed_updated.strftime("%b %Y") if parsed_updated else "Unknown",
            }
        )

    return sorted(records, key=lambda record: record["updated_dt"] or datetime.min, reverse=True)


def all_public_source_kinds(record: dict[str, Any]) -> list[str]:
    """Return every declared evidence source kind for a public contribution."""
    kinds: list[str] = []
    for evidence in record.get("evidence", []):
        kinds.append(str(evidence.get("kind", "")))
    for outcome in record.get("outcomes", []):
        for evidence in outcome.get("evidence", []):
            kinds.append(str(evidence.get("kind", "")))
    return kinds


def validate_public_contribution_record(record: dict[str, Any]) -> None:
    """Fail closed when a public contribution record leaks private provenance."""
    required = {
        "id", "ticket_id", "ticket_url", "title", "component", "public_status",
        "contribution_type", "contribution_date", "contribution_link",
        "contribution_summary", "evidence", "opportunity", "outcomes",
        "outcome_flags",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"public contribution {record.get('id', '<unknown>')} missing {', '.join(missing)}")

    serialized = json.dumps(record, sort_keys=True).lower()
    for term in PRIVATE_CONTRIBUTION_TERMS:
        if term in serialized:
            raise ValueError(f"public contribution {record['id']} contains private implementation term")

    for source_kind in all_public_source_kinds(record):
        if source_kind not in PUBLIC_CONTRIBUTION_SOURCE_KINDS:
            raise ValueError(f"public contribution {record['id']} uses unsupported source {source_kind}")

    opportunity = record.get("opportunity", {})
    if opportunity.get("source") != "deterministic_ticket_id":
        raise ValueError(f"public contribution {record['id']} lacks deterministic opportunity identity")
    if str(opportunity.get("identity", "")) != f"core-trac:{record['ticket_id']}":
        raise ValueError(f"public contribution {record['id']} has mismatched opportunity identity")

    flags = record.get("outcome_flags", {})
    if flags.get("merged") and not any(outcome.get("type") == "merged" for outcome in record.get("outcomes", [])):
        raise ValueError(f"public contribution {record['id']} claims merge without public merge outcome")
    if flags.get("resolved") and not any(outcome.get("type") == "resolved" for outcome in record.get("outcomes", [])):
        raise ValueError(f"public contribution {record['id']} claims resolution without public resolution outcome")


def load_public_contribution_payload(path: Path = PUBLIC_CONTRIBUTIONS) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "radar-public-contributions.v1":
        raise ValueError("public contributions payload has an unsupported schema")
    allowed = set(payload.get("source_contract", {}).get("allowed_source_kinds", []))
    if not allowed.issubset(PUBLIC_CONTRIBUTION_SOURCE_KINDS):
        raise ValueError("public contributions source contract includes unsupported source kinds")
    if payload.get("source_contract", {}).get("private_source_kinds"):
        raise ValueError("public contributions source contract cannot declare private sources")
    for record in payload.get("contributions", []):
        validate_public_contribution_record(record)
    return payload


def parse_public_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def public_contribution_records(path: Path = PUBLIC_CONTRIBUTIONS) -> list[dict[str, Any]]:
    payload = load_public_contribution_payload(path)
    records: dict[str, dict[str, Any]] = {}
    for record in payload.get("contributions", []):
        current = records.get(record["id"])
        if current is None:
            records[record["id"]] = record
            continue
        current_date = parse_public_date(current["contribution_date"]) or datetime.min
        next_date = parse_public_date(record["contribution_date"]) or datetime.min
        if next_date > current_date:
            records[record["id"]] = record
    return sorted(
        records.values(),
        key=lambda record: parse_public_date(record["contribution_date"]) or datetime.min,
        reverse=True,
    )


def latest_public_outcome(record: dict[str, Any]) -> dict[str, Any] | None:
    outcomes = record.get("outcomes", [])
    if not outcomes:
        return None
    return sorted(
        outcomes,
        key=lambda outcome: parse_public_date(str(outcome.get("date", ""))) or datetime.min,
        reverse=True,
    )[0]


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
    .record-grid {
      display: grid;
      gap: 16px;
    }
    .contribution-record {
      background: white;
      border: 1px solid #dcdcde;
      border-left: 6px solid #2563eb;
      border-radius: 10px;
      padding: 18px;
    }
    .contribution-record h3 {
      margin: 0 0 8px;
      font-size: 20px;
      line-height: 1.25;
    }
    .record-meta,
    .source-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0;
    }
    .record-summary,
    .outcome-summary {
      color: #50575e;
      line-height: 1.55;
    }
    .record-outcome {
      margin-top: 14px;
      padding: 14px;
      border: 1px solid #dbeafe;
      border-radius: 8px;
      background: #f8fbff;
    }
    .record-outcome strong {
      display: block;
      margin-bottom: 6px;
    }
    .source-link {
      display: inline-flex;
      align-items: center;
      padding: 7px 10px;
      border: 1px solid #dcdcde;
      border-radius: 999px;
      background: #fff;
      color: #2271b1;
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
    }
    .source-link:hover {
      border-color: #2271b1;
      background: #f0f6fc;
      color: #135e96;
      text-decoration: none;
    }
    .lifecycle {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }
    .lifecycle-step {
      border: 1px solid #dcdcde;
      border-radius: 8px;
      padding: 12px;
      background: #fff;
    }
    .lifecycle-step strong {
      display: block;
      margin-bottom: 4px;
    }
    .lifecycle-step span {
      color: #646970;
      font-size: 13px;
    }
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
      .lifecycle { grid-template-columns: 1fr; }
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
    context = context or parse_run_time(None)
    records = public_contribution_records()
    generated = context.generated_display

    type_counts = Counter(record["contribution_type"] for record in records)
    component_counts = Counter(record["component"] for record in records)
    status_counts = Counter(record["public_status"] for record in records)
    confirmed_count = sum(1 for record in records if record["outcome_flags"].get("confirmed"))
    incorporated_count = sum(1 for record in records if record["outcome_flags"].get("incorporated"))
    merged_count = sum(1 for record in records if record["outcome_flags"].get("merged"))
    resolved_count = sum(1 for record in records if record["outcome_flags"].get("resolved"))
    linked_count = sum(1 for record in records if record.get("opportunity", {}).get("source") == "deterministic_ticket_id")
    latest = records[0] if records else None

    component_cards = "".join(
        f'''<div class="component-card"><strong>{count}</strong><span>{html.escape(component)}</span></div>'''
        for component, count in component_counts.most_common(8)
    ) or '<p class="empty">No components recorded yet.</p>'

    record_cards = []
    for record in records:
        parsed_date = parse_public_date(record["contribution_date"])
        contribution_date = parsed_date.strftime("%b %d, %Y") if parsed_date else html.escape(record["contribution_date"])
        outcome = latest_public_outcome(record)
        outcome_html = '<p class="empty">No downstream public outcome recorded yet.</p>'
        if outcome:
            outcome_date = parse_public_date(str(outcome.get("date", "")))
            outcome_label = outcome_date.strftime("%b %d, %Y") if outcome_date else str(outcome.get("date", ""))
            outcome_sources = "".join(
                f'<a class="source-link" href="{html.escape(source["url"])}">{html.escape(source["label"])}</a>'
                for source in outcome.get("evidence", [])
            )
            outcome_html = f'''<div class="record-outcome">
  <strong>{html.escape(outcome["label"])}</strong>
  <div class="timeline-date">{html.escape(outcome_label)}</div>
  <p class="outcome-summary">{html.escape(outcome["summary"])}</p>
  <div class="source-list">{outcome_sources}</div>
</div>'''

        evidence_links = "".join(
            f'<a class="source-link" href="{html.escape(source["url"])}">{html.escape(source["label"])}</a>'
            for source in record.get("evidence", [])
        )
        flags = record["outcome_flags"]
        flag_badges = "".join(
            html_badge(label, "signal")
            for label, active in (
                ("Confirmed", flags.get("confirmed")),
                ("Incorporated", flags.get("incorporated")),
                ("Merged", flags.get("merged")),
                ("Resolved", flags.get("resolved")),
                ("Props", flags.get("public_props")),
            )
            if active
        ) or html_badge("Outcome pending", "signal")
        opportunity_url = record["opportunity"]["url"]

        record_cards.append(
            f'''<article class="contribution-record">
  <h3><a href="{html.escape(record["ticket_url"])}">#{html.escape(record["ticket_id"])}</a> {html.escape(record["title"])}</h3>
  <div class="record-meta">
    {html_badge(record["contribution_type"], "signal")}
    {html_badge(record["component"], "signal")}
    {html_badge(status_label(record["public_status"]), "signal")}
    {flag_badges}
  </div>
  <p class="record-summary">{html.escape(record["contribution_summary"])}</p>
  <div class="source-list">
    <a class="source-link" href="{html.escape(record["contribution_link"])}">Public contribution</a>
    <a class="source-link" href="{html.escape(opportunity_url)}">Radar opportunity</a>
    {evidence_links}
  </div>
  <div class="timeline-date">{html.escape(contribution_date)}</div>
  {outcome_html}
</article>'''
        )

    record_grid = "".join(record_cards) or '<p class="empty">No public contributions recorded yet.</p>'
    latest_html = '<p>No public contribution recorded yet.</p>'
    if latest:
        latest_outcome = latest_public_outcome(latest)
        latest_outcome_text = latest_outcome["label"] if latest_outcome else "Outcome pending"
        latest_html = f'''<p><strong><a href="{html.escape(latest["ticket_url"])}">#{html.escape(latest["ticket_id"])}</a></strong><br>{html.escape(latest["title"])}</p><p>{html.escape(latest_outcome_text)}</p>'''

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
      <p>Generated {html.escape(generated)}. Public WordPress contribution history with downstream outcomes.</p>
    </div>
    <div class="header-actions">
      <a class="header-pill" href="/">Dashboard</a>
      <a class="header-pill" href="/contributions/">Contributions</a>
    </div>
  </header>

  <main>
    <div class="hero-grid">
      <section class="hero-card">
        <h2>Contribution outcomes</h2>
        <p>This page tracks public WordPress contributions from James and the public response that followed. Each record is built from WordPress Core Trac, public WordPress GitHub activity, or other public WordPress sources.</p>
        <div class="lifecycle">
          <div class="lifecycle-step"><strong>Opportunity</strong><span>Radar identifies a public ticket or PR.</span></div>
          <div class="lifecycle-step"><strong>Public contribution</strong><span>James contributes public evidence, diagnosis, review, patch, or validation.</span></div>
          <div class="lifecycle-step"><strong>Upstream response</strong><span>Other contributors respond, test, update, or adopt the work.</span></div>
          <div class="lifecycle-step"><strong>Outcome</strong><span>The ticket moves toward confirmation, merge, resolution, or credit.</span></div>
        </div>
        <div class="metric-row">
          <div class="mini-metric"><strong>{len(records)}</strong><span>Public contributions</span></div>
          <div class="mini-metric"><strong>{linked_count}</strong><span>Linked opportunities</span></div>
          <div class="mini-metric"><strong>{confirmed_count}</strong><span>Confirmed outcomes</span></div>
          <div class="mini-metric"><strong>{incorporated_count}</strong><span>Incorporated outcomes</span></div>
          <div class="mini-metric"><strong>{merged_count}</strong><span>Merged</span></div>
          <div class="mini-metric"><strong>{resolved_count}</strong><span>Resolved</span></div>
        </div>
      </section>
      <aside class="hero-card latest-card">
        <h3>Latest contribution</h3>
        {latest_html}
      </aside>
    </div>

    <div class="summary">
      <div class="card card-blue"><strong>{type_counts.get("observation / diagnosis", 0)}</strong>Observation / diagnosis</div>
      <div class="card"><strong>{type_counts.get("reproduction", 0)}</strong>Reproduction</div>
      <div class="card"><strong>{type_counts.get("test report", 0)}</strong>Test report</div>
      <div class="card"><strong>{type_counts.get("patch", 0)}</strong>Patch</div>
      <div class="card card-purple"><strong>{type_counts.get("review / verification", 0)}</strong>Review / verification</div>
      <div class="card card-amber"><strong>{confirmed_count}</strong>Confirmed</div>
    </div>

    <section>
      <h2>Contribution types <span>{len(records)}</span></h2>
      {contribution_bar_chart("Types by public evidence", type_counts, lambda value: value)}
    </section>

    <section>
      <h2>Public ticket status <span>{len(status_counts)}</span></h2>
      {contribution_bar_chart("Status by public ticket state", status_counts)}
    </section>

    <section>
      <h2>Component focus <span>{len(component_counts)}</span></h2>
      <div class="component-grid">{component_cards}</div>
    </section>

    <section>
      <h2>Public contributions and outcomes <span>{len(records)}</span></h2>
      <div class="record-grid">{record_grid}</div>
    </section>
  </main>

  <footer class="contribution-footer">
    <span>Generated from public WordPress source records in <code>data/public-contributions.json</code>.</span>
    <a class="footer-pill" href="/">Back to dashboard</a>
  </footer>
</body>
</html>
'''

def build_dashboard(context: RunContext | None = None, selection: DatasetSelection | None = None) -> str:
    context = context or parse_run_time(None)
    ranked, duplicate_sources, summary = opportunity_data(context, selection)
    groups = group_items(ranked)
    certification = summary["certification"]
    generated = certification["reference_time"]
    verified_contributions = len(public_contribution_records())

    immediate_count = sum(1 for item in groups["priority"] if priority_tier(item)[0] == "immediate")
    strong_count = sum(1 for item in groups["priority"] if priority_tier(item)[0] == "strong")
    watching_count = sum(1 for item in groups["top"] if priority_tier(item)[0] == "watching")
    warnings = certification["warnings"]
    data_status = "Current" if certification["state"] == "certified" and not warnings else "Attention"
    warning_label = "None" if not warnings else str(len(warnings))

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
      <p>Updated {html.escape(generated)}. Public WordPress Core opportunity intelligence.</p>
    </div>
    <div class="header-actions">
      <a class="header-pill" href="/contributions/">Contributions</a>
      <a class="admin-link" href="/admin/">Admin Console</a>
    </div>
  </header>

  <main>
    <div class="summary">
      <div class="card"><strong>{len(ranked)}</strong>Opportunities scored</div>
      <div class="card card-blue"><strong>{immediate_count}</strong>Immediate Review</div>
      <div class="card card-purple"><strong>{strong_count}</strong>Strong Candidates</div>
      <div class="card card-amber"><strong>{watching_count}</strong>Worth Watching</div>
      <div class="card"><strong>{verified_contributions}</strong>Verified contributions</div>
      <div class="card"><strong>{html.escape(certification["reference_time"][:10])}</strong>Last updated</div>
    </div>

    <section aria-labelledby="data-status">
      <h2 id="data-status">Data status</h2>
      <div class="status-grid">
        <div class="card card-blue"><strong>{html.escape(data_status)}</strong>Dataset</div>
        <div class="card"><strong>{len(ranked)}</strong>Tickets processed</div>
        <div class="card"><strong>{html.escape(certification["reference_time"][:10])}</strong>Updated</div>
        <div class="card"><strong>{html.escape(warning_label)}</strong>Warnings</div>
      </div>
      <p class="status-detail">The dashboard is generated from the current verified Radar dataset. Scores help prioritize where to look first; current Trac state should still be checked before contributing.</p>
      <details class="technical-details">
        <summary>Technical details</summary>
        <p>
          Scoring version <code>{html.escape(certification["scoring_version"])}</code> ·
          Snapshot <code>{html.escape(certification["snapshot_id"])}</code> ·
          Collection <code>{html.escape(certification["collection_id"])}</code> ·
          Source <code>{html.escape(certification["source_revision"] or "unknown")}</code>
          {" · Warnings: " + html.escape(", ".join(warnings)) if warnings else " · No data warnings"}
        </p>
      </details>
    </section>

    <section aria-labelledby="scoring-explainer">
      <h2 id="scoring-explainer">How the tiers work</h2>
      <div class="scoring-explainer">
        <strong>Immediate Review</strong> surfaces the strongest current signals and is the first place to look.
        <strong>Strong Candidates</strong> are promising opportunities that still deserve a quick upstream check.
        <strong>Worth Watching</strong> have useful signals but may need more context, stability, or timing before acting.
        Scores are deterministic recommendations, not contribution decisions.
      </div>
    </section>

    {section_html("Priority Targets", groups["priority"], duplicate_sources)}
    {section_html("Top Opportunities", groups["top"], duplicate_sources, limit=PUBLIC_TOP_LIMIT)}
    {section_html("Shortlisted", groups["shortlist"], duplicate_sources)}
    {section_html("Watching", groups["watch"], duplicate_sources)}
    {section_html("Completed / Acted On", groups["completed"], duplicate_sources)}
    {section_html("Rejected", groups["rejected"], duplicate_sources)}
  </main>

  <footer>
    WP Core Radar publishes public WordPress Core opportunity and contribution intelligence.
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
    admin_payload = admin_data_payload(context, selection)
    admin_data.write_text(json.dumps(admin_payload, indent=2) + "\n", encoding="utf-8")

    review_state = radar_dir / "review-state.json"
    _, _, summary = opportunity_data(context, selection)
    review_state.write_text(json.dumps(review_state_payload(summary["reviews"]), indent=2) + "\n", encoding="utf-8")

    contributions_dir = radar_dir / "contributions"
    contributions_dir.mkdir(parents=True, exist_ok=True)
    contributions_output = contributions_dir / "index.html"
    contributions_output.write_text(build_contributions_page(context, selection), encoding="utf-8")

    contribution_state_output = radar_dir / "contribution-state.json"
    contribution_state_output.write_text(
        json.dumps(load_contribution_state(), indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {output}")
    print(f"Wrote {admin_data}")
    print(f"Wrote {review_state}")
    print(f"Wrote {contributions_output}")
    print(f"Wrote {contribution_state_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
