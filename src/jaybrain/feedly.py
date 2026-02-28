"""Feedly AI Feed monitor -- fetch, dedup, store, notify.

Polls a Feedly AI Feed stream, deduplicates against previously seen
articles, stores new ones into the knowledge base (with embeddings for
deep_recall search), and sends Telegram notifications for new arrivals.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from .config import (
    FEEDLY_ACCESS_TOKEN,
    FEEDLY_API_BASE,
    FEEDLY_FETCH_COUNT,
    FEEDLY_NOTIFY_THRESHOLD,
    FEEDLY_STREAM_ID,
    SCRAPE_TIMEOUT,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _feedly_headers() -> dict:
    """Build request headers with Feedly auth token."""
    return {
        "Authorization": f"Bearer {FEEDLY_ACCESS_TOKEN}",
        "Accept": "application/json",
    }


def fetch_stream(
    count: int = FEEDLY_FETCH_COUNT,
    continuation: str | None = None,
) -> dict:
    """Fetch articles from the Feedly AI Feed stream.

    Returns raw Feedly API response with 'items' and optional 'continuation'.
    """
    if not FEEDLY_ACCESS_TOKEN:
        return {"error": "FEEDLY_ACCESS_TOKEN not set"}
    if not FEEDLY_STREAM_ID:
        return {"error": "FEEDLY_STREAM_ID not set"}

    params: dict = {"streamId": FEEDLY_STREAM_ID, "count": count}
    if continuation:
        params["continuation"] = continuation

    resp = requests.get(
        f"{FEEDLY_API_BASE}/streams/contents",
        headers=_feedly_headers(),
        params=params,
        timeout=SCRAPE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_article(item: dict) -> dict:
    """Parse a Feedly stream item into a normalized article dict."""
    title = item.get("title", "Untitled")

    # Summary -- Feedly returns HTML in summary.content
    summary_obj = item.get("summary", {})
    summary_html = summary_obj.get("content", "") if isinstance(summary_obj, dict) else ""
    summary_text = _strip_html(summary_html)

    # Source URL -- try canonicalUrl first, then alternate links
    source_url = item.get("canonicalUrl", "")
    if not source_url:
        alternates = item.get("alternate", [])
        if alternates and isinstance(alternates, list):
            source_url = alternates[0].get("href", "")

    # Published timestamp (unix ms -> ISO)
    published_ms = item.get("published", 0)
    published_at = (
        datetime.fromtimestamp(published_ms / 1000, tz=timezone.utc).isoformat()
        if published_ms
        else None
    )

    # Metadata
    origin = item.get("origin", {})
    source_name = origin.get("title", "") if isinstance(origin, dict) else ""
    author = item.get("author", "")
    keywords = item.get("keywords", [])
    entities = [
        e.get("label", "") for e in item.get("entities", []) if e.get("label")
    ]

    # Build rich content for knowledge store
    content_parts = []
    if summary_text:
        content_parts.append(summary_text)
    if author:
        content_parts.append(f"Author: {author}")
    if source_name:
        content_parts.append(f"Source: {source_name}")
    if source_url:
        content_parts.append(f"URL: {source_url}")
    if keywords:
        content_parts.append(f"Keywords: {', '.join(keywords[:10])}")
    if entities:
        content_parts.append(f"Entities: {', '.join(entities[:10])}")

    content = "\n".join(content_parts)

    # Tags: combine keywords + entities, lowercased, deduped, capped
    tags = list(
        dict.fromkeys(
            [k.lower().replace(" ", "_") for k in (keywords + entities)][:15]
        )
    )

    return {
        "feedly_id": item.get("id", ""),
        "title": title,
        "content": content,
        "summary_text": summary_text,
        "source_url": source_url,
        "source_name": source_name,
        "published_at": published_at,
        "author": author,
        "tags": tags,
    }


def _is_seen(conn, feedly_id: str) -> bool:
    """Check if we've already processed this Feedly article."""
    row = conn.execute(
        "SELECT 1 FROM feedly_articles WHERE feedly_id = ?", (feedly_id,)
    ).fetchone()
    return row is not None


