#!/usr/bin/env python3
"""Shared utilities for WP Core Radar.

The project intentionally stays deterministic and human-in-the-loop:
Radar collects, normalizes, scores, and reports. Humans decide what to test
or comment on in WordPress Trac.
"""

from __future__ import annotations

import csv
from collections import defaultdict
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from radarcore import DatasetSelection, RunContext, load_scoring_config

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
OUTCOMES_CSV = ROOT / "data" / "outcomes" / "outcomes.csv"
REVIEWS_JSON = ROOT / "data" / "reviews" / "reviews.json"
QUERIES_JSON = ROOT / "config" / "queries.json"
REPORTS_DIR = ROOT / "reports"

TICKET_ID_KEYS = ("id", "ticket", "Ticket", "ticket_id", "Ticket ID")
SUMMARY_KEYS = ("summary", "Summary")
COMPONENT_KEYS = ("component", "Component")
KEYWORDS_KEYS = ("keywords", "Keywords")
STATUS_KEYS = ("status", "Status")
MILESTONE_KEYS = ("milestone", "Milestone")
OWNER_KEYS = ("owner", "Owner")
MODIFIED_KEYS = ("modified", "Modified", "changetime", "Change Time")
CREATED_KEYS = ("created", "Created", "time", "Created Time")
COMMENTS_KEYS = ("comments", "Comments", "comment_count", "Comment Count", "Comment count", "_comments", "_comment_count")


