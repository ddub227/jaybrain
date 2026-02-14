"""Memory store, retrieve, decay, and markdown file writing."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import (
    MEMORIES_DIR,
    DECAY_HALF_LIFE_DAYS,
    DECAY_ACCESS_HALF_LIFE_BONUS,
    DECAY_MAX_HALF_LIFE,
    MIN_DECAY,
    DEFAULT_SEARCH_LIMIT,
    SEARCH_CANDIDATES,
)
from .db import (
    get_connection,
    insert_memory,
    delete_memory,
    get_memory,
    get_memories_batch,
    update_memory_access,
    search_memories_fts,
    search_memories_vec,
    get_all_memories,
)
from .models import Memory, MemoryCategory, MemorySearchResult
from .search import embed_text, hybrid_search

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_memory_row(row: sqlite3.Row) -> Memory:
    """Convert a database row to a Memory model."""
    return Memory(
        id=row["id"],
        content=row["content"],
        category=MemoryCategory(row["category"]),
        tags=json.loads(row["tags"]),
        importance=row["importance"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        access_count=row["access_count"],
        last_accessed=(
            datetime.fromisoformat(row["last_accessed"])
            if row["last_accessed"]
            else None
        ),
        session_id=row["session_id"] if row["session_id"] else None,
    )


def _write_memory_markdown(memory: Memory) -> None:
    """Append memory to the appropriate markdown file (file-first pattern)."""
    category_dir = MEMORIES_DIR / memory.category.value
    category_dir.mkdir(parents=True, exist_ok=True)

    date_str = memory.created_at.strftime("%Y-%m-%d")
    md_file = category_dir / f"{date_str}.md"

    tags_str = ", ".join(memory.tags) if memory.tags else "none"
    entry = (
        f"\n## [{memory.id}] {memory.created_at.strftime('%H:%M:%S UTC')}\n"
        f"**Importance:** {memory.importance} | **Tags:** {tags_str}\n\n"
        f"{memory.content}\n"
    )

    # Create file with header if it doesn't exist
    if not md_file.exists():
        header = f"# Memories: {memory.category.value} - {date_str}\n"
        md_file.write_text(header + entry, encoding="utf-8")
    else:
        with open(md_file, "a", encoding="utf-8") as f:
            f.write(entry)


def compute_decay(
    created_at: datetime,
    importance: float,
    access_count: int = 0,
    last_accessed: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> float:
    """Compute memory decay factor using SM-2 inspired exponential model.

    Each access extends the half-life, so frequently accessed memories persist
    much longer. Importance scales the final score.

    Returns a value between MIN_DECAY and 1.0.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure datetimes are timezone-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    # Effective half-life grows with each access
    effective_half_life = min(
        DECAY_HALF_LIFE_DAYS + (access_count * DECAY_ACCESS_HALF_LIFE_BONUS),
        DECAY_MAX_HALF_LIFE,
    )

    # Decay from the most recent touch point (creation or last access)
    last_touch = created_at
    if last_accessed is not None:
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        if last_accessed > created_at:
            last_touch = last_accessed

    days_since_touch = max(0.0, (now - last_touch).total_seconds() / 86400)

    # Exponential decay: 0.5^(days / half_life)
    raw_decay = 0.5 ** (days_since_touch / effective_half_life)

    # Importance scales the result: importance=1.0 -> full score, importance=0.0 -> half score
    final = raw_decay * (0.5 + 0.5 * importance)

    return max(MIN_DECAY, final)


