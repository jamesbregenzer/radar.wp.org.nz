#!/usr/bin/env python3
"""Read-only UI/report projection of the verified WP-3 certified model."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from certification import CERTIFIED_CURRENT, verify_certified
from radarlib import Dataset, REVIEWS_JSON, load_queries, load_reviews


def load_certified_projection(
    current_dir: Path = CERTIFIED_CURRENT,
    reviews_path: Path = REVIEWS_JSON,
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, Any]]:
    """Return legacy renderer-shaped items sourced only from a verified bundle.

    Certified ranking/ticket/provenance fields remain immutable. Current review
    state is attached as a separate durable overlay for human UI grouping.
    """
    verify_certified(current_dir)
    snapshot = json.loads((current_dir / "snapshot.json").read_text(encoding="utf-8"))
    collection = json.loads((current_dir / "collection.json").read_text(encoding="utf-8"))
    opportunity_set = json.loads((current_dir / "opportunities.json").read_text(encoding="utf-8"))
    reviews = load_reviews(reviews_path)
    queries = {query["slug"]: query for query in load_queries()}
    ranked: list[dict[str, Any]] = []
    duplicate_sources: dict[str, set[str]] = defaultdict(set)

    for record in opportunity_set["opportunities"]:
        ticket = record["ticket"]
        ranking = record["ranking"]
        ticket_id = ticket["id"]
        source_slugs = {source["query_slug"] for source in record["discovery"]["sources"]}
        duplicate_sources[ticket_id].update(source_slugs)
        primary_slug = sorted(source_slugs)[0]
        primary_query = queries.get(primary_slug, {
            "slug": primary_slug,
            "name": primary_slug,
            "track": record["discovery"]["tracks"][0] if record["discovery"]["tracks"] else primary_slug,
        })
        row = {
            "ticket_id": ticket_id,
            "summary": ticket["summary"],
            "component": ticket["component"] or "",
            "status": ticket["status"] or "",
            "resolution": ticket["resolution"] or "",
            "owner": ticket["owner"] or "",
            "reporter": ticket["reporter"] or "",
            "type": ticket["type"] or "",
            "priority": ticket["priority"] or "",
            "milestone": ticket["milestone"] or "",
            "version": ticket["wordpress_version"] or "",
            "keywords": " ".join(ticket["keywords"]),
            "created": ticket["created"] or "",
            "modified": ticket["modified"] or "",
            "comments": "" if ticket["comment_count"] is None else str(ticket["comment_count"]),
        }
        ranked.append({
            "ticket_id": ticket_id,
            "score": ranking["score"],
            "reasons": list(ranking["reasons"]),
            "row": row,
            "query": primary_query,
            "review": reviews.get(ticket_id) or dict(record.get("radar_state") or {}),
            "certified_record": record,
        })

    datasets = [
        Dataset(
            path=Path(item["artifact_path"]),
            query_slug=item["query_slug"],
            collected_date=collection["reference_time"][:10],
            row_count=item["row_count"],
        )
        for item in collection["query_evidence"]
    ]
    return ranked, duplicate_sources, {
        "datasets": datasets,
        "reviews": reviews,
        "certification": {
            "snapshot_id": snapshot["snapshot_id"],
            "collection_id": snapshot["collection_id"],
            "reference_time": snapshot["reference_time"],
            "state": snapshot["certification"]["state"],
            "opportunity_count": snapshot["opportunity_count"],
            "scoring_version": snapshot["scoring_version"],
            "source_revision": snapshot.get("source_revision"),
            "warnings": list(snapshot["certification"].get("warnings", [])),
            "dataset_sha256": snapshot["dataset_sha256"],
        },
    }
