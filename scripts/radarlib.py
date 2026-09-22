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


def days_since(value: str, now: datetime | None = None) -> int | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    now = now or datetime.now(timezone.utc)
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


def score_ticket(row: dict[str, Any], query_meta: dict[str, Any], outcomes: dict[str, str]) -> tuple[int, list[str]]:
    priority = int(query_meta.get("priority", 50))
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
        score += 35
        reasons.append("has patch +35")
    if "needs-testing" in keywords or "needs testing" in keywords:
        score += 30
        reasons.append("needs testing +30")
    if "dev-feedback" in keywords or "dev feedback" in keywords:
        score += 18
        reasons.append("dev feedback +18")
    if "reporter-feedback" in keywords or "reporter feedback" in keywords:
        score += 10
        reasons.append("reporter feedback +10")
    if "good-first-bug" in keywords or "good first bug" in keywords:
        score += 20
        reasons.append("good first bug +20")
    if component == "media":
        score += 20
        reasons.append("preferred component: Media +20")
    if "accessibility" in component or "accessibility" in keywords:
        score += 18
        reasons.append("accessibility signal +18")
    if milestone and milestone not in {"awaiting review", "future release"}:
        score += 8
        reasons.append("has concrete milestone +8")
    if owner and owner not in {"", "anonymous", "nobody"}:
        score += 6
        reasons.append("has owner +6")
    if status in {"closed", "fixed", "wontfix", "duplicate", "invalid"}:
        score -= 100
        reasons.append("closed/non-actionable -100")

    modified_age = days_since(first_value(row, MODIFIED_KEYS))
    if modified_age is not None:
        if modified_age <= 14:
            score += 20
            reasons.append("freshness: recently updated <=14 days +20")
        elif modified_age <= 60:
            score += 10
            reasons.append("freshness: updated within 60 days +10")
        elif modified_age > 730:
            score -= 10
            reasons.append("freshness: stale activity >2 years -10")

    created_age = days_since(first_value(row, CREATED_KEYS))
    if created_age is not None:
        if 30 <= created_age <= 730:
            score += 8
            reasons.append("ticket age: mature but not ancient +8")
        elif created_age > 3650:
            score -= 8
            reasons.append("ticket age: very old ticket -8")

    comments_raw = first_value(row, COMMENTS_KEYS)
    if comments_raw.isdigit():
        comments = int(comments_raw)
        if 2 <= comments <= 20:
            score += 7
            reasons.append("momentum: healthy comment count +7")
        elif comments > 80:
            score -= 8
            reasons.append("momentum: very large thread -8")

    if any(term in searchable for term in ("woocommerce", "woo commerce")):
        score -= 18
        reasons.append("setup complexity: requires WooCommerce -18")
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
        score -= 12
        reasons.append("setup complexity: custom content type setup -12")
    if any(term in searchable for term in ("avif", "imagecreatefrom", "imagemagick", "imagick", " gd ", "image library", "image libraries")):
        score -= 18
        reasons.append("setup complexity: specialized image library -18")
    if any(term in searchable for term in ("opcache", "php.ini", "php ini", "server config", "server configuration", "x-robots", "header", "headers")):
        score -= 16
        reasons.append("setup complexity: server/runtime configuration -16")
    if "multisite" in searchable or "multi-site" in searchable:
        score -= 14
        reasons.append("setup complexity: multisite environment -14")
    if any(term in searchable for term in ("browser-specific", "safari", "firefox", "chrome", "edge", "webkit")):
        score -= 12
        reasons.append("setup complexity: browser-specific behavior -12")
    if any(term in searchable for term in ("external api", "third-party api", "oauth", "oembed", "remote request", "external-http", "api endpoint")):
        score -= 16
        reasons.append("setup complexity: external service or API -16")

    if ticket_id in outcomes:
        outcome = outcomes[ticket_id]
        if outcome == "props":
            score -= 60
            reasons.append("already produced props -60")
        elif outcome == "tested":
            score -= 20
            reasons.append("already tested -20")

    if not summary:
        score -= 10
        reasons.append("missing summary -10")

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


def collect_items() -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, Any]]:
    query_list = load_queries()
    query_meta = {query["slug"]: query for query in query_list}
    outcomes = load_outcomes()
    reviews = load_reviews()
    datasets = discover_datasets()

    scored_by_ticket: dict[str, dict[str, Any]] = {}
    duplicate_sources: dict[str, set[str]] = defaultdict(set)

    for dataset in datasets:
        meta = query_meta.get(
            dataset.query_slug,
            {"priority": 50, "name": dataset.query_slug, "track": dataset.query_slug},
        )

        for row in read_ticket_rows(dataset):
            score, reasons = score_ticket(row, meta, outcomes)
            ticket_id = row["ticket_id"]
            duplicate_sources[ticket_id].add(dataset.query_slug)

            candidate = {
                "ticket_id": ticket_id,
                "score": score,
                "reasons": reasons,
                "row": row,
                "query": meta,
                "review": reviews.get(ticket_id),
            }

            if ticket_id not in scored_by_ticket or score > scored_by_ticket[ticket_id]["score"]:
                scored_by_ticket[ticket_id] = candidate

    ranked = sorted(
        scored_by_ticket.values(),
        key=lambda item: (-int(item["score"]), int(item["ticket_id"])),
    )

    return ranked, duplicate_sources, {
        "datasets": datasets,
        "outcomes": outcomes,
        "reviews": reviews,
    }


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
