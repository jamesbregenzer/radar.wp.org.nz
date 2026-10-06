#!/usr/bin/env python3
"""Immutable public source receipts for Core Trac CSV acquisitions."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
QUERIES_JSON = ROOT / "config" / "queries.json"

QUERY_COLUMNS = (
    "id",
    "summary",
    "status",
    "component",
    "owner",
    "type",
    "priority",
    "milestone",
    "version",
    "keywords",
    "time",
    "changetime",
    "comments",
    "_comments",
)

PARSER_VERSION = "core-trac-csv-parser.v1"
RECEIPT_SCHEMA = "trac-csv-source-receipt.v1"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def load_queries() -> list[dict[str, Any]]:
    if not QUERIES_JSON.exists():
        return []
    payload = json.loads(QUERIES_JSON.read_text(encoding="utf-8"))
    return [query for query in payload.get("queries", []) if query.get("enabled", True)]


def query_url(query: dict[str, Any]) -> str:
    if query.get("url"):
        return str(query["url"])

    track = query.get("track")
    if not track:
        raise ValueError(f"Query {query.get('slug', '<unknown>')} is missing both url and track.")

    params = urlencode(
        {
            "status": "!closed",
            "keywords": f"~{track}",
            "format": "csv",
            "col": list(QUERY_COLUMNS),
        },
        doseq=True,
    )
    return f"https://core.trac.wordpress.org/query?{params}"


def configured_query(query_slug: str) -> dict[str, Any]:
    queries = {query["slug"]: query for query in load_queries()}
    query = queries.get(query_slug)
    if not query:
        raise ValueError(f"Unknown or disabled query slug: {query_slug}")
    return query


def receipt_path_for(csv_path: Path) -> Path:
    return csv_path.with_suffix(".source-receipt.json")


def build_trac_receipt(
    *,
    query_slug: str,
    collection_id: str,
    source_url: str,
    csv_path: Path,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    raw_bytes = csv_path.read_bytes()
    observed = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        raw_artifact = csv_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        raw_artifact = f"data/raw/manual/{collection_id}/{csv_path.name}"
    preimage = {
        "schema": RECEIPT_SCHEMA,
        "querySlug": query_slug,
        "collectionId": collection_id,
        "sourceUrl": source_url,
        "retrievedAt": observed,
        "rawSha256": sha256_bytes(raw_bytes),
        "byteLength": len(raw_bytes),
        "parserVersion": PARSER_VERSION,
    }
    acquisition_id = f"trac-csv-acquisition-v1-{canonical_hash(preimage)[:24]}"
    return {
        "schema": RECEIPT_SCHEMA,
        "version": 1,
        "acquisitionId": acquisition_id,
        "sourceFamily": "CORE_TRAC",
        "sourceType": "trac-query-csv",
        "querySlug": query_slug,
        "collectionId": collection_id,
        "sourceUrl": source_url,
        "retrievedAt": observed,
        "rawArtifact": raw_artifact,
        "rawSha256": preimage["rawSha256"],
        "byteLength": preimage["byteLength"],
        "parserVersion": PARSER_VERSION,
        "parsingMetadata": {
            "format": "csv",
            "encoding": "utf-8-sig",
            "ticketIdColumns": ["id", "ticket", "Ticket", "ticket_id", "Ticket ID"],
        },
        "canonicalHash": canonical_hash(preimage),
    }


def write_trac_receipt(
    *,
    query_slug: str,
    collection_id: str,
    source_url: str,
    csv_path: Path,
    retrieved_at: str | None = None,
) -> Path:
    receipt = build_trac_receipt(
        query_slug=query_slug,
        collection_id=collection_id,
        source_url=source_url,
        csv_path=csv_path,
        retrieved_at=retrieved_at,
    )
    path = receipt_path_for(csv_path)
    body = canonical_json(receipt)
    if path.exists() and path.read_bytes() != body:
        raise FileExistsError(f"Immutable source receipt already exists with different content: {path}")
    path.write_bytes(body)
    return path


def load_trac_receipt(csv_path: Path) -> dict[str, Any] | None:
    path = receipt_path_for(csv_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