def _mark_seen(
    conn,
    feedly_id: str,
    knowledge_id: str,
    title: str,
    source_url: str,
    published_at: str | None,
) -> None:
    """Record a Feedly article as processed."""
    conn.execute(
        """INSERT OR IGNORE INTO feedly_articles
        (feedly_id, knowledge_id, title, source_url, published_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (feedly_id, knowledge_id, title, source_url, published_at, now_iso()),
    )
    conn.commit()


def run_feedly_monitor() -> dict:
    """Poll Feedly, dedup, store new articles to knowledge base, notify.

    Called by daemon every N minutes or manually via MCP tool.
    Returns dict with status and counts (daemon pattern).
    """
    ensure_data_dirs()

    if not FEEDLY_ACCESS_TOKEN or not FEEDLY_STREAM_ID:
        return {"status": "skipped", "reason": "not configured"}

    try:
        data = fetch_stream()
    except requests.RequestException as e:
        logger.error("Feedly API request failed: %s", e)
        return {"status": "error", "error": str(e)[:500]}

    if "error" in data:
        return {"status": "error", "error": data["error"]}

    items = data.get("items", [])
    if not items:
        return {"status": "ok", "fetched": 0, "new": 0}

    from .knowledge import store_knowledge

    conn = get_connection()
    new_articles: list[dict] = []
    stored = 0

    try:
        for item in items:
            article = _parse_article(item)
            feedly_id = article["feedly_id"]

            if not feedly_id:
                continue
            if _is_seen(conn, feedly_id):
                continue

            try:
                k = store_knowledge(
                    title=article["title"],
                    content=article["content"],
                    category="feedly",
                    tags=article["tags"],
                    source="feedly_ai_feed",
                )
                _mark_seen(
                    conn,
                    feedly_id,
                    k.id,
                    article["title"],
                    article["source_url"],
                    article["published_at"],
                )
                new_articles.append(article)
                stored += 1
            except Exception as e:
                logger.warning(
                    "Failed to store article '%s': %s", article["title"][:50], e
                )
    finally:
        conn.close()

    # Telegram notification for new articles
    if stored >= FEEDLY_NOTIFY_THRESHOLD:
        try:
            lines = [f"Feedly: {stored} new article{'s' if stored != 1 else ''}"]
            for a in new_articles[:5]:
                title_short = a["title"][:60]
                source = a["source_name"] or "Unknown"
                lines.append(f"  - {title_short} ({source})")
            if stored > 5:
                lines.append(f"  ... and {stored - 5} more")
            from .telegram import send_telegram_message

            send_telegram_message("\n".join(lines), caller="daemon_feedly_monitor")
        except Exception:
            pass  # Notification failure must not break the job

    return {
        "status": "ok",
        "fetched": len(items),
        "new": stored,
    }


def get_feedly_status() -> dict:
    """Get feed monitoring status: recent articles, totals, last fetch time."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM feedly_articles").fetchone()[0]

        last_row = conn.execute(
            "SELECT fetched_at FROM feedly_articles ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        last_fetch = last_row["fetched_at"] if last_row else None

        recent = conn.execute(
            """SELECT title, source_url, published_at, fetched_at
            FROM feedly_articles
            ORDER BY fetched_at DESC LIMIT 10"""
        ).fetchall()

        recent_list = [
            {
                "title": r["title"],
                "source_url": r["source_url"],
                "published_at": r["published_at"],
                "fetched_at": r["fetched_at"],
            }
            for r in recent
        ]

        return {
            "configured": bool(FEEDLY_ACCESS_TOKEN and FEEDLY_STREAM_ID),
            "total_articles": total,
            "last_fetch": last_fetch,
            "recent": recent_list,
        }
    finally:
        conn.close()