def remember(
    content: str,
    category: str = "semantic",
    tags: Optional[list[str]] = None,
    importance: float = 0.5,
) -> Memory:
    """Store a new memory. Writes markdown file, generates embedding, inserts into DB."""
    from .sessions import get_current_session_id

    tags = tags or []
    memory_id = _generate_id()
    session_id = get_current_session_id()

    # Generate embedding
    try:
        embedding = embed_text(content)
    except Exception as e:
        logger.warning("Embedding generation failed, storing without vector: %s", e)
        embedding = None

    # Insert into database
    conn = get_connection()
    try:
        insert_memory(conn, memory_id, content, category, tags, importance, embedding, session_id)
        row = get_memory(conn, memory_id)
    finally:
        conn.close()

    memory = _parse_memory_row(row)

    # Write to markdown file (file-first)
    try:
        _write_memory_markdown(memory)
    except Exception as e:
        logger.warning("Failed to write memory markdown: %s", e)

    return memory


def recall(
    query: str,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[MemorySearchResult]:
    """Search memories using hybrid vector + keyword search with decay scoring."""
    conn = get_connection()
    try:
        # Vector search path
        vec_results = []
        try:
            query_embedding = embed_text(query)
            vec_results = search_memories_vec(conn, query_embedding, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("Vector search failed, falling back to keyword only: %s", e)

        # Keyword search path
        fts_results = []
        try:
            # Escape FTS5 special characters for safe query
            safe_query = _fts5_safe_query(query)
            if safe_query:
                fts_results = search_memories_fts(conn, safe_query, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("FTS search failed: %s", e)

        # Merge results
        if vec_results or fts_results:
            merged = hybrid_search(vec_results, fts_results)
        else:
            # Fall back to listing recent memories
            rows = get_all_memories(conn, category, limit)
            return [
                MemorySearchResult(
                    memory=_parse_memory_row(row),
                    score=1.0,
                )
                for row in rows
            ]

        # Batch fetch all candidate memories in one query
        candidate_ids = [mem_id for mem_id, _ in merged]
        rows_by_id = get_memories_batch(conn, candidate_ids)

        # Build lookup dicts for individual scores
        vec_scores = {vid: vd for vid, vd in vec_results}
        kw_scores = {kid: ks for kid, ks in fts_results}

        # Apply decay and filters
        results = []
        now = datetime.now(timezone.utc)
        for mem_id, search_score in merged:
            row = rows_by_id.get(mem_id)
            if row is None:
                continue

            memory = _parse_memory_row(row)

            # Filter by category if specified
            if category and memory.category.value != category:
                continue

            # Filter by tags if specified
            if tags and not any(t in memory.tags for t in tags):
                continue

            # Apply decay (importance is factored into decay now)
            decay = compute_decay(
                memory.created_at, memory.importance,
                memory.access_count, memory.last_accessed, now,
            )
            final_score = search_score * decay

            results.append(MemorySearchResult(
                memory=memory,
                score=round(final_score, 4),
                vector_score=round(vec_scores.get(mem_id, 0.0), 4),
                keyword_score=round(kw_scores.get(mem_id, 0.0), 4),
            ))

            # Update access count
            update_memory_access(conn, mem_id)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
    finally:
        conn.close()


def forget(memory_id: str) -> bool:
    """Delete a memory by ID. Returns True if found and deleted."""
    conn = get_connection()
    try:
        return delete_memory(conn, memory_id)
    finally:
        conn.close()


def reinforce(memory_id: str) -> Optional[Memory]:
    """Boost a memory's importance by incrementing access count."""
    conn = get_connection()
    try:
        update_memory_access(conn, memory_id)
        row = get_memory(conn, memory_id)
        if row is None:
            return None
        return _parse_memory_row(row)
    finally:
        conn.close()


def _fts5_safe_query(query: str) -> str:
    """Convert a natural language query into a safe FTS5 query.

    Wraps individual words in quotes to avoid FTS5 syntax errors from
    special characters like AND, OR, NOT, -, etc.
    """
    words = query.split()
    safe_words = []
    for word in words:
        # Strip punctuation that could cause FTS5 issues
        cleaned = "".join(c for c in word if c.isalnum() or c == "_")
        if cleaned:
            safe_words.append(f'"{cleaned}"')
    return " ".join(safe_words)