def first_value(row: dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return default


def normalize_ticket_id(value: str) -> str:
    match = re.search(r"\d+", value or "")
    return match.group(0) if match else ""


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    formats = (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def days_since(value: str, now: datetime) -> int | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    return max(0, (now - parsed.astimezone(timezone.utc)).days)


def load_queries(path: Path = QUERIES_JSON) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [q for q in payload.get("queries", []) if q.get("enabled", True)]


def load_outcomes(path: Path = OUTCOMES_CSV) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    if not path.exists():
        return outcomes
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or row[0].strip().startswith("#"):
                continue
            ticket_id = normalize_ticket_id(row[0])
            outcome = row[1].strip().lower() if len(row) > 1 else ""
            if ticket_id and outcome:
                outcomes[ticket_id] = outcome
    return outcomes


def normalize_review(review: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "status": str(review.get("status", "")).strip().lower(),
        "reason": str(review.get("reason", "")).strip(),
        "notes": str(review.get("notes", "")).strip(),
        "updated_at": str(review.get("updated_at", "")).strip(),
    }

    # Props are an outcome independent of review status. Preserve this
    # metadata whenever reviews are loaded and saved so dashboard generation
    # cannot silently erase contribution history.
    if review.get("received_props") is True:
        normalized["received_props"] = True

    props_recorded_at = str(review.get("props_recorded_at", "")).strip()
    if props_recorded_at:
        normalized["props_recorded_at"] = props_recorded_at

    changeset = str(review.get("changeset", "")).strip()
    if changeset:
        normalized["changeset"] = changeset

    return normalized


def load_reviews(path: Path = REVIEWS_JSON) -> dict[str, dict[str, Any]]:
    """Load human review decisions from JSON.

    Reviews are keyed by normalized ticket ID so the admin workflow can update
    exactly one constrained data file. This is intentionally easier for the
    Worker-backed admin endpoint to validate than CSV rows.
    """
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    reviews: dict[str, dict[str, Any]] = {}

    for ticket, review in payload.items():
        ticket_id = normalize_ticket_id(str(ticket))
        if ticket_id and isinstance(review, dict):
            reviews[ticket_id] = normalize_review(review)

    return reviews


def save_reviews(reviews: dict[str, dict[str, Any]], path: Path = REVIEWS_JSON) -> None:
    """Persist human review decisions as stable, sorted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized = {
        ticket_id: normalize_review(review)
        for ticket_id, review in sorted(reviews.items(), key=lambda item: int(item[0]))
        if normalize_ticket_id(ticket_id)
    }

    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def infer_query_slug(csv_path: Path) -> str:
    # Preferred convention: data/raw/<source>/<YYYY-MM-DD>/<query_slug>.csv
    stem = csv_path.stem
    if stem and stem.lower() not in {"query", "tickets", "trac"}:
        return stem

    # Fallback: use the closest non-date parent name.
    for parent in csv_path.parents:
        name = parent.name
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", name) and name not in {"raw", "data", "manual"}:
            return name
    return "unknown"


@dataclass(frozen=True)
class Dataset:
    path: Path
    query_slug: str
    collected_date: str
    row_count: int


def discover_datasets(raw_dir: Path = DATA_RAW) -> list[Dataset]:
    datasets: list[Dataset] = []
    for path in sorted(raw_dir.glob("**/*.csv")):
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                row_count = sum(1 for _ in csv.DictReader(handle))
        except Exception:
            row_count = 0
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", str(path))
        collected_date = date_match.group(0) if date_match else "unknown-date"
        datasets.append(Dataset(path=path, query_slug=infer_query_slug(path), collected_date=collected_date, row_count=row_count))
    return datasets


def read_ticket_rows(dataset: Dataset) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with dataset.path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            ticket_id = normalize_ticket_id(first_value(raw_row, TICKET_ID_KEYS))
            if not ticket_id:
                continue
            row = {k: (v or "").strip() for k, v in raw_row.items()}
            row["ticket_id"] = ticket_id
            row["query_slug"] = dataset.query_slug
            row["collected_date"] = dataset.collected_date
            row["source_file"] = str(dataset.path.relative_to(ROOT))
            rows.append(row)
    return rows


def score_ticket(
    row: dict[str, Any],
    query_meta: dict[str, Any],
    outcomes: dict[str, str],
    reference_time: datetime,
    scoring: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    scoring = scoring or load_scoring_config()
    p = scoring["points"]
    t = scoring["thresholds"]
    priority = int(query_meta.get("priority", scoring["default_query_priority"]))
    score = priority
    track_label = query_meta.get("name", query_meta.get("track", "configured track"))
    reasons: list[str] = [f"track priority: {track_label} +{priority}"]

    ticket_id = row.get("ticket_id", "")
    keywords = first_value(row, KEYWORDS_KEYS).lower()
    component = first_value(row, COMPONENT_KEYS).lower()
    status = first_value(row, STATUS_KEYS).lower()
    milestone = first_value(row, MILESTONE_KEYS).lower()
    owner = first_value(row, OWNER_KEYS).lower()
    summary = first_value(row, SUMMARY_KEYS)
    searchable = " ".join((summary, keywords, component)).lower()

    if "has-patch" in keywords or "has patch" in keywords:
        score += p["has_patch"]
        reasons.append(f"has patch {p['has_patch']:+d}")
    if "needs-testing" in keywords or "needs testing" in keywords:
        score += p["needs_testing"]
        reasons.append(f"needs testing {p['needs_testing']:+d}")
    if "dev-feedback" in keywords or "dev feedback" in keywords:
        score += p["dev_feedback"]
        reasons.append(f"dev feedback {p['dev_feedback']:+d}")
    if "reporter-feedback" in keywords or "reporter feedback" in keywords:
        score += p["reporter_feedback"]
        reasons.append(f"reporter feedback {p['reporter_feedback']:+d}")
    if "good-first-bug" in keywords or "good first bug" in keywords:
        score += p["good_first_bug"]
        reasons.append(f"good first bug {p['good_first_bug']:+d}")
    if component == "media":
        score += p["media_component"]
        reasons.append(f"preferred component: Media {p['media_component']:+d}")
    if "accessibility" in component or "accessibility" in keywords:
        score += p["accessibility_signal"]
        reasons.append(f"accessibility signal {p['accessibility_signal']:+d}")
    if milestone and milestone not in {"awaiting review", "future release"}:
        score += p["concrete_milestone"]
        reasons.append(f"has concrete milestone {p['concrete_milestone']:+d}")
    if owner and owner not in {"", "anonymous", "nobody"}:
        score += p["owner_assigned"]
        reasons.append(f"has owner {p['owner_assigned']:+d}")
    if status in {"closed", "fixed", "wontfix", "duplicate", "invalid"}:
        score += p["closed_status"]
        reasons.append(f"closed/non-actionable {p['closed_status']:+d}")

    modified_age = days_since(first_value(row, MODIFIED_KEYS), reference_time)
    if modified_age is not None:
        if modified_age <= t["fresh_days"]:
            score += p["fresh"]
            reasons.append(f"freshness: recently updated <={t['fresh_days']} days {p['fresh']:+d}")
        elif modified_age <= t["recent_days"]:
            score += p["recent"]
            reasons.append(f"freshness: updated within {t['recent_days']} days {p['recent']:+d}")
        elif modified_age > t["stale_days"]:
            score += p["stale"]
            reasons.append(f"freshness: stale activity >{t['stale_days']} days {p['stale']:+d}")

    created_age = days_since(first_value(row, CREATED_KEYS), reference_time)
    if created_age is not None:
        if t["mature_min_days"] <= created_age <= t["mature_max_days"]:
            score += p["mature"]
            reasons.append(f"ticket age: mature but not ancient {p['mature']:+d}")
        elif created_age > t["very_old_days"]:
            score += p["very_old"]
            reasons.append(f"ticket age: very old ticket {p['very_old']:+d}")

    comments_raw = first_value(row, COMMENTS_KEYS)
    if comments_raw.isdigit():
        comments = int(comments_raw)
        if t["momentum_min_comments"] <= comments <= t["momentum_max_comments"]:
            score += p["healthy_momentum"]
            reasons.append(f"momentum: healthy comment count {p['healthy_momentum']:+d}")
        elif comments > t["large_thread_comments"]:
            score += p["large_thread"]
            reasons.append(f"momentum: very large thread {p['large_thread']:+d}")

    if any(term in searchable for term in ("woocommerce", "woo commerce")):
        score += p["woocommerce"]
        reasons.append(f"setup complexity: requires WooCommerce {p['woocommerce']:+d}")
    if any(
        term in searchable
        for term in (
            "custom post type",
            "custom post types",
            " cpt",
            " cpts",
            "comment type",
            "comment types",
            "type different than 'comment'",
            'type different than "comment"',
            "type different from 'comment'",
            'type different from "comment"',
            "other than 'comment'",
            'other than "comment"',
        )
    ):
        score += p["custom_content_type"]
        reasons.append(f"setup complexity: custom content type setup {p['custom_content_type']:+d}")
    if any(term in searchable for term in ("avif", "imagecreatefrom", "imagemagick", "imagick", " gd ", "image library", "image libraries")):
        score += p["image_library"]
        reasons.append(f"setup complexity: specialized image library {p['image_library']:+d}")
    if any(term in searchable for term in ("opcache", "php.ini", "php ini", "server config", "server configuration", "x-robots", "header", "headers")):
        score += p["server_configuration"]
        reasons.append(f"setup complexity: server/runtime configuration {p['server_configuration']:+d}")
    if "multisite" in searchable or "multi-site" in searchable:
        score += p["multisite"]
        reasons.append(f"setup complexity: multisite environment {p['multisite']:+d}")
    if any(term in searchable for term in ("browser-specific", "safari", "firefox", "chrome", "edge", "webkit")):
        score += p["browser_specific"]
        reasons.append(f"setup complexity: browser-specific behavior {p['browser_specific']:+d}")
    if any(term in searchable for term in ("external api", "third-party api", "oauth", "oembed", "remote request", "external-http", "api endpoint")):
        score += p["external_service"]
        reasons.append(f"setup complexity: external service or API {p['external_service']:+d}")

    if ticket_id in outcomes:
        outcome = outcomes[ticket_id]
        if outcome == "props":
            score += p["already_props"]
            reasons.append(f"already produced props {p['already_props']:+d}")
        elif outcome == "tested":
            score += p["already_tested"]
            reasons.append(f"already tested {p['already_tested']:+d}")

    if not summary:
        score += p["missing_summary"]
        reasons.append(f"missing summary {p['missing_summary']:+d}")

    return score, reasons


def trac_url(ticket_id: str) -> str:
    return f"https://core.trac.wordpress.org/ticket/{ticket_id}"

# Shared review/grouping helpers -------------------------------------------------

PRIORITY_TARGET_LIMIT = 12
PRIORITY_TARGET_MIN_SCORE = 150
COMPLETED_REVIEW_STATUSES = {"tested", "commented", "committed"}
VALID_REVIEW_STATUSES = {
    "new",
    "shortlist",
    "watch",
    "reject",
    "tested",
    "commented",
    "committed",
}


def review_received_props(item: dict[str, Any]) -> bool:
    review = item.get("review") or {}
    # ``status: props`` is retained as legacy read-only compatibility from the
    # early admin prototype. New writes should use ``received_props: true``
    # while preserving the workflow status that led to the contribution.
    return review.get("received_props") is True or str(review.get("status", "")).strip().lower() == "props"


def review_status(item: dict[str, Any]) -> str:
    review = item.get("review") or {}
    return str(review.get("status", "")).strip().lower()


def priority_tier(item: dict[str, Any]) -> tuple[str, str]:
    score = int(item.get("score", 0))

    if score >= 165:
        return "immediate", "Immediate Review"
    if score >= 150:
        return "strong", "Strong Candidate"
    if score >= 130:
        return "watching", "Worth Watching"

    return "standard", "Standard"


def is_priority_target(item: dict[str, Any]) -> bool:
    if review_status(item):
        return False

    if int(item.get("score", 0)) < PRIORITY_TARGET_MIN_SCORE:
        return False

    reasons = " ".join(item.get("reasons", [])).lower()

    has_action_signal = any(
        signal in reasons
        for signal in ("needs testing", "has patch", "good first bug")
    )
    has_manageable_signal = any(
        signal in reasons
        for signal in ("freshness:", "momentum:", "recent activity", "healthy comment count", "has owner")
    )
    has_stale_penalty = any(
        penalty in reasons
        for penalty in (
            "very old ticket",
            "stale activity",
            "very large thread",
            "already produced props",
            "already tested",
        )
    )

    return has_action_signal and has_manageable_signal and not has_stale_penalty


def group_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "priority": [],
        "top": [],
        "shortlist": [],
        "watch": [],
        "completed": [],
        "rejected": [],
    }

    for item in items:
        status = review_status(item)

        if status == "reject":
            groups["rejected"].append(item)
        elif status == "shortlist":
            groups["shortlist"].append(item)
        elif status == "watch":
            groups["watch"].append(item)
        elif status in COMPLETED_REVIEW_STATUSES or review_received_props(item):
            groups["completed"].append(item)
        elif is_priority_target(item) and len(groups["priority"]) < PRIORITY_TARGET_LIMIT:
            groups["priority"].append(item)
        else:
            groups["top"].append(item)

    return groups


@dataclass(frozen=True)
class Opportunity:
    """Canonical normalized and scored opportunity used by every renderer."""

    ticket_id: str
    score: int
    reasons: tuple[str, ...]
    row: dict[str, Any]
    query: dict[str, Any]
    review: dict[str, Any] | None

    def as_item(self) -> dict[str, Any]:
        return {"ticket_id": self.ticket_id, "score": self.score, "reasons": list(self.reasons),
                "row": self.row, "query": self.query, "review": self.review}


def datasets_from_selection(selection: DatasetSelection) -> list[Dataset]:
    return [
        Dataset(path=path, query_slug=slug, collected_date=selection.identity,
                row_count=selection.evidence[slug].row_count)
        for slug, path in sorted(selection.artifacts.items())
        if selection.evidence[slug].valid
    ]


def build_opportunities(
    context: RunContext,
    selection: DatasetSelection | None = None,
    raw_dir: Path = DATA_RAW,
) -> tuple[list[Opportunity], dict[str, set[str]], dict[str, Any]]:
    query_list = load_queries()
    query_meta = {query["slug"]: query for query in query_list}
    outcomes = load_outcomes()
    reviews = load_reviews()
    datasets = datasets_from_selection(selection) if selection else discover_datasets(raw_dir)
    scoring = load_scoring_config()

    scored_by_ticket: dict[str, Opportunity] = {}
    duplicate_sources: dict[str, set[str]] = defaultdict(set)

    for dataset in datasets:
        meta = query_meta.get(
            dataset.query_slug,
            {"priority": scoring["default_query_priority"], "name": dataset.query_slug, "track": dataset.query_slug},
        )

        for row in read_ticket_rows(dataset):
            score, reasons = score_ticket(row, meta, outcomes, context.reference_time, scoring)
            ticket_id = row["ticket_id"]
            duplicate_sources[ticket_id].add(dataset.query_slug)

            candidate = Opportunity(ticket_id, score, tuple(reasons), row, meta, reviews.get(ticket_id))

            if ticket_id not in scored_by_ticket or score > scored_by_ticket[ticket_id].score:
                scored_by_ticket[ticket_id] = candidate

    ranked = sorted(
        scored_by_ticket.values(),
        key=lambda item: (-item.score, int(item.ticket_id)),
    )

    return ranked, duplicate_sources, {
        "datasets": datasets,
        "outcomes": outcomes,
        "reviews": reviews,
    }


def collect_items(
    context: RunContext | None = None,
    selection: DatasetSelection | None = None,
    raw_dir: Path = DATA_RAW,
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, Any]]:
    """Compatibility projection for existing presentation code."""
    opportunities, duplicate_sources, summary = build_opportunities(
        context or RunContext.now(), selection, raw_dir
    )
    return [opportunity.as_item() for opportunity in opportunities], duplicate_sources, summary


# Shared presentation helpers ----------------------------------------------------


def pretty_label(value: str) -> str:
    words = value.replace("_", " ").replace("-", " ").strip().split()
    return " ".join(word.upper() if word.lower() in {"ui", "ux"} else word.capitalize() for word in words)


def clean_reason_label(reason: str) -> str:
    reason = re.sub(r"[+-]\d+", "", reason)
    return pretty_label(reason.strip(" ,"))


def signal_class(label: str) -> str:
    lowered = label.lower()

    if "priority" in lowered:
        return "priority"
    if "patch" in lowered:
        return "patch"
    if "testing" in lowered or "unit test" in lowered:
        return "testing"
    if "first bug" in lowered or "good first" in lowered:
        return "first"
    if "feedback" in lowered:
        return "feedback"
    if "owner" in lowered:
        return "owner"
    if "refresh" in lowered:
        return "refresh"
    if "freshness" in lowered or "recent" in lowered or "stale" in lowered:
        return "freshness"
    if "momentum" in lowered or "comment count" in lowered or "large thread" in lowered:
        return "momentum"
    if "ticket age" in lowered or "very old" in lowered or "mature" in lowered:
        return "age"
    if "component" in lowered:
        return "component"
    if "setup complexity" in lowered:
        return "complexity"

    return "standard"


def signal_labels(keywords: str, reasons: list[str]) -> list[str]:
    labels = [pretty_label(keyword) for keyword in keywords.split()]
    labels.extend(clean_reason_label(reason) for reason in reasons)

    seen: set[str] = set()
    unique: list[str] = []

    for label in labels:
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        unique.append(label)

    return unique


def reason_points(reason: str) -> str:
    match = re.search(r"([+-]\d+)", reason)
    return match.group(1) if match else ""


def reason_without_points(reason: str) -> str:
    points = reason_points(reason)
    return reason.replace(points, "").strip(" ,") if points else reason.strip()


def split_reason(reason: str) -> tuple[str, str]:
    """Return a human category/detail pair for a score reason."""
    label = reason_without_points(reason)

    if ":" in label:
        category, detail = label.split(":", 1)
        return pretty_label(category.strip()), pretty_label(detail.strip())

    return pretty_label(label), ""


def scoring_signal_label(reason: str) -> str:
    """Return a concise pill label that keeps score context visible."""
    category, detail = split_reason(reason)
    points = reason_points(reason)

    if detail:
        label = f"{category}: {detail}"
    else:
        label = category

    return f"{label} {points}".strip()


def ranking_signal_labels(reasons: list[str]) -> list[str]:
    """Return scored signal labels for dashboard/admin pills.

    These labels intentionally expose the actual ranking rationale, not just
    raw Trac keywords, so reviewers can see why a ticket rose or fell without
    reading the full score table.
    """
    labels: list[str] = []

    for reason in reasons:
        lower = reason.lower()
        if any(
            signal in lower
            for signal in (
                "track priority",
                "has patch",
                "needs testing",
                "good first bug",
                "dev feedback",
                "reporter feedback",
                "has owner",
                "freshness:",
                "ticket age:",
                "momentum:",
                "preferred component",
                "accessibility signal",
                "concrete milestone",
                "setup complexity",
            )
        ):
            labels.append(scoring_signal_label(reason))

    return labels or ["Scored Candidate"]


def score_breakdown(reasons: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for reason in reasons:
        points = reason_points(reason)
        category, detail = split_reason(reason)
        polarity = "positive" if points.startswith("+") else "negative" if points.startswith("-") else "neutral"
        rows.append({
            "points": points,
            "label": category,
            "detail": detail,
            "display": f"{category}: {detail}" if detail else category,
            "polarity": polarity,
        })

    return rows

def discovery_track_label(sources: set[str]) -> str:
    return ", ".join(pretty_label(source) for source in sorted(sources))
