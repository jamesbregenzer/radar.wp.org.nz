#!/usr/bin/env python3
"""Fetch and normalize approved public WordPress Wave 2 sources."""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "wave2-sources.json"

ALLOWED_FAMILIES = {
    "CORE_PATCH_TEST",
    "GUTENBERG_TEST",
    "ACCESSIBILITY_TEST",
    "BETA_RC_TEST",
    "DOCS_REVIEW",
    "HANDBOOK_UPDATE",
    "PATHWAY_REVIEW",
    "THEME_CHECK_CODE",
    "THEME_CHECK_TRIAGE",
    "THEME_REVIEW",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PublicTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self.links.append(href)


def canonical_url(value: str, base: str | None = None) -> str | None:
    try:
        joined = urljoin(base or value, value)
        parsed = urlparse(joined)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path if parsed.path == "/" else parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def public_text(value: str) -> tuple[str, list[str]]:
    parser = PublicTextParser()
    parser.feed(value or "")
    text = re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()
    links = sorted({item for item in (canonical_url(link) for link in parser.links) if item})
    return text, links


def github_headers() -> dict[str, str]:
    headers = {
        "accept": "application/vnd.github+json",
        "user-agent": "wp-core-radar-public-source-collector",
        "x-github-api-version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def fetch_public(url: str) -> tuple[bytes, dict[str, str], int]:
    headers = github_headers() if urlparse(url).netloc == "api.github.com" else {
        "accept": "application/json",
        "user-agent": "wp-core-radar-public-source-collector",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
        response_headers = {key.lower(): value for key, value in response.headers.items()}
        return body, response_headers, int(response.status)


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema") != "radar-wave2-source-config.v2":
        raise ValueError("unsupported Wave 2 source config")
    families = [item["sourceFamily"] for item in config.get("sources", [])]
    if len(families) != len(set(families)):
        raise ValueError("duplicate Wave 2 source family")
    return config


def source_config(source_family: str, path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    for item in load_config(path).get("sources", []):
        if item["sourceFamily"] == source_family:
            return item
    raise KeyError(source_family)


def with_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def wp_tree_urls(config: dict[str, Any], fetcher: Callable[[str], tuple[bytes, dict[str, str], int]]) -> list[tuple[str, bytes, dict[str, str], int]]:
    endpoint = str(config["endpoint"])
    fields = "id,link,slug,parent,date_gmt,modified_gmt,title,content"
    pending = [int(config["rootId"])]
    seen: set[int] = set()
    responses: list[tuple[str, bytes, dict[str, str], int]] = []
    root_url = f"{endpoint}/{config['rootId']}?_fields={fields}"
    body, headers, status = fetcher(root_url)
    responses.append((root_url, body, headers, status))
    while pending:
        parent = pending.pop(0)
        if parent in seen:
            continue
        seen.add(parent)
        children_url = f"{endpoint}?parent={parent}&per_page=100&orderby=id&order=asc&_fields={fields}"
        body, headers, status = fetcher(children_url)
        responses.append((children_url, body, headers, status))
        values = json.loads(body.decode("utf-8"))
        for item in values:
            child_id = int(item["id"])
            if child_id not in seen:
                pending.append(child_id)
        total_pages = int(headers.get("x-wp-totalpages", "1") or "1")
        for page in range(2, total_pages + 1):
            page_url = with_page(children_url, page)
            page_body, page_headers, page_status = fetcher(page_url)
            responses.append((page_url, page_body, page_headers, page_status))
            page_values = json.loads(page_body.decode("utf-8"))
            for item in page_values:
                child_id = int(item["id"])
                if child_id not in seen:
                    pending.append(child_id)
    return responses


def configured_responses(config: dict[str, Any], fetcher: Callable[[str], tuple[bytes, dict[str, str], int]]) -> list[tuple[str, bytes, dict[str, str], int]]:
    if config["adapter"] == "wp_rest_tree":
        return wp_tree_urls(config, fetcher)
    return [(url, *fetcher(url)) for url in config.get("urls", [])]


def signal(family_id: str, state: str, confidence: str, reason: str, evidence: list[str]) -> dict[str, Any]:
    if family_id not in ALLOWED_FAMILIES:
        raise ValueError(f"unregistered Wave 2 contribution family: {family_id}")
    return {
        "familyId": family_id,
        "state": state,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
    }


def age_days(value: str | None, observed_at: str | None) -> int | None:
    if not value or not observed_at:
        return None
    try:
        updated = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc) if "+" not in value and not value.endswith("Z") else datetime.fromisoformat(value.replace("Z", "+00:00"))
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (observed - updated).days)


def post_signals(
    source_family: str,
    title: str,
    text: str,
    links: list[str],
    slug: str,
    created_at: str | None = None,
    updated_at: str | None = None,
    observed_at: str | None = None,
) -> list[dict[str, Any]]:
    haystack = f"{title} {text}".lower()
    title_lower = title.lower()
    explicit_test = any(phrase in title_lower for phrase in (
        "call for testing", "call for test", "needs testing", "testing call",
    ))
    explicit_review = any(phrase in title_lower for phrase in (
        "call for review", "looking for reviewers", "review a pathway guide", "needs review",
    ))
    results: list[dict[str, Any]] = []
    if source_family == "CONTRIBUTOR_PATHWAYS":
        if "review-a-pathway-guide" in slug:
            results.append(signal(
                "PATHWAY_REVIEW", "CLEAR_OPPORTUNITY", "high",
                "The authoritative pathway explicitly asks contributors to review a pathway guide.",
                [title, slug],
            ))
        return results
    if (age_days(created_at, observed_at) or 0) > 60 or (age_days(updated_at, observed_at) or 0) > 60:
        return results
    if any(term in title_lower for term in ("agenda", "meeting notes", "summary", "thank you", "schedule", "faq", "month in test", "week in test", "year in", "nominations")):
        return results
    if source_family == "MAKE_TEST_RELEASE_SIGNALS" and explicit_test:
        if re.search(r"\b(beta|release candidate|rc\s*[0-9])\b", title_lower):
            results.append(signal(
                "BETA_RC_TEST", "CLEAR_OPPORTUNITY", "high",
                "The Make Test post explicitly requests testing for a beta or release-candidate build.",
                [title],
            ))
        if any("github.com/wordpress/gutenberg" in link.lower() for link in links):
            results.append(signal(
                "GUTENBERG_TEST", "POSSIBLE_OPPORTUNITY", "medium",
                "The Make Test post explicitly requests testing and links to Gutenberg source material.",
                [title],
            ))
        elif any(
            "core.trac.wordpress.org" in link.lower()
            or "github.com/wordpress/wordpress-develop" in link.lower()
            or "make.wordpress.org/core" in link.lower()
            for link in links
        ):
            results.append(signal(
                "CORE_PATCH_TEST", "POSSIBLE_OPPORTUNITY", "medium",
                "The Make Test post explicitly requests testing and links to Core source material.",
                [title],
            ))
    elif source_family == "ACCESSIBILITY_REQUESTS" and (explicit_test or explicit_review or title_lower.startswith("help ") or "request for feedback" in title_lower):
        results.append(signal(
            "ACCESSIBILITY_TEST", "POSSIBLE_OPPORTUNITY", "medium",
            "The Make Accessibility post explicitly requests testing, review, or feedback.",
            [title],
        ))
    elif source_family == "MAKE_THEMES_REQUESTS" and (explicit_test or explicit_review or "theme review" in title_lower):
        results.append(signal(
            "THEME_REVIEW", "POSSIBLE_OPPORTUNITY", "medium",
            "The Make Themes post explicitly requests theme testing or review.",
            [title],
        ))
    return results


def normalize_wp_item(item: dict[str, Any], source_family: str, resource_type: str, observed_at: str | None = None) -> dict[str, Any]:
    title = unescape(str((item.get("title") or {}).get("rendered") or "")).strip()
    html = str((item.get("content") or {}).get("rendered") or "")
    text, links = public_text(html)
    link = str(item.get("link") or "")
    identity = f"{resource_type.lower()}/{item['id']}"
    revision = item.get("modified_gmt") or item.get("date_gmt")
    return {
        "resourceType": resource_type,
        "nativeIdentity": identity,
        "nativeId": item["id"],
        "url": link,
        "title": title,
        "state": "published",
        "createdAt": item.get("date_gmt"),
        "updatedAt": revision,
        "sourceRevision": revision,
        "bodyHash": canonical_hash({"html": html}),
        "bodyExcerpt": text[:500],
        "labels": [str(value) for value in item.get("tags", [])],
        "outboundLinks": links,
        "candidateSignals": post_signals(
            source_family,
            title,
            text,
            links,
            str(item.get("slug") or ""),
            item.get("date_gmt"),
            revision,
            observed_at,
        ),
    }


def github_links(item: dict[str, Any]) -> list[str]:
    text = f"{item.get('title') or ''} {item.get('body') or ''}"
    links = {match.rstrip(".,)") for match in re.findall(r"https?://[^\s<>'\"]+", text)}
    repo_url = str(item.get("repository_url") or "").replace("api.github.com/repos", "github.com")
    for number in re.findall(r"(?<![\w/])#([0-9]{1,7})\b", text):
        if repo_url:
            links.add(f"{repo_url}/issues/{number}")
    return sorted({item for item in (canonical_url(value) for value in links) if item})


def normalize_github_item(item: dict[str, Any], source_family: str, observed_at: str | None = None) -> dict[str, Any]:
    is_pr = bool(item.get("pull_request") or item.get("head"))
    resource_type = "GITHUB_PULL_REQUEST" if is_pr else "GITHUB_ISSUE"
    labels = sorted(str(value.get("name")) for value in item.get("labels", []) if value.get("name"))
    assignees = sorted(str(value.get("login")) for value in item.get("assignees", []) if value.get("login"))
    reviewers = sorted(str(value.get("login")) for value in item.get("requested_reviewers", []) if value.get("login"))
    teams = sorted(str(value.get("slug")) for value in item.get("requested_teams", []) if value.get("slug"))
    node_id = str(item.get("node_id") or f"number-{item['number']}")
    native_identity = f"github-node/{node_id}"
    body = str(item.get("body") or "")
    signals: list[dict[str, Any]] = []
    doc_labels = " ".join(label.lower() for label in labels)
    doc_title = str(item.get("title") or "").lower()
    developer_docs = (
        "[devhub]" in doc_title
        or "developer documentation" in doc_labels
        or "devhub" in doc_labels
        or "misc-dev-note" in doc_labels
        or "documentation team handbook" in doc_labels
    )
    if source_family == "CORE_DEVELOPER_DOCS" and not is_pr and not assignees and developer_docs:
        signals.append(signal(
            "DOCS_REVIEW", "POSSIBLE_OPPORTUNITY", "medium",
            "An open, unassigned issue in the authoritative WordPress documentation tracker requests a specific documentation change.",
            [f"issue #{item['number']}", str(item.get("title") or "")],
        ))
    if source_family == "THEME_CHECK_GITHUB":
        if not is_pr and not assignees and (age_days(item.get("updated_at"), observed_at) or 0) <= 180:
            signals.append(signal(
                "THEME_CHECK_TRIAGE", "POSSIBLE_OPPORTUNITY", "medium",
                "An open, unassigned Theme Check issue has a specific public problem statement.",
                [f"issue #{item['number']}", str(item.get("title") or "")],
            ))
        elif is_pr and not bool(item.get("draft")) and (reviewers or teams or any("review" in label.lower() for label in labels)):
            signals.append(signal(
                "THEME_CHECK_CODE", "POSSIBLE_OPPORTUNITY", "medium",
                "The open Theme Check pull request has an explicit public review request.",
                [f"pull request #{item['number']}", *reviewers, *teams],
            ))
    return {
        "resourceType": resource_type,
        "nativeIdentity": native_identity,
        "nativeId": node_id,
        "number": item["number"],
        "url": item["html_url"],
        "title": str(item.get("title") or ""),
        "state": str(item.get("state") or "unknown"),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
        "sourceRevision": item.get("updated_at") or node_id,
        "bodyHash": canonical_hash({"body": body}),
        "bodyExcerpt": re.sub(r"\s+", " ", body).strip()[:500],
        "labels": labels,
        "assignees": assignees,
        "requestedReviewers": reviewers,
        "requestedTeams": teams,
        "draft": bool(item.get("draft")),
        "outboundLinks": github_links(item),
        "candidateSignals": signals,
    }


def normalize_release_offer(item: dict[str, Any], channel: str) -> dict[str, Any]:
    current = str(item.get("current") or item.get("version") or "unknown")
    locale = str(item.get("locale") or "unknown")
    response = str(item.get("response") or "unknown")
    prerelease = re.search(r"\b(beta|rc)[-_. ]?[0-9]*\b", current, re.IGNORECASE)
    signals = []
    if prerelease:
        signals.append(signal(
            "BETA_RC_TEST", "CLEAR_OPPORTUNITY", "high",
            "The authoritative WordPress version API offers a current beta or release-candidate build.",
            [channel, current, response],
        ))
    download = str(item.get("download") or "")
    return {
        "resourceType": "WORDPRESS_RELEASE_OFFER",
        "nativeIdentity": f"offer/{channel}/{locale}/{current}/{response}",
        "nativeId": f"{channel}:{locale}:{current}:{response}",
        "url": download or "https://wordpress.org/download/beta-nightly/",
        "title": f"WordPress {current} ({channel})",
        "state": response,
        "createdAt": None,
        "updatedAt": None,
        "sourceRevision": canonical_hash(item),
        "bodyHash": canonical_hash(item),
        "bodyExcerpt": "",
        "labels": [channel, response],
        "outboundLinks": [download] if download else [],
        "candidateSignals": signals,
    }


def normalize_resources(config: dict[str, Any], responses: list[tuple[str, bytes, dict[str, str], int]], observed_at: str | None = None) -> list[dict[str, Any]]:
    source_family = config["sourceFamily"]
    adapter = config["adapter"]
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, body, _, _ in responses:
        payload = json.loads(body.decode("utf-8"))
        if adapter in {"wp_rest_posts", "wp_rest_tree"}:
            items = payload if isinstance(payload, list) else [payload]
            resource_type = "WORDPRESS_HANDBOOK_PAGE" if adapter == "wp_rest_tree" else "WORDPRESS_MAKE_POST"
            normalized = [normalize_wp_item(item, source_family, resource_type, observed_at) for item in items]
        elif adapter in {"github_issues", "github_repository"}:
            normalized = [normalize_github_item(item, source_family, observed_at) for item in payload]
        elif adapter == "wordpress_releases":
            channel = parse_qs(urlparse(url).query).get("channel", ["unknown"])[0]
            normalized = [normalize_release_offer(item, channel) for item in payload.get("offers", [])]
        else:
            raise ValueError(f"unsupported Wave 2 adapter: {adapter}")
        for item in normalized:
            identity = item["nativeIdentity"]
            if identity in seen:
                existing = next(value for value in values if value["nativeIdentity"] == identity)
                if len(item.get("requestedReviewers", [])) + len(item.get("requestedTeams", [])) > len(existing.get("requestedReviewers", [])) + len(existing.get("requestedTeams", [])):
                    values[values.index(existing)] = item
                continue
            seen.add(identity)
            values.append(item)
    return sorted(values, key=lambda item: item["nativeIdentity"])
