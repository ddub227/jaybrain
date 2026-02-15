"""Memory consolidation: clustering, deduplication, merging, and archival."""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter, defaultdict
from typing import Optional

import numpy as np

from .config import (
    CONSOLIDATION_DEFAULT_SIMILARITY,
    CONSOLIDATION_DUPLICATE_THRESHOLD,
    CONSOLIDATION_MAX_CLUSTER_SIZE,
)
from .db import (
    get_connection,
    get_all_memory_embeddings,
    get_memories_batch,
    archive_memory,
    insert_memory,
    insert_consolidation_log,
    get_consolidation_log,
    _deserialize_f32,
)
from .memory import _parse_memory_row
from .search import embed_text

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def find_clusters(
    min_similarity: float = CONSOLIDATION_DEFAULT_SIMILARITY,
    max_age_days: Optional[int] = None,
    category: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Find clusters of semantically similar memories.

    Uses numpy pairwise cosine similarity + BFS connected components.
    O(n^2) but fast for <5000 memories on an N100.
    """
    conn = get_connection()
    try:
        raw_embeddings = get_all_memory_embeddings(conn, category, max_age_days)
        if len(raw_embeddings) < 2:
            return []

        ids = [r[0] for r in raw_embeddings]
        vectors = [_deserialize_f32(r[1]) for r in raw_embeddings]

        # Build numpy matrix and compute pairwise cosine similarities
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
                if sim_matrix[i, j] >= min_similarity:
                    adjacency[i].add(j)
                    adjacency[j].add(i)

        # BFS to find connected components
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
                components.append(component[:CONSOLIDATION_MAX_CLUSTER_SIZE])

        # Build output with full memory details
        all_cluster_ids = []
        for comp in components:
            for idx in comp:
                all_cluster_ids.append(ids[idx])
        rows_by_id = get_memories_batch(conn, all_cluster_ids)

        clusters = []
        for cluster_num, comp in enumerate(components):
            cluster_ids_list = [ids[idx] for idx in comp]

            # Average pairwise similarity within cluster
            sims = []
            for i_idx in range(len(comp)):
                for j_idx in range(i_idx + 1, len(comp)):
                    sims.append(float(sim_matrix[comp[i_idx], comp[j_idx]]))
            avg_sim = sum(sims) / len(sims) if sims else 0.0

            memories = []
            for mid in cluster_ids_list:
                row = rows_by_id.get(mid)
                if row:
                    mem = _parse_memory_row(row)
                    memories.append({
                        "id": mem.id,
                        "content": mem.content,
                        "category": mem.category.value,
                        "tags": mem.tags,
                        "importance": mem.importance,
                        "created_at": mem.created_at.isoformat(),
                        "access_count": mem.access_count,
                    })

            clusters.append({
                "cluster_id": cluster_num,
                "memory_count": len(memories),
                "avg_similarity": round(avg_sim, 4),
                "memories": memories,
            })

        clusters.sort(key=lambda c: c["memory_count"], reverse=True)
        return clusters[:limit]
    finally:
        conn.close()


def find_duplicates(
    threshold: float = CONSOLIDATION_DUPLICATE_THRESHOLD,
    category: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Find near-duplicate memory pairs above the similarity threshold."""
    conn = get_connection()
    try:
        raw_embeddings = get_all_memory_embeddings(conn, category)
        if len(raw_embeddings) < 2:
            return []

        ids = [r[0] for r in raw_embeddings]
        vectors = [_deserialize_f32(r[1]) for r in raw_embeddings]

        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-9)
        normalized = matrix / norms
        sim_matrix = normalized @ normalized.T

        pairs: list[tuple[str, str, float]] = []
        n = len(ids)
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    pairs.append((ids[i], ids[j], sim))

        pairs.sort(key=lambda x: x[2], reverse=True)
        pairs = pairs[:limit]

        all_ids = list({p[0] for p in pairs} | {p[1] for p in pairs})
        rows_by_id = get_memories_batch(conn, all_ids)

        result = []
        for id_a, id_b, sim in pairs:
            row_a = rows_by_id.get(id_a)
            row_b = rows_by_id.get(id_b)
            if row_a and row_b:
                mem_a = _parse_memory_row(row_a)
                mem_b = _parse_memory_row(row_b)
                result.append({
                    "similarity": round(sim, 4),
                    "memory_a": {
                        "id": mem_a.id,
                        "content": mem_a.content,
                        "category": mem_a.category.value,
                        "importance": mem_a.importance,
                        "created_at": mem_a.created_at.isoformat(),
                    },
                    "memory_b": {
                        "id": mem_b.id,
                        "content": mem_b.content,
                        "category": mem_b.category.value,
                        "importance": mem_b.importance,
                        "created_at": mem_b.created_at.isoformat(),
                    },
                })

        return result
    finally:
        conn.close()


