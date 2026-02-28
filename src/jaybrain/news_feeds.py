"""Multi-source news feed ingestion -- fetch, parse, dedup, store, notify.

Polls DB-configured news sources (RSS, Atom, JSON API), deduplicates
against previously seen articles, stores new ones to the knowledge base
(with embeddings for deep_recall search), and sends Telegram notifications.

Step 1 of the pipeline: articles -> cluster -> synthesize -> blog posts.
"""

from __future__ import annotations

import json as _json
import logging
import re
import uuid
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as ET
from typing import Optional

import requests

from .config import (
    NEWS_FEED_HTTP_TIMEOUT,
    NEWS_FEED_MAX_ITEMS_PER_SOURCE,
    NEWS_FEED_NOTIFY_THRESHOLD,
    SCRAPE_USER_AGENT,
    ensure_data_dirs,
)
from .db import (
    delete_news_feed_source,
    get_connection,
    get_news_feed_source,
    insert_news_feed_source,
    list_news_feed_sources,
    now_iso,
    update_news_feed_source,
)

logger = logging.getLogger(__name__)

# --- Default sources seeded on first use ---
_DEFAULT_SOURCES = [
    {
        "name": "Google News - Claude Code",
        "url": "https://news.google.com/rss/search?q=%22Claude+Code%22&hl=en-US&gl=US&ceid=US:en",
        "source_type": "rss",
        "tags": ["claude_code", "google_news"],
    },
    {
        "name": "Google News - Anthropic",
        "url": "https://news.google.com/rss/search?q=Anthropic&hl=en-US&gl=US&ceid=US:en",
        "source_type": "rss",
        "tags": ["anthropic", "google_news"],
    },
    {
        "name": "HN - Claude Code",
        "url": "https://hn.algolia.com/api/v1/search_by_date?query=%22claude+code%22&tags=story",
        "source_type": "json_api",
        "tags": ["claude_code", "hacker_news"],
    },
    {
        "name": "HN - Anthropic",
        "url": "https://hn.algolia.com/api/v1/search_by_date?query=anthropic&tags=story",
        "source_type": "json_api",
        "tags": ["anthropic", "hacker_news"],
    },
    {
        "name": "Reddit r/ClaudeAI",
        "url": "https://www.reddit.com/r/ClaudeAI/.rss",
        "source_type": "atom",
        "tags": ["claude", "reddit"],
    },
    {
        "name": "Claude Code Releases",
        "url": "https://github.com/anthropics/claude-code/releases.atom",
        "source_type": "atom",
        "tags": ["claude_code", "releases", "github"],
    },
    {
        "name": "Check Point Research",
        "url": "https://research.checkpoint.com/feed/",
        "source_type": "rss",
        "tags": ["security", "threat_intel"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _http_get(url: str, accept: str = "*/*") -> requests.Response:
    """Make an HTTP GET with standard headers and timeout."""
    headers = {
        "User-Agent": SCRAPE_USER_AGENT,
        "Accept": accept,
    }
    resp = requests.get(url, headers=headers, timeout=NEWS_FEED_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Parsers (one per feed format)
# ---------------------------------------------------------------------------
# Each returns list[dict] with normalized keys:
#   source_article_id, title, url, summary, published_at, author,
#   publisher, extra_tags


def _parse_rss(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 XML (Google News, Check Point Research, WordPress)."""
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    articles = []

    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    for item in items[:NEWS_FEED_MAX_ITEMS_PER_SOURCE]:
        guid_el = item.find("guid")
        link_el = item.find("link")
        guid = guid_el.text.strip() if guid_el is not None and guid_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""

        article_id = guid or link
        if not article_id:
            continue

        title_el = item.find("title")
        title = (
            title_el.text.strip()
            if title_el is not None and title_el.text
            else "Untitled"
        )

        # Description (excerpt)
        desc_el = item.find("description")
        desc_html = desc_el.text if desc_el is not None and desc_el.text else ""

        # content:encoded (full HTML, WordPress feeds)
        content_el = item.find("content:encoded", ns)
        full_html = (
            content_el.text if content_el is not None and content_el.text else ""
        )

        summary = _strip_html(full_html[:2000] if full_html else desc_html)

        # Published date (RFC 2822)
        pub_el = item.find("pubDate")
        published_at = None
        if pub_el is not None and pub_el.text:
            try:
                published_at = parsedate_to_datetime(pub_el.text).isoformat()
            except Exception:
                pass

        # Author
        creator_el = item.find("dc:creator", ns)
        author = creator_el.text if creator_el is not None and creator_el.text else ""

        # Publisher (RSS <source> element, used by Google News)
        source_el = item.find("source")
        publisher = source_el.text if source_el is not None and source_el.text else ""

        # Category tags
        extra_tags = []
        for cat_el in item.findall("category"):
            if cat_el.text:
                extra_tags.append(cat_el.text.lower().replace(" ", "_"))

        articles.append(
            {
                "source_article_id": article_id,
                "title": title,
                "url": link,
                "summary": summary[:1000],
                "published_at": published_at,
                "author": author,
                "publisher": publisher,
                "extra_tags": extra_tags[:10],
            }
        )

    return articles


def _parse_atom(xml_text: str) -> list[dict]:
    """Parse Atom XML (Reddit, GitHub Releases)."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", ns)
    articles = []

    for entry in entries[:NEWS_FEED_MAX_ITEMS_PER_SOURCE]:
        id_el = entry.find("atom:id", ns)
        entry_id = (
            id_el.text.strip() if id_el is not None and id_el.text else ""
        )
        if not entry_id:
            continue

        title_el = entry.find("atom:title", ns)
        title = (
            title_el.text.strip()
            if title_el is not None and title_el.text
            else "Untitled"
        )

        # Link -- prefer rel="alternate", fall back to first link
        link = ""
        for link_el in entry.findall("atom:link", ns):
            href = link_el.get("href", "")
            rel = link_el.get("rel", "alternate")
            if rel == "alternate" and href:
                link = href
                break
        if not link:
            first_link = entry.find("atom:link", ns)
            if first_link is not None:
                link = first_link.get("href", "")

        # Content
        content_el = entry.find("atom:content", ns)
        content_html = (
            content_el.text if content_el is not None and content_el.text else ""
        )
        summary_el = entry.find("atom:summary", ns)
        summary_html = (
            summary_el.text if summary_el is not None and summary_el.text else ""
        )
        summary = _strip_html(
            content_html[:2000] if content_html else summary_html
        )

        # Dates
        published_at = None
        for date_tag in ["atom:published", "atom:updated"]:
            date_el = entry.find(date_tag, ns)
            if date_el is not None and date_el.text:
                published_at = date_el.text.strip()
                break

        # Author
        author_el = entry.find("atom:author/atom:name", ns)
        author = author_el.text if author_el is not None and author_el.text else ""

        # Categories
        extra_tags = []
        for cat_el in entry.findall("atom:category", ns):
            term = cat_el.get("term", "")
            if term:
                extra_tags.append(term.lower().replace(" ", "_"))

        articles.append(
            {
                "source_article_id": entry_id,
                "title": title,
                "url": link,
                "summary": summary[:1000],
                "published_at": published_at,
                "author": author,
                "publisher": "",
                "extra_tags": extra_tags[:10],
            }
        )

    return articles


def _parse_json_api(json_data: dict) -> list[dict]:
    """Parse HN Algolia JSON API response."""
    hits = json_data.get("hits", [])
    articles = []

    for hit in hits[:NEWS_FEED_MAX_ITEMS_PER_SOURCE]:
        object_id = hit.get("objectID", "")
        if not object_id:
            continue

        title = hit.get("title", "Untitled") or "Untitled"
        url = hit.get("url", "") or ""

        # Self-post text
        story_text = hit.get("story_text", "") or ""
        summary = _strip_html(story_text[:2000]) if story_text else ""

        points = hit.get("points", 0) or 0
        num_comments = hit.get("num_comments", 0) or 0
        author = hit.get("author", "") or ""
        created_at = hit.get("created_at", "") or ""

        # If no URL, use the HN discussion URL
        hn_url = f"https://news.ycombinator.com/item?id={object_id}"
        if not url:
            url = hn_url

        # Append HN metadata to summary
        meta_parts = []
        if summary:
            meta_parts.append(summary)
        meta_parts.append(f"HN: {points} points, {num_comments} comments")
        meta_parts.append(f"Discussion: {hn_url}")
        summary = "\n".join(meta_parts)

        articles.append(
            {
                "source_article_id": object_id,
                "title": title,
                "url": url,
                "summary": summary[:1000],
                "published_at": created_at if created_at else None,
                "author": author,
                "publisher": "Hacker News",
                "extra_tags": [],
            }
        )

    return articles


# ---------------------------------------------------------------------------
# Fetch dispatcher
# ---------------------------------------------------------------------------


def _fetch_source(source_row) -> list[dict]:
    """Fetch and parse a single source based on its source_type."""
    url = source_row["url"]
    source_type = source_row["source_type"]

    if source_type == "rss":
        resp = _http_get(
            url, accept="application/rss+xml, application/xml, text/xml"
        )
        return _parse_rss(resp.text)

    elif source_type == "atom":
        resp = _http_get(
            url, accept="application/atom+xml, application/xml, text/xml"
        )
        return _parse_atom(resp.text)

    elif source_type == "json_api":
        resp = _http_get(url, accept="application/json")
        return _parse_json_api(resp.json())

    else:
        logger.warning(
            "Unsupported source_type '%s' for source %s",
            source_type,
            source_row["id"],
        )
        return []


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _is_seen(conn, source_id: str, source_article_id: str) -> bool:
    """Check if this article was already processed from this source."""
    row = conn.execute(
        "SELECT 1 FROM news_feed_articles "
        "WHERE source_id = ? AND source_article_id = ?",
        (source_id, source_article_id),
    ).fetchone()
    return row is not None


def _is_url_seen(conn, url: str) -> bool:
    """Cross-source dedup: check if this direct URL was already stored.

    Skips empty URLs and Google News redirect URLs.
    """
    if not url or "news.google.com" in url:
        return False
    row = conn.execute(
        "SELECT 1 FROM news_feed_articles WHERE url = ? LIMIT 1",
        (url,),
    ).fetchone()
    return row is not None


def _mark_seen(
    conn,
    source_id: str,
    source_article_id: str,
    knowledge_id: str,
    title: str,
    url: str,
    published_at: str | None,
) -> None:
    """Record an article as processed."""
    conn.execute(
        """INSERT OR IGNORE INTO news_feed_articles
        (source_id, source_article_id, knowledge_id, title, url,
         published_at, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            source_article_id,
            knowledge_id,
            title,
            url,
            published_at,
            now_iso(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Content builder (for knowledge store)
# ---------------------------------------------------------------------------


def _build_knowledge_content(article: dict, source_name: str) -> str:
    """Build rich content string for the knowledge store entry."""
    parts = []
    if article["summary"]:
        parts.append(article["summary"])
    if article["author"]:
        parts.append(f"Author: {article['author']}")
    if article["publisher"]:
        parts.append(f"Publisher: {article['publisher']}")
    if article["url"]:
        parts.append(f"URL: {article['url']}")
    parts.append(f"Source feed: {source_name}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------


def _parse_source_row(row) -> dict:
    """Convert a DB row to a serializable dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "source_type": row["source_type"],
        "tags": _json.loads(row["tags"]),
        "active": bool(row["active"]),
        "last_polled": row["last_polled"],
        "last_error": row["last_error"],
        "articles_total": row["articles_total"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _ensure_default_sources(conn) -> int:
    """Seed default sources if the table is empty. Returns count seeded."""
    count = conn.execute(
        "SELECT COUNT(*) FROM news_feed_sources"
    ).fetchone()[0]
    if count > 0:
        return 0

    seeded = 0
    for src in _DEFAULT_SOURCES:
        source_id = _generate_id()
        insert_news_feed_source(
            conn,
            source_id,
            src["name"],
            src["url"],
            src["source_type"],
            src["tags"],
        )
        seeded += 1
    return seeded


def add_source(
    name: str,
    url: str,
    source_type: str = "rss",
    tags: Optional[list[str]] = None,
) -> dict:
    """Register a new news feed source."""
    if source_type not in ("rss", "atom", "json_api", "web_scrape"):
        raise ValueError(f"Invalid source_type: {source_type}")
    source_id = _generate_id()
    conn = get_connection()
    try:
        insert_news_feed_source(
            conn, source_id, name, url, source_type, tags or []
        )
        row = get_news_feed_source(conn, source_id)
        return _parse_source_row(row)
    finally:
        conn.close()


def remove_source(source_id: str) -> bool:
    """Remove a news feed source and all its dedup records."""
    conn = get_connection()
    try:
        return delete_news_feed_source(conn, source_id)
    finally:
        conn.close()


def get_sources(active_only: bool = True) -> list[dict]:
    """List all registered news feed sources."""
    conn = get_connection()
    try:
        _ensure_default_sources(conn)
        rows = list_news_feed_sources(conn, active_only=active_only)
        return [_parse_source_row(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Poll functions
# ---------------------------------------------------------------------------


def _poll_single(conn, source_row) -> dict:
    """Poll one source, dedup, store new articles. Returns result dict."""
    from .knowledge import store_knowledge

    source_id = source_row["id"]
    source_name = source_row["name"]

    try:
        articles = _fetch_source(source_row)
    except Exception as e:
        error_msg = str(e)[:500]
        logger.error("Failed to fetch source '%s': %s", source_name, e)
        update_news_feed_source(
            conn, source_id, last_polled=now_iso(), last_error=error_msg
        )
        return {"status": "error", "source": source_name, "error": error_msg}

    new_count = 0
    source_tags = _json.loads(source_row["tags"]) if source_row["tags"] else []

    for article in articles:
        aid = article["source_article_id"]
        if _is_seen(conn, source_id, aid):
            continue
        if _is_url_seen(conn, article["url"]):
            continue

        try:
            content = _build_knowledge_content(article, source_name)
            tags = list(dict.fromkeys(source_tags + article["extra_tags"]))[:15]

            k = store_knowledge(
                title=article["title"],
                content=content,
                category="news_feed",
                tags=tags,
                source=source_name,
            )
            _mark_seen(
                conn,
                source_id,
                aid,
                k.id,
                article["title"],
                article["url"],
                article["published_at"],
            )
            new_count += 1
        except Exception as e:
            logger.warning(
                "Failed to store article '%s': %s",
                article["title"][:50],
                e,
            )

    # Update source metadata
    current_total = source_row["articles_total"] or 0
    update_news_feed_source(
        conn,
        source_id,
        last_polled=now_iso(),
        last_error="",
        articles_total=current_total + new_count,
    )

    return {
        "status": "ok",
        "source": source_name,
        "fetched": len(articles),
        "new": new_count,
    }


def poll_source(source_id: str) -> dict:
    """Poll a single source by ID. Returns status dict."""
    conn = get_connection()
    try:
        row = get_news_feed_source(conn, source_id)
        if not row:
            return {"status": "error", "error": f"Source not found: {source_id}"}
        return _poll_single(conn, row)
    finally:
        conn.close()


def run_news_feed_poll() -> dict:
    """Poll all enabled sources. Daemon entry point.

    Returns dict with status and per-source results.
    """
    ensure_data_dirs()

    conn = get_connection()
    try:
        _ensure_default_sources(conn)
        sources = list_news_feed_sources(conn, active_only=True)
    finally:
        conn.close()

    if not sources:
        return {"status": "skipped", "reason": "no active sources"}

    results = []
    total_new = 0

    for source_row in sources:
        conn = get_connection()
        try:
            result = _poll_single(conn, source_row)
            results.append(result)
            total_new += result.get("new", 0)
        except Exception as e:
            logger.error(
                "Unexpected error polling '%s': %s", source_row["name"], e
            )
            results.append(
                {
                    "status": "error",
                    "source": source_row["name"],
                    "error": str(e)[:200],
                }
            )
        finally:
            conn.close()

    # Telegram notification
    if total_new >= NEWS_FEED_NOTIFY_THRESHOLD:
        try:
            lines = [
                f"News feeds: {total_new} new article"
                f"{'s' if total_new != 1 else ''}"
            ]
            for r in results:
                if r.get("new", 0) > 0:
                    lines.append(f"  - {r['source']}: {r['new']} new")
            from .telegram import send_telegram_message

            send_telegram_message(
                "\n".join(lines), caller="daemon_news_feed"
            )
        except Exception:
            pass  # Notification failure must not break the job

    return {
        "status": "ok",
        "sources_polled": len(results),
        "total_new": total_new,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def get_news_feed_status() -> dict:
    """Get feed status: sources, totals, last poll times, recent articles."""
    conn = get_connection()
    try:
        _ensure_default_sources(conn)
        sources = list_news_feed_sources(conn, active_only=False)

        total_articles = conn.execute(
            "SELECT COUNT(*) FROM news_feed_articles"
        ).fetchone()[0]

        last_poll = conn.execute(
            "SELECT MAX(last_polled) FROM news_feed_sources"
        ).fetchone()[0]

        recent = conn.execute(
            """SELECT nfa.title, nfa.url, nfa.published_at, nfa.fetched_at,
                      nfs.name as source_name
            FROM news_feed_articles nfa
            JOIN news_feed_sources nfs ON nfa.source_id = nfs.id
            ORDER BY nfa.fetched_at DESC LIMIT 10"""
        ).fetchall()

        return {
            "sources": [_parse_source_row(s) for s in sources],
            "total_articles": total_articles,
            "last_poll": last_poll,
            "recent": [
                {
                    "title": r["title"],
                    "url": r["url"],
                    "source": r["source_name"],
                    "published_at": r["published_at"],
                    "fetched_at": r["fetched_at"],
                }
                for r in recent
            ],
        }
    finally:
        conn.close()
