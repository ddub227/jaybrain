"""SignalForge — Article intelligence engine: fetching, clustering, synthesis, and lifecycle.

Tier 1 of the three-tier article lifecycle:
  - Tier 1 (30-day TTL): Full article text as .txt files in data/articles/
  - Tier 2 (permanent): Summary + metadata + embedding in knowledge table
  - Tier 3 (permanent): Distilled insights from synthesis
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests

from .config import (
    ANTHROPIC_API_KEY,
    SCRAPE_USER_AGENT,
    SIGNALFORGE_ARTICLE_TTL_DAYS,
    SIGNALFORGE_ARTICLES_DIR,
    SIGNALFORGE_BACKOFF_MAX,
    SIGNALFORGE_CLUSTER_MAX_SIZE,
    SIGNALFORGE_CLUSTER_SIMILARITY,
    SIGNALFORGE_CLUSTER_WINDOW_DAYS,
    SIGNALFORGE_FETCH_BATCH_SIZE,
    SIGNALFORGE_FETCH_DELAY_BASE,
    SIGNALFORGE_FETCH_DELAY_JITTER,
    SIGNALFORGE_MAX_ARTICLE_CHARS,
    SIGNALFORGE_SYNTHESIS_EXCERPT_CHARS,
    SIGNALFORGE_SYNTHESIS_MAX_CLUSTERS,
    SIGNALFORGE_SYNTHESIS_MAX_TOKENS_COMBINE,
    SIGNALFORGE_SYNTHESIS_MAX_TOKENS_PER_CLUSTER,
    SIGNALFORGE_SYNTHESIS_MIN_SIGNIFICANCE,
    SIGNALFORGE_SYNTHESIS_MODEL,
)
from .db import (
    _deserialize_f32,
    count_signalforge_by_status,
    get_cluster_articles,
    get_connection,
    get_signalforge_article_by_knowledge_id,
    get_signalforge_cluster,
    get_signalforge_synthesis_by_date,
    init_db,
    insert_cluster_article,
    insert_signalforge_article,
    insert_signalforge_cluster,
    insert_signalforge_synthesis,
    list_signalforge_clusters,
    list_signalforge_expired,
    list_signalforge_pending,
    list_signalforge_syntheses,
    now_iso,
    update_signalforge_article,
    update_signalforge_synthesis,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Google News URL resolution
# ---------------------------------------------------------------------------


def _resolve_google_news_url(url: str) -> str:
    """Resolve a Google News redirect URL to the actual article URL.

    Google News wraps all article links in redirect URLs like:
        https://news.google.com/rss/articles/...

    Uses googlenewsdecoder to decode the protobuf-encoded redirect.
    Non-Google-News URLs are passed through unchanged.
    """
    if not url or "news.google.com" not in url:
        return url

    try:
        from googlenewsdecoder import new_decoderv1

        result = new_decoderv1(url, interval=5)
        if result.get("status"):
            decoded = result.get("decoded_url", url)
            logger.debug("Resolved Google News URL: %s -> %s", url[:80], decoded[:80])
            return decoded
        logger.warning("Google News decode returned non-success: %s", result)
        return url
    except Exception as exc:
        logger.warning("Failed to decode Google News URL: %s — %s", url[:80], exc)
        return url


# ---------------------------------------------------------------------------
# Article text extraction
# ---------------------------------------------------------------------------


def _extract_article_text(html: str, url: str) -> str:
    """Extract main article text from HTML.

    Primary: trafilatura (F1: 0.958, best-in-class)
    Fallback: scraping.extract_clean_text (BS4-based)
    Truncates to SIGNALFORGE_MAX_ARTICLE_CHARS.
    """
    text = ""

    # Primary: trafilatura
    try:
        import trafilatura

        result = trafilatura.extract(html, url=url, include_comments=False)
        if result:
            text = result
    except Exception as exc:
        logger.debug("Trafilatura extraction failed for %s: %s", url[:80], exc)

    # Fallback: BS4-based extraction
    if not text:
        try:
            from .scraping import extract_clean_text

            text = extract_clean_text(html)
        except Exception as exc:
            logger.debug("BS4 fallback extraction failed for %s: %s", url[:80], exc)

    # Truncate
    if len(text) > SIGNALFORGE_MAX_ARTICLE_CHARS:
        text = text[:SIGNALFORGE_MAX_ARTICLE_CHARS]

    return text.strip()


# ---------------------------------------------------------------------------
# File naming and formatting
# ---------------------------------------------------------------------------


def _slugify_title(title: str, max_len: int = 80) -> str:
    """Convert an article title to a filesystem-safe slug.

    'Claude Code flaws left AI tool wide open to hackers'
    -> 'claude-code-flaws-left-ai-tool-wide-open-to-hackers'
    """
    slug = title.lower()
    slug = re.sub(r"[''`]", "", slug)          # remove apostrophes
    slug = re.sub(r"[^a-z0-9]+", "-", slug)    # non-alphanumeric -> hyphen
    slug = slug.strip("-")                      # trim leading/trailing hyphens
    # Truncate at word boundary
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "untitled"


def _format_article_text(text: str, title: str = "", url: str = "",
                         source: str = "") -> str:
    """Format extracted article text for human readability in Notepad.

    Adds a metadata header and ensures paragraph breaks use blank lines.
    """
    lines = []

    # Metadata header
    if title:
        lines.append(title)
        lines.append("=" * min(len(title), 80))
        lines.append("")
    if url:
        lines.append(f"Source: {url}")
    if source:
        lines.append(f"Feed: {source}")
    if url or source:
        fetched = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"Fetched: {fetched}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("")

    # Format body: ensure paragraph breaks are double-newline separated.
    # Trafilatura already uses \n between paragraphs, but single newlines
    # look like one continuous blob in Notepad. Convert to double newlines.
    paragraphs = re.split(r"\n{2,}", text)
    if len(paragraphs) <= 1:
        # Single block — split on single newlines as paragraph boundaries
        paragraphs = text.split("\n")

    # Filter empties and rejoin with double newlines
    body = "\n\n".join(p.strip() for p in paragraphs if p.strip())
    lines.append(body)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File storage (Tier 1)
# ---------------------------------------------------------------------------


def _article_path(title: str, knowledge_id: str,
                  date: Optional[datetime] = None) -> Path:
    """Build the file path for an article's full text.

    Format: data/articles/YYYY-MM-DD/{slugified-title}.txt
    Falls back to knowledge_id if title is empty.
    """
    if date is None:
        date = datetime.now(timezone.utc)
    date_str = date.strftime("%Y-%m-%d")
    if title:
        filename = _slugify_title(title)
    else:
        filename = knowledge_id
    return SIGNALFORGE_ARTICLES_DIR / date_str / f"{filename}.txt"


def _save_article_text(title: str, knowledge_id: str, text: str) -> Path:
    """Write article text to disk and return the file path."""
    path = _article_path(title, knowledge_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_article_text(knowledge_id: str) -> Optional[str]:
    """Read full article text from Tier 1 file store.

    Returns None if the file doesn't exist or the article has expired.
    """
    conn = get_connection()
    try:
        row = get_signalforge_article_by_knowledge_id(conn, knowledge_id)
        if not row:
            return None
        if row["fetch_status"] != "fetched":
            return None

        content_path = row["content_path"]
        if not content_path:
            return None

        path = Path(content_path)
        if not path.exists():
            return None

        return path.read_text(encoding="utf-8")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Skip logic
# ---------------------------------------------------------------------------


def _should_skip_url(url: str) -> bool:
    """Determine if a URL should be skipped for full-text fetching."""
    if not url:
        return True

    # HN discussion pages have no article text worth extracting
    if "news.ycombinator.com/item" in url:
        return True

    return False


# ---------------------------------------------------------------------------
# Fetch logic
# ---------------------------------------------------------------------------


def _fetch_single_article(knowledge_id: str, url: str, title: str = "",
                          source_name: str = "") -> dict:
    """Fetch and extract full text for a single article.

    Returns a dict with: status, word_count, char_count, content_path, error
    """
    result = {
        "knowledge_id": knowledge_id,
        "status": "failed",
        "word_count": 0,
        "char_count": 0,
        "content_path": "",
        "resolved_url": url,
        "error": "",
    }

    # Skip logic
    if _should_skip_url(url):
        result["status"] = "skipped"
        result["error"] = "URL skipped by policy"
        return result

    # Resolve Google News redirects
    resolved_url = _resolve_google_news_url(url)
    result["resolved_url"] = resolved_url

    # HTTP GET
    try:
        resp = requests.get(
            resolved_url,
            timeout=20,
            headers={"User-Agent": SCRAPE_USER_AGENT},
            allow_redirects=True,
        )

        if resp.status_code == 429:
            result["error"] = "Rate limited (429)"
            return result

        if resp.status_code == 403:
            result["status"] = "failed"
            result["error"] = "Forbidden (403)"
            return result

        if resp.status_code >= 400:
            result["status"] = "failed"
            result["error"] = f"HTTP {resp.status_code}"
            return result

        html = resp.text
    except requests.RequestException as exc:
        result["error"] = str(exc)[:200]
        return result

    # Extract article text
    raw_text = _extract_article_text(html, resolved_url)
    if not raw_text:
        result["status"] = "failed"
        result["error"] = "No text extracted"
        return result

    # Format for human readability
    formatted = _format_article_text(
        raw_text, title=title, url=resolved_url, source=source_name,
    )

    # Save to disk
    path = _save_article_text(title, knowledge_id, formatted)
    result["status"] = "fetched"
    result["content_path"] = str(path)
    result["word_count"] = len(raw_text.split())
    result["char_count"] = len(raw_text)

    return result


def _enqueue_new_articles() -> int:
    """Find news_feed_articles not yet in signalforge_articles and create pending rows.

    Returns the number of new rows created.
    """
    conn = get_connection()
    try:
        # LEFT JOIN to find articles that don't have a signalforge row yet
        rows = conn.execute(
            """SELECT nfa.knowledge_id, nfa.url
            FROM news_feed_articles nfa
            LEFT JOIN signalforge_articles sa ON sa.knowledge_id = nfa.knowledge_id
            WHERE sa.id IS NULL AND nfa.url != ''"""
        ).fetchall()

        count = 0
        for row in rows:
            knowledge_id = row["knowledge_id"]
            try:
                article_id = uuid.uuid4().hex[:12]
                insert_signalforge_article(conn, article_id, knowledge_id)
                count += 1
            except Exception as exc:
                logger.debug("Failed to enqueue %s: %s", knowledge_id, exc)

        return count
    finally:
        conn.close()


def run_signalforge_fetch() -> dict:
    """Daemon entry point: enqueue new articles and batch-fetch pending ones.

    Implements polite rate limiting with jitter and exponential backoff on 429s.
    """
    init_db()

    # Phase 1: Enqueue new articles from news_feed_articles
    enqueued = _enqueue_new_articles()
    logger.info("SignalForge: enqueued %d new articles for fetching", enqueued)

    # Phase 2: Fetch pending articles
    conn = get_connection()
    try:
        pending = list_signalforge_pending(conn, limit=SIGNALFORGE_FETCH_BATCH_SIZE)
    finally:
        conn.close()

    if not pending:
        logger.info("SignalForge: no pending articles to fetch")
        return {"enqueued": enqueued, "fetched": 0, "failed": 0, "skipped": 0}

    fetched = 0
    failed = 0
    skipped = 0
    backoff = SIGNALFORGE_FETCH_DELAY_BASE

    for row in pending:
        article_id = row["id"]
        knowledge_id = row["knowledge_id"]

        # Look up URL, title, and source name from news_feed_articles
        conn = get_connection()
        try:
            nfa_row = conn.execute(
                """SELECT nfa.url, nfa.title, nfs.name as source_name
                FROM news_feed_articles nfa
                LEFT JOIN news_feed_sources nfs ON nfs.id = nfa.source_id
                WHERE nfa.knowledge_id = ?""",
                (knowledge_id,),
            ).fetchone()
        finally:
            conn.close()

        if not nfa_row:
            # No URL found, skip
            conn = get_connection()
            try:
                update_signalforge_article(
                    conn, article_id,
                    fetch_status="skipped",
                    fetch_error="No URL in news_feed_articles",
                    fetched_at=now_iso(),
                )
            finally:
                conn.close()
            skipped += 1
            continue

        url = nfa_row["url"]
        title = nfa_row["title"] or ""
        source_name = nfa_row["source_name"] or ""

        # Fetch
        result = _fetch_single_article(
            knowledge_id, url, title=title, source_name=source_name,
        )

        # Update DB
        now = now_iso()
        conn = get_connection()
        try:
            if result["status"] == "fetched":
                expires = (
                    datetime.now(timezone.utc)
                    + timedelta(days=SIGNALFORGE_ARTICLE_TTL_DAYS)
                ).isoformat()
                update_signalforge_article(
                    conn, article_id,
                    fetch_status="fetched",
                    resolved_url=result["resolved_url"],
                    content_path=result["content_path"],
                    word_count=result["word_count"],
                    char_count=result["char_count"],
                    fetched_at=now,
                    expires_at=expires,
                )
                fetched += 1
                backoff = SIGNALFORGE_FETCH_DELAY_BASE  # reset backoff
            elif result["status"] == "skipped":
                update_signalforge_article(
                    conn, article_id,
                    fetch_status="skipped",
                    fetch_error=result["error"],
                    resolved_url=result["resolved_url"],
                    fetched_at=now,
                )
                skipped += 1
            else:
                update_signalforge_article(
                    conn, article_id,
                    fetch_status="failed",
                    fetch_error=result["error"],
                    resolved_url=result["resolved_url"],
                    fetched_at=now,
                )
                failed += 1

                # Exponential backoff on rate limiting
                if "429" in result.get("error", ""):
                    backoff = min(backoff * 2, SIGNALFORGE_BACKOFF_MAX)
                    logger.warning(
                        "SignalForge: 429 rate limit, backing off to %.1fs", backoff
                    )
        finally:
            conn.close()

        # Rate limiting delay
        delay = backoff + random.uniform(0, SIGNALFORGE_FETCH_DELAY_JITTER)
        time.sleep(delay)

    summary = {
        "enqueued": enqueued,
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info("SignalForge fetch complete: %s", summary)
    return summary


def fetch_single(knowledge_id: str) -> dict:
    """MCP entry point: fetch full text for a single article by knowledge_id.

    If already fetched, returns the existing data without re-fetching.
    """
    init_db()
    conn = get_connection()
    try:
        # Check if already exists
        existing = get_signalforge_article_by_knowledge_id(conn, knowledge_id)
        if existing and existing["fetch_status"] == "fetched":
            return {
                "status": "already_fetched",
                "knowledge_id": knowledge_id,
                "word_count": existing["word_count"],
                "content_path": existing["content_path"],
            }

        # Look up URL, title, and source name
        nfa_row = conn.execute(
            """SELECT nfa.url, nfa.title, nfs.name as source_name
            FROM news_feed_articles nfa
            LEFT JOIN news_feed_sources nfs ON nfs.id = nfa.source_id
            WHERE nfa.knowledge_id = ?""",
            (knowledge_id,),
        ).fetchone()

        if not nfa_row:
            return {"status": "error", "error": "No URL found for knowledge_id"}

        url = nfa_row["url"]
        title = nfa_row["title"] or ""
        source_name = nfa_row["source_name"] or ""

        # Create signalforge row if not exists
        if not existing:
            article_id = uuid.uuid4().hex[:12]
            insert_signalforge_article(conn, article_id, knowledge_id)
        else:
            article_id = existing["id"]
    finally:
        conn.close()

    # Fetch
    result = _fetch_single_article(
        knowledge_id, url, title=title, source_name=source_name,
    )

    # Update DB
    now = now_iso()
    conn = get_connection()
    try:
        if result["status"] == "fetched":
            expires = (
                datetime.now(timezone.utc)
                + timedelta(days=SIGNALFORGE_ARTICLE_TTL_DAYS)
            ).isoformat()
            update_signalforge_article(
                conn, article_id,
                fetch_status="fetched",
                resolved_url=result["resolved_url"],
                content_path=result["content_path"],
                word_count=result["word_count"],
                char_count=result["char_count"],
                fetched_at=now,
                expires_at=expires,
            )
        else:
            update_signalforge_article(
                conn, article_id,
                fetch_status=result["status"],
                fetch_error=result["error"],
                resolved_url=result["resolved_url"],
                fetched_at=now,
            )
    finally:
        conn.close()

    return result


# ---------------------------------------------------------------------------
# Cleanup (Tier 1 expiry)
# ---------------------------------------------------------------------------


def run_signalforge_cleanup() -> dict:
    """Daemon entry point: delete expired article files and update status.

    Runs daily at the configured hour (default 4 AM).
    """
    init_db()
    conn = get_connection()
    try:
        expired = list_signalforge_expired(conn)
    finally:
        conn.close()

    deleted_files = 0
    cleaned_dirs = 0

    for row in expired:
        content_path = row["content_path"]
        article_id = row["id"]

        # Delete the .txt file
        if content_path:
            path = Path(content_path)
            if path.exists():
                try:
                    path.unlink()
                    deleted_files += 1

                    # Remove empty date directory
                    parent = path.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                        cleaned_dirs += 1
                except OSError as exc:
                    logger.warning(
                        "Failed to delete expired article file %s: %s",
                        content_path, exc,
                    )

        # Update status to expired
        conn = get_connection()
        try:
            update_signalforge_article(
                conn, article_id,
                fetch_status="expired",
                content_path="",
            )
        finally:
            conn.close()

    summary = {
        "expired_count": len(expired),
        "deleted_files": deleted_files,
        "cleaned_dirs": cleaned_dirs,
    }
    logger.info("SignalForge cleanup complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Story Clustering
# ---------------------------------------------------------------------------


def _get_clusterable_articles(
    conn, window_days: int = SIGNALFORGE_CLUSTER_WINDOW_DAYS,
) -> list[tuple[str, list[float]]]:
    """Get fetched articles with embeddings from the last N days.

    Returns list of (knowledge_id, embedding_vector) tuples.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).isoformat()
    rows = conn.execute(
        """SELECT sa.knowledge_id, kv.embedding
        FROM signalforge_articles sa
        JOIN knowledge_vec kv ON kv.id = sa.knowledge_id
        WHERE sa.fetch_status = 'fetched'
          AND sa.created_at >= ?""",
        (cutoff,),
    ).fetchall()

    items = []
    for row in rows:
        try:
            vec = _deserialize_f32(row["embedding"])
            items.append((row["knowledge_id"], vec))
        except Exception:
            continue
    return items


