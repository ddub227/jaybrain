"""Deep recall: fused search across memories, knowledge, and knowledge graph.

Generates one embedding, searches all three subsystems, follows entity->memory
links to surface results that wouldn't match the text query alone, deduplicates,
and returns structured sections.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .config import SEARCH_CANDIDATES, DEFAULT_SEARCH_LIMIT
from .db import (
    fts5_safe_query,
    get_connection,
    get_memories_batch,
    get_knowledge,
    search_memories_fts,
    search_memories_vec,
    search_knowledge_fts,
    search_knowledge_vec,
    search_graph_entities,
    get_entity_relationships,
    get_graph_entity,
    update_memory_access,
)
from .graph import _format_entity
from .knowledge import _parse_knowledge_row
from .memory import _parse_memory_row, compute_decay
from .search import embed_text, hybrid_search

logger = logging.getLogger(__name__)


def deep_recall(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> dict:
    """Fused search across memories, knowledge, and knowledge graph.

    Generates one embedding, searches all three subsystems, follows
    entity->memory links, deduplicates, and returns structured sections.
    """
    # Step 1: Generate embedding ONCE
    query_embedding = None
    try:
        query_embedding = embed_text(query)
    except Exception as e:
        logger.warning("Embedding generation failed for deep_recall: %s", e)

    safe_query = fts5_safe_query(query)

    conn = get_connection()
    try:
        # Step 2: Run all searches
        mem_vec = []
        if query_embedding:
            try:
                mem_vec = search_memories_vec(conn, query_embedding, SEARCH_CANDIDATES)
            except Exception as e:
                logger.warning("Memory vec search failed: %s", e)

        mem_fts = []
        if safe_query:
            try:
                mem_fts = search_memories_fts(conn, safe_query, SEARCH_CANDIDATES)
            except Exception as e:
                logger.warning("Memory FTS search failed: %s", e)

        know_vec = []
        if query_embedding:
            try:
                know_vec = search_knowledge_vec(conn, query_embedding, SEARCH_CANDIDATES)
            except Exception as e:
                logger.warning("Knowledge vec search failed: %s", e)

        know_fts = []
        if safe_query:
            try:
                know_fts = search_knowledge_fts(conn, safe_query, SEARCH_CANDIDATES)
            except Exception as e:
                logger.warning("Knowledge FTS search failed: %s", e)

        graph_rows = []
        try:
            graph_rows = search_graph_entities(conn, query, limit=limit)
        except Exception as e:
            logger.warning("Graph entity search failed: %s", e)

        # Step 3: Merge hybrid results
        mem_merged = hybrid_search(mem_vec, mem_fts) if (mem_vec or mem_fts) else []
        know_merged = hybrid_search(know_vec, know_fts) if (know_vec or know_fts) else []

        # Step 4: Build memories section (with decay)
        seen_memory_ids: set[str] = set()
        memories_out = []
        now = datetime.now(timezone.utc)

        if mem_merged:
            candidate_ids = [mid for mid, _ in mem_merged]
            rows_by_id = get_memories_batch(conn, candidate_ids)

            for mem_id, search_score in mem_merged:
                if len(memories_out) >= limit:
                    break
                row = rows_by_id.get(mem_id)
                if row is None:
                    continue
                memory = _parse_memory_row(row)
                decay = compute_decay(
                    memory.created_at, memory.importance,
                    memory.access_count, memory.last_accessed, now,
                )
                final_score = search_score * decay
                memories_out.append({
                    "id": memory.id,
                    "content": memory.content,
                    "category": memory.category.value,
                    "tags": memory.tags,
                    "importance": memory.importance,
                    "score": round(final_score, 4),
                    "created_at": memory.created_at.isoformat(),
                })
                seen_memory_ids.add(memory.id)
                update_memory_access(conn, mem_id)

        # Step 5: Build knowledge section
        knowledge_out = []
        if know_merged:
            for kid, score in know_merged:
                if len(knowledge_out) >= limit:
                    break
                row = get_knowledge(conn, kid)
                if row is None:
                    continue
                k = _parse_knowledge_row(row)
                knowledge_out.append({
                    "id": k.id,
                    "title": k.title,
                    "content": k.content,
                    "category": k.category,
                    "tags": k.tags,
                    "source": k.source,
                    "score": round(score, 4),
                })

        # Step 6: Build graph section + collect entity-linked memory IDs
        entities_out = []
        entity_id_to_name: dict[str, str] = {}
        linked_ids: set[str] = set()

        for row in graph_rows:
            entity = _format_entity(row)
            entities_out.append(entity)
            entity_id_to_name[entity["id"]] = entity["name"]
            for mid in entity.get("memory_ids", []):
                if mid and mid not in seen_memory_ids:
                    linked_ids.add(mid)

        # Step 7: Fetch entity-linked memories (deduplicated)
        linked_out = []
        if linked_ids:
            linked_rows = get_memories_batch(conn, list(linked_ids))
            for mid, row in linked_rows.items():
                memory = _parse_memory_row(row)
                linked_out.append({
                    "id": memory.id,
                    "content": memory.content,
                    "category": memory.category.value,
                    "tags": memory.tags,
                    "importance": memory.importance,
                    "created_at": memory.created_at.isoformat(),
                    "linked_from": "graph_entity",
                })
                seen_memory_ids.add(mid)
                update_memory_access(conn, mid)

        # Step 8: Fetch relationships for found entities
        connections_out = []
        seen_rel_ids: set[str] = set()

        for entity_id in entity_id_to_name:
            try:
                rels = get_entity_relationships(conn, entity_id, direction="both")
                for rel in rels:
                    rel_id = rel["id"]
                    if rel_id in seen_rel_ids:
                        continue
                    seen_rel_ids.add(rel_id)

                    source_name = entity_id_to_name.get(rel["source_entity_id"])
                    target_name = entity_id_to_name.get(rel["target_entity_id"])

                    if not source_name:
                        srow = get_graph_entity(conn, rel["source_entity_id"])
                        source_name = srow["name"] if srow else rel["source_entity_id"]
                    if not target_name:
                        trow = get_graph_entity(conn, rel["target_entity_id"])
                        target_name = trow["name"] if trow else rel["target_entity_id"]

                    connections_out.append({
                        "source": source_name,
                        "target": target_name,
                        "rel_type": rel["rel_type"],
                        "weight": rel["weight"],
                    })
            except Exception as e:
                logger.warning("Relationship fetch failed for %s: %s", entity_id, e)

        # Step 9: Assemble response
        return {
            "query": query,
            "memories": memories_out,
            "knowledge": knowledge_out,
            "graph": {
                "entities": entities_out,
                "connections": connections_out,
            },
            "linked_memories": linked_out,
            "summary": {
                "memory_count": len(memories_out),
                "knowledge_count": len(knowledge_out),
                "entity_count": len(entities_out),
                "linked_memory_count": len(linked_out),
                "connection_count": len(connections_out),
            },
        }
    finally:
        conn.close()