def merge_memories(
    memory_ids: list[str],
    merged_content: str,
    merged_tags: Optional[list[str]] = None,
    merged_importance: Optional[float] = None,
    reason: str = "",
) -> dict:
    """Merge multiple memories into one new consolidated memory.

    Claude provides merged_content. Originals are archived with audit trail.
    """
    conn = get_connection()
    try:
        rows_by_id = get_memories_batch(conn, memory_ids)
        missing = [mid for mid in memory_ids if mid not in rows_by_id]
        if missing:
            return {"error": f"Memory IDs not found: {missing}"}

        source_memories = [_parse_memory_row(rows_by_id[mid]) for mid in memory_ids]

        if merged_tags is None:
            all_tags: set[str] = set()
            for mem in source_memories:
                all_tags.update(mem.tags)
            merged_tags = sorted(all_tags)

        if merged_importance is None:
            merged_importance = max(mem.importance for mem in source_memories)

        cat_counts = Counter(mem.category.value for mem in source_memories)
        merged_category = cat_counts.most_common(1)[0][0]

        new_id = _generate_id()
        run_id = _generate_id()

        try:
            embedding = embed_text(merged_content)
        except Exception:
            embedding = None

        from .sessions import get_current_session_id
        session_id = get_current_session_id()

        insert_memory(
            conn, new_id, merged_content, merged_category,
            merged_tags, merged_importance, embedding, session_id,
        )

        for mid in memory_ids:
            archive_memory(
                conn, mid,
                archive_reason="consolidated",
                merged_into_id=new_id,
                consolidation_run_id=run_id,
            )

        insert_consolidation_log(
            conn, run_id, "merge", memory_ids,
            result_memory_id=new_id,
            merged_content_preview=merged_content[:200],
            reason=reason or f"Merged {len(memory_ids)} similar memories",
        )

        return {
            "status": "merged",
            "new_memory_id": new_id,
            "archived_count": len(memory_ids),
            "consolidated_from": memory_ids,
            "category": merged_category,
            "importance": merged_importance,
            "run_id": run_id,
        }
    finally:
        conn.close()


def archive_memories(
    memory_ids: list[str],
    reason: str = "manual_archive",
) -> dict:
    """Archive multiple memories (soft delete) without merging."""
    conn = get_connection()
    try:
        archived = []
        not_found = []
        run_id = _generate_id()

        for mid in memory_ids:
            success = archive_memory(conn, mid, archive_reason=reason,
                                     consolidation_run_id=run_id)
            if success:
                archived.append(mid)
            else:
                not_found.append(mid)

        if archived:
            insert_consolidation_log(
                conn, run_id, "archive", archived,
                reason=reason,
            )

        return {
            "status": "archived",
            "archived": archived,
            "not_found": not_found,
            "run_id": run_id,
        }
    finally:
        conn.close()


def get_consolidation_stats() -> dict:
    """Get consolidation history and statistics."""
    conn = get_connection()
    try:
        logs = get_consolidation_log(conn, limit=100)
        archive_count = conn.execute(
            "SELECT COUNT(*) FROM memory_archive"
        ).fetchone()[0]
        active_count = conn.execute(
            "SELECT COUNT(*) FROM memories"
        ).fetchone()[0]

        action_counts: dict[str, int] = {}
        for log in logs:
            action = log["action"]
            action_counts[action] = action_counts.get(action, 0) + 1

        recent = []
        for log in logs[:20]:
            recent.append({
                "id": log["id"],
                "action": log["action"],
                "source_count": len(json.loads(log["source_memory_ids"])),
                "result_memory_id": log["result_memory_id"],
                "preview": log["merged_content_preview"][:100] if log["merged_content_preview"] else "",
                "reason": log["reason"],
                "created_at": log["created_at"],
            })

        return {
            "active_memories": active_count,
            "archived_memories": archive_count,
            "total_consolidation_runs": len(logs),
            "actions_by_type": action_counts,
            "recent_logs": recent,
        }
    finally:
        conn.close()
