"""Knowledge base operations - store, search, update structured knowledge."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import SEARCH_CANDIDATES, DEFAULT_SEARCH_LIMIT
from .db import (
    fts5_safe_query,
    get_connection,
    insert_knowledge,
    update_knowledge,
    get_knowledge,
    search_knowledge_fts,
    search_knowledge_vec,
)
from .models import Knowledge, KnowledgeSearchResult
from .search import embed_text, hybrid_search

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_knowledge_row(row) -> Knowledge:
    """Convert a database row to a Knowledge model."""
    return Knowledge(
        id=row["id"],
        title=row["title"],
        content=row["content"],
        category=row["category"],
        tags=json.loads(row["tags"]),
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def store_knowledge(
    title: str,
    content: str,
    category: str = "general",
    tags: Optional[list[str]] = None,
    source: str = "",
) -> Knowledge:
    """Store a new knowledge entry with embedding."""
    tags = tags or []
    knowledge_id = _generate_id()

    # Generate embedding from title + content
    try:
        embedding = embed_text(f"{title} {content}")
    except Exception as e:
        logger.warning("Embedding generation failed for knowledge: %s", e)
        embedding = None

    conn = get_connection()
    try:
        insert_knowledge(conn, knowledge_id, title, content, category, tags, source, embedding)
        row = get_knowledge(conn, knowledge_id)
        return _parse_knowledge_row(row)
    finally:
        conn.close()


def search_knowledge_entries(
    query: str,
    category: Optional[str] = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[KnowledgeSearchResult]:
    """Search knowledge base using hybrid vector + keyword search."""
    conn = get_connection()
    try:
        # Vector search
        vec_results = []
        try:
            query_embedding = embed_text(query)
            vec_results = search_knowledge_vec(conn, query_embedding, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("Vector search failed for knowledge: %s", e)

        # Keyword search
        fts_results = []
        try:
            safe_query = fts5_safe_query(query)
            if safe_query:
                fts_results = search_knowledge_fts(conn, safe_query, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("FTS search failed for knowledge: %s", e)

        if not vec_results and not fts_results:
            return []

        merged = hybrid_search(vec_results, fts_results)

        results = []
        for kid, score in merged:
            row = get_knowledge(conn, kid)
            if row is None:
                continue

            knowledge = _parse_knowledge_row(row)

            if category and knowledge.category != category:
                continue

            results.append(KnowledgeSearchResult(
                knowledge=knowledge,
                score=round(score, 4),
            ))

        return results[:limit]
    finally:
        conn.close()


def modify_knowledge(knowledge_id: str, **fields) -> Optional[Knowledge]:
    """Update a knowledge entry's fields.

    Uses a single connection so that the relational update and any
    embedding update are atomic (committed together or not at all).
    """
    conn = get_connection()
    try:
        # If content or title changed, update the embedding
        if "content" in fields or "title" in fields:
            row = get_knowledge(conn, knowledge_id)
            if not row:
                return None
            new_title = fields.get("title", row["title"])
            new_content = fields.get("content", row["content"])
            try:
                embedding = embed_text(f"{new_title} {new_content}")
                from .db import _serialize_f32
                conn.execute(
                    "UPDATE knowledge_vec SET embedding = ? WHERE id = ?",
                    (_serialize_f32(embedding), knowledge_id),
                )
            except Exception as e:
                logger.warning("Failed to update knowledge embedding: %s", e)

        success = update_knowledge(conn, knowledge_id, **fields)
        if not success:
            return None
        row = get_knowledge(conn, knowledge_id)
        if not row:
            return None
        return _parse_knowledge_row(row)
    finally:
        conn.close()