def _build_clusters(
    items: list[tuple[str, list[float]]],
    threshold: float = SIGNALFORGE_CLUSTER_SIMILARITY,
    max_size: int = SIGNALFORGE_CLUSTER_MAX_SIZE,
) -> list[dict]:
    """Build story clusters using cosine similarity + BFS connected components.

    Adapted from consolidation.py's proven clustering algorithm.

    Returns list of dicts with: knowledge_ids, avg_similarity
    """
    if len(items) < 2:
        return []

    ids = [item[0] for item in items]
    vectors = [item[1] for item in items]

    # Pairwise cosine similarity via numpy
    matrix = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-9)
    normalized = matrix / norms
    sim_matrix = normalized @ normalized.T

    # Build adjacency list from pairs above threshold
    n = len(ids)
    adjacency: dict[int, set[int]] = defaultdict(set)
    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i, j] >= threshold:
                adjacency[i].add(j)
                adjacency[j].add(i)

    # BFS connected components
    visited: set[int] = set()
    components: list[list[int]] = []
    for start in range(n):
        if start in visited or start not in adjacency:
            continue
        component: list[int] = []
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for neighbor in adjacency[node]:
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(component) >= 2:
            components.append(component[:max_size])

    # Build output with avg similarity per cluster
    clusters = []
    for comp in components:
        cluster_ids = [ids[idx] for idx in comp]
        # Average pairwise similarity within cluster
        sims = []
        for i_idx in range(len(comp)):
            for j_idx in range(i_idx + 1, len(comp)):
                sims.append(float(sim_matrix[comp[i_idx], comp[j_idx]]))
        avg_sim = sum(sims) / len(sims) if sims else 0.0

        clusters.append({
            "knowledge_ids": cluster_ids,
            "avg_similarity": round(avg_sim, 4),
        })

    return clusters


def _compute_significance(
    article_count: int, avg_similarity: float, source_count: int
) -> float:
    """Compute story significance score.

    More articles from more sources with higher similarity = more significant.
    """
    return round(article_count * avg_similarity * source_count, 4)


def _generate_cluster_label(conn, knowledge_ids: list[str]) -> str:
    """Pick a representative label for a cluster from article titles.

    Uses the shortest title as it tends to be the most headline-like.
    """
    placeholders = ", ".join("?" for _ in knowledge_ids)
    rows = conn.execute(
        f"SELECT title FROM knowledge WHERE id IN ({placeholders})",  # nosec B608
        knowledge_ids,
    ).fetchall()
    titles = [r["title"] for r in rows if r["title"]]
    if not titles:
        return "Untitled cluster"
    # Shortest title is usually the most concise headline
    return min(titles, key=len)


def _count_distinct_sources(conn, knowledge_ids: list[str]) -> int:
    """Count how many distinct news feed sources contributed to a cluster."""
    placeholders = ", ".join("?" for _ in knowledge_ids)
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT nfa.source_id) as cnt
        FROM news_feed_articles nfa
        WHERE nfa.knowledge_id IN ({placeholders})""",  # nosec B608
        knowledge_ids,
    ).fetchone()
    return row["cnt"] if row else 1


def run_signalforge_clustering() -> dict:
    """Daemon entry point: cluster related articles into stories.

    Clears old clusters and rebuilds from scratch using articles
    from the last SIGNALFORGE_CLUSTER_WINDOW_DAYS days.
    """
    init_db()
    conn = get_connection()
    try:
        # Get articles with embeddings
        items = _get_clusterable_articles(conn, SIGNALFORGE_CLUSTER_WINDOW_DAYS)
        if len(items) < 2:
            logger.info("SignalForge clustering: fewer than 2 articles, skipping")
            return {"clusters_found": 0, "articles_clustered": 0, "avg_size": 0}

        # Build clusters
        raw_clusters = _build_clusters(
            items, SIGNALFORGE_CLUSTER_SIMILARITY, SIGNALFORGE_CLUSTER_MAX_SIZE,
        )
        if not raw_clusters:
            logger.info("SignalForge clustering: no clusters found above threshold")
            return {"clusters_found": 0, "articles_clustered": 0, "avg_size": 0}

        # Clear old clusters before inserting new ones
        old_cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=SIGNALFORGE_CLUSTER_WINDOW_DAYS)
        ).isoformat()
        old_clusters = conn.execute(
            "SELECT id FROM signalforge_clusters WHERE created_at < ?",
            (old_cutoff,),
        ).fetchall()
        if old_clusters:
            old_ids = [r["id"] for r in old_clusters]
            placeholders = ", ".join("?" for _ in old_ids)
            conn.execute(
                f"DELETE FROM signalforge_cluster_articles WHERE cluster_id IN ({placeholders})",  # nosec B608
                old_ids,
            )
            conn.execute(
                f"DELETE FROM signalforge_clusters WHERE id IN ({placeholders})",  # nosec B608
                old_ids,
            )
            conn.commit()
            logger.info(
                "SignalForge clustering: cleaned %d old clusters", len(old_ids)
            )

        # Also clear current clusters to rebuild fresh
        conn.execute("DELETE FROM signalforge_cluster_articles")
        conn.execute("DELETE FROM signalforge_clusters")
        conn.commit()

        # Insert new clusters
        total_articles = 0
        for cluster_data in raw_clusters:
            kid_list = cluster_data["knowledge_ids"]
            avg_sim = cluster_data["avg_similarity"]

            label = _generate_cluster_label(conn, kid_list)
            source_count = _count_distinct_sources(conn, kid_list)
            significance = _compute_significance(
                len(kid_list), avg_sim, source_count,
            )

            cluster_id = uuid.uuid4().hex[:12]
            insert_signalforge_cluster(
                conn, cluster_id, label,
                article_count=len(kid_list),
                source_count=source_count,
                avg_similarity=avg_sim,
                significance=significance,
            )

            for kid in kid_list:
                insert_cluster_article(conn, cluster_id, kid)

            total_articles += len(kid_list)

        avg_size = round(total_articles / len(raw_clusters), 1) if raw_clusters else 0

        summary = {
            "clusters_found": len(raw_clusters),
            "articles_clustered": total_articles,
            "avg_size": avg_size,
        }
        logger.info("SignalForge clustering complete: %s", summary)
        return summary
    finally:
        conn.close()


def get_cluster_detail(cluster_id: str) -> Optional[dict]:
    """Get full details for a story cluster including all articles."""
    init_db()
    conn = get_connection()
    try:
        cluster = get_signalforge_cluster(conn, cluster_id)
        if not cluster:
            return None

        articles = get_cluster_articles(conn, cluster_id)
        article_list = [
            {
                "knowledge_id": a["id"],
                "title": a["title"],
                "source": a["source"],
                "created_at": a["created_at"],
            }
            for a in articles
        ]

        return {
            "cluster_id": cluster["id"],
            "label": cluster["label"],
            "article_count": cluster["article_count"],
            "source_count": cluster["source_count"],
            "avg_similarity": cluster["avg_similarity"],
            "significance": cluster["significance"],
            "created_at": cluster["created_at"],
            "articles": article_list,
        }
    finally:
        conn.close()


def get_clustering_status() -> dict:
    """Get story clustering dashboard data."""
    init_db()
    conn = get_connection()
    try:
        clusters = list_signalforge_clusters(conn, limit=100)
        total_clusters = len(clusters)

        total_articles = sum(c["article_count"] for c in clusters)
        avg_size = round(total_articles / total_clusters, 1) if total_clusters else 0

        # Top clusters by significance
        top = [
            {
                "cluster_id": c["id"],
                "label": c["label"],
                "article_count": c["article_count"],
                "source_count": c["source_count"],
                "significance": c["significance"],
            }
            for c in clusters[:10]
        ]

        # Unclustered fetched articles
        total_fetched = conn.execute(
            "SELECT COUNT(*) as cnt FROM signalforge_articles "
            "WHERE fetch_status = 'fetched'"
        ).fetchone()["cnt"]
        clustered_ids = conn.execute(
            "SELECT COUNT(DISTINCT knowledge_id) as cnt "
            "FROM signalforge_cluster_articles"
        ).fetchone()["cnt"]
        unclustered = total_fetched - clustered_ids

        return {
            "total_clusters": total_clusters,
            "total_articles_clustered": total_articles,
            "avg_cluster_size": avg_size,
            "unclustered_articles": unclustered,
            "top_clusters": top,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Synthesis — LLM-powered daily intelligence article
# ---------------------------------------------------------------------------


def _get_anthropic_client():
    """Return an Anthropic client, raising RuntimeError if no API key."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Cannot run SignalForge synthesis."
        )
    import anthropic

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _call_claude(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    model: str = "",
) -> dict:
    """Call Claude API and return {text, input_tokens, output_tokens, model}."""
    client = _get_anthropic_client()
    used_model = model or SIGNALFORGE_SYNTHESIS_MODEL
    response = client.messages.create(
        model=used_model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return {
        "text": response.content[0].text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "model": used_model,
    }


CLUSTER_SYNTHESIS_SYSTEM = (
    "You are a news analyst writing a daily cybersecurity intelligence briefing. "
    "Synthesize multiple articles about the same story into a concise, factual summary. "
    "Focus on: what happened, who is affected, why it matters, and what action to take. "
    "Write in clear, professional prose. No bullet points. No hedging language."
)

CLUSTER_SYNTHESIS_USER = """Synthesize these {article_count} articles about the same story into a 150-300 word summary.

Story topic: {label}

Articles:
{article_block}

Write a cohesive synthesis covering the key facts, affected parties, and implications."""

COMBINE_SYSTEM = (
    "You are a news editor assembling a daily cybersecurity intelligence briefing. "
    "Combine the individual story summaries into one cohesive article with a title. "
    "Start with a 2-3 sentence executive summary, then cover each story under a bold heading. "
    "Maintain a professional, authoritative tone. The audience is a security professional."
)

COMBINE_USER = """Combine these {story_count} story summaries into a daily intelligence briefing for {date}.

{stories_block}

Output format:
1. A short, compelling title for the daily briefing (one line)
2. A 2-3 sentence executive summary
3. Each story under a **bold heading**

Write the complete article."""


def _gather_cluster_data(
    conn, cluster_id: str, excerpt_chars: int = 0
) -> Optional[dict]:
    """Gather cluster metadata + article data for synthesis.

    Returns {cluster_id, label, significance, articles: [{title, source, text}]}
    or None if cluster not found.
    """
    cluster = get_signalforge_cluster(conn, cluster_id)
    if not cluster:
        return None

    articles_raw = get_cluster_articles(conn, cluster_id)
    articles = []
    for a in articles_raw:
        kid = a["id"]
        text = ""

        # Try Tier 1 full text first
        if excerpt_chars > 0:
            sf_article = get_signalforge_article_by_knowledge_id(conn, kid)
            if sf_article and sf_article["content_path"]:
                content_path = Path(sf_article["content_path"])
                if content_path.exists():
                    try:
                        raw = content_path.read_text(encoding="utf-8")
                        # Skip metadata header (lines before first blank line)
                        parts = raw.split("\n\n", 1)
                        body = parts[1] if len(parts) > 1 else raw
                        text = body[:excerpt_chars]
                    except Exception:
                        pass

        # Fall back to knowledge.content (RSS summary)
        if not text:
            k_row = conn.execute(
                "SELECT content FROM knowledge WHERE id = ?", (kid,)
            ).fetchone()
            if k_row:
                text = k_row["content"][:excerpt_chars] if excerpt_chars else k_row["content"]

        articles.append({
            "title": a["title"],
            "source": a["source"] or "Unknown",
            "text": text,
        })

    return {
        "cluster_id": cluster["id"],
        "label": cluster["label"],
        "significance": cluster["significance"],
        "article_count": cluster["article_count"],
        "articles": articles,
    }


def _synthesize_cluster(cluster_data: dict) -> dict:
    """Phase 1: Synthesize one cluster into a summary paragraph.

    Returns {text, input_tokens, output_tokens, cluster_id, label} or {error}.
    """
    article_block = "\n\n".join(
        f"### {a['title']} ({a['source']})\n{a['text']}"
        for a in cluster_data["articles"]
    )

    user_prompt = CLUSTER_SYNTHESIS_USER.format(
        article_count=cluster_data["article_count"],
        label=cluster_data["label"],
        article_block=article_block,
    )

    try:
        result = _call_claude(
            CLUSTER_SYNTHESIS_SYSTEM,
            user_prompt,
            SIGNALFORGE_SYNTHESIS_MAX_TOKENS_PER_CLUSTER,
        )
        return {
            "text": result["text"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cluster_id": cluster_data["cluster_id"],
            "label": cluster_data["label"],
        }
    except Exception as e:
        logger.error(
            "Synthesis failed for cluster %s: %s",
            cluster_data["cluster_id"], e,
        )
        return {"error": str(e), "cluster_id": cluster_data["cluster_id"]}


def _combine_stories(story_summaries: list[dict], synthesis_date: str) -> dict:
    """Phase 2: Combine cluster summaries into one cohesive article.

    Returns {text, title, input_tokens, output_tokens}.
    """
    stories_block = "\n\n---\n\n".join(
        f"**{s['label']}**\n\n{s['text']}"
        for s in story_summaries
    )

    user_prompt = COMBINE_USER.format(
        story_count=len(story_summaries),
        date=synthesis_date,
        stories_block=stories_block,
    )

    result = _call_claude(
        COMBINE_SYSTEM,
        user_prompt,
        SIGNALFORGE_SYNTHESIS_MAX_TOKENS_COMBINE,
    )

    # Extract title from first line of response
    lines = result["text"].strip().split("\n", 1)
    title = lines[0].strip().lstrip("#").strip()
    content = lines[1].strip() if len(lines) > 1 else result["text"]

    return {
        "text": content,
        "title": title,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
    }


def run_signalforge_synthesis(force: bool = False) -> dict:
    """Daemon/MCP entry point: synthesize top clusters into daily article.

    1. Check if today's synthesis exists (skip unless force=True)
    2. Get top clusters by significance
    3. Phase 1: synthesize each cluster
    4. Phase 2: combine into daily article
    5. Store in DB + publish to Google Doc
    """
    init_db()
    conn = get_connection()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Idempotency check
        existing = get_signalforge_synthesis_by_date(conn, today)
        if existing and not force:
            logger.info("SignalForge synthesis: already exists for %s", today)
            return {
                "status": "already_exists",
                "synthesis_date": today,
                "title": existing["title"],
            }

        # Get top clusters above minimum significance
        clusters = list_signalforge_clusters(
            conn,
            limit=SIGNALFORGE_SYNTHESIS_MAX_CLUSTERS,
            min_significance=SIGNALFORGE_SYNTHESIS_MIN_SIGNIFICANCE,
        )
        if not clusters:
            logger.info("SignalForge synthesis: no clusters above significance threshold")
            return {"status": "no_clusters", "synthesis_date": today}

        # Phase 1: Synthesize each cluster
        story_summaries = []
        total_input = 0
        total_output = 0
        cluster_ids = []

        for cluster in clusters:
            data = _gather_cluster_data(
                conn, cluster["id"],
                excerpt_chars=SIGNALFORGE_SYNTHESIS_EXCERPT_CHARS,
            )
            if not data:
                continue

            result = _synthesize_cluster(data)
            if "error" in result:
                continue

            story_summaries.append(result)
            total_input += result["input_tokens"]
            total_output += result["output_tokens"]
            cluster_ids.append(cluster["id"])

        if not story_summaries:
            logger.warning("SignalForge synthesis: all cluster syntheses failed")
            return {"status": "all_failed", "synthesis_date": today}

        # Phase 2: Combine into daily article
        combined = _combine_stories(story_summaries, today)
        total_input += combined["input_tokens"]
        total_output += combined["output_tokens"]

        word_count = len(combined["text"].split())
        total_articles = sum(c["article_count"] for c in clusters if c["id"] in cluster_ids)

        # Store in DB
        synthesis_id = uuid.uuid4().hex[:12]

        # If force and existing, delete old one first
        if existing and force:
            conn.execute(
                "DELETE FROM signalforge_synthesis WHERE id = ?",
                (existing["id"],),
            )
            conn.commit()

        insert_signalforge_synthesis(
            conn,
            synthesis_id=synthesis_id,
            synthesis_date=today,
            title=combined["title"],
            content=combined["text"],
            cluster_ids=json.dumps(cluster_ids),
            cluster_count=len(cluster_ids),
            article_count=total_articles,
            word_count=word_count,
            model_used=SIGNALFORGE_SYNTHESIS_MODEL,
            input_tokens=total_input,
            output_tokens=total_output,
        )

        # Publish to Google Doc
        gdoc_id = ""
        gdoc_url = ""
        try:
            from .gdocs import create_google_doc

            doc_title = f"SignalForge Briefing — {today}"
            full_content = f"# {combined['title']}\n\n{combined['text']}"
            doc_result = create_google_doc(doc_title, full_content)
            if doc_result.get("doc_id"):
                gdoc_id = doc_result["doc_id"]
                gdoc_url = doc_result.get("doc_url", "")
                update_signalforge_synthesis(
                    conn, synthesis_id, gdoc_id=gdoc_id, gdoc_url=gdoc_url,
                )
                logger.info("SignalForge synthesis published to Google Docs: %s", gdoc_url)
        except Exception as e:
            logger.warning("SignalForge synthesis: Google Doc publish failed: %s", e)

        summary = {
            "status": "synthesized",
            "synthesis_date": today,
            "synthesis_id": synthesis_id,
            "title": combined["title"],
            "cluster_count": len(cluster_ids),
            "article_count": total_articles,
            "word_count": word_count,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "gdoc_url": gdoc_url or None,
        }

        logger.info("SignalForge synthesis complete: %s", summary)
        return summary
    finally:
        conn.close()


def get_synthesis_status() -> dict:
    """Dashboard: today's synthesis, recent syntheses, token usage."""
    init_db()
    conn = get_connection()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_synthesis = get_signalforge_synthesis_by_date(conn, today)

        recent = list_signalforge_syntheses(conn, limit=7)
        recent_list = [
            {
                "synthesis_date": r["synthesis_date"],
                "title": r["title"],
                "cluster_count": r["cluster_count"],
                "article_count": r["article_count"],
                "word_count": r["word_count"],
                "gdoc_url": r["gdoc_url"] or None,
            }
            for r in recent
        ]

        # Total token usage across all syntheses
        token_row = conn.execute(
            "SELECT SUM(input_tokens) as total_in, SUM(output_tokens) as total_out, "
            "COUNT(*) as count FROM signalforge_synthesis"
        ).fetchone()

        return {
            "today": {
                "synthesized": today_synthesis is not None,
                "title": today_synthesis["title"] if today_synthesis else None,
                "word_count": today_synthesis["word_count"] if today_synthesis else None,
                "gdoc_url": (today_synthesis["gdoc_url"] or None) if today_synthesis else None,
            },
            "recent_syntheses": recent_list,
            "token_usage": {
                "total_syntheses": token_row["count"] or 0,
                "total_input_tokens": token_row["total_in"] or 0,
                "total_output_tokens": token_row["total_out"] or 0,
            },
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def get_signalforge_status() -> dict:
    """Get SignalForge dashboard data: counts, storage, recent activity."""
    init_db()
    conn = get_connection()
    try:
        # Counts by status
        status_counts = count_signalforge_by_status(conn)

        # Storage size
        total_bytes = 0
        file_count = 0
        if SIGNALFORGE_ARTICLES_DIR.exists():
            for f in SIGNALFORGE_ARTICLES_DIR.rglob("*.txt"):
                total_bytes += f.stat().st_size
                file_count += 1

        # Average word count (fetched articles only)
        avg_row = conn.execute(
            "SELECT AVG(word_count) as avg_wc FROM signalforge_articles "
            "WHERE fetch_status = 'fetched'"
        ).fetchone()
        avg_words = round(avg_row["avg_wc"] or 0)

        # Recent fetches (last 5)
        recent = conn.execute(
            "SELECT sa.id, sa.knowledge_id, sa.word_count, sa.fetched_at, "
            "k.title "
            "FROM signalforge_articles sa "
            "LEFT JOIN knowledge k ON k.id = sa.knowledge_id "
            "WHERE sa.fetch_status = 'fetched' "
            "ORDER BY sa.fetched_at DESC LIMIT 5"
        ).fetchall()
        recent_list = [
            {
                "id": r["id"],
                "title": r["title"] or "Unknown",
                "word_count": r["word_count"],
                "fetched_at": r["fetched_at"],
            }
            for r in recent
        ]

        # Recent failures (last 5)
        failures = conn.execute(
            "SELECT sa.id, sa.knowledge_id, sa.fetch_error, sa.fetched_at, "
            "k.title "
            "FROM signalforge_articles sa "
            "LEFT JOIN knowledge k ON k.id = sa.knowledge_id "
            "WHERE sa.fetch_status = 'failed' "
            "ORDER BY sa.fetched_at DESC LIMIT 5"
        ).fetchall()
        failure_list = [
            {
                "id": f["id"],
                "title": f["title"] or "Unknown",
                "error": f["fetch_error"],
                "fetched_at": f["fetched_at"],
            }
            for f in failures
        ]

        # Expiring soon (next 7 days)
        soon = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        expiring = conn.execute(
            "SELECT COUNT(*) as cnt FROM signalforge_articles "
            "WHERE fetch_status = 'fetched' AND expires_at < ?",
            (soon,),
        ).fetchone()

        return {
            "status_counts": status_counts,
            "storage": {
                "file_count": file_count,
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2),
            },
            "avg_word_count": avg_words,
            "recent_fetches": recent_list,
            "recent_failures": failure_list,
            "expiring_soon_7d": expiring["cnt"],
        }
    finally:
        conn.close()
