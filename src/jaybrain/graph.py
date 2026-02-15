"""Knowledge graph: entities, relationships, and traversal queries."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from .config import GRAPH_DEFAULT_DEPTH, GRAPH_MAX_DEPTH
from .db import (
    get_connection,
    insert_graph_entity,
    update_graph_entity,
    get_graph_entity,
    get_graph_entity_by_name,
    search_graph_entities,
    list_graph_entities,
    insert_graph_relationship,
    update_graph_relationship,
    get_graph_relationship_by_triple,
    get_entity_relationships,
)

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _format_entity(row) -> dict:
    """Convert a graph_entities row to a serializable dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "entity_type": row["entity_type"],
        "description": row["description"],
        "aliases": json.loads(row["aliases"]),
        "memory_ids": json.loads(row["memory_ids"]),
        "properties": json.loads(row["properties"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _format_relationship(row) -> dict:
    """Convert a graph_relationships row to a serializable dict."""
    return {
        "id": row["id"],
        "source_entity_id": row["source_entity_id"],
        "target_entity_id": row["target_entity_id"],
        "rel_type": row["rel_type"],
        "weight": row["weight"],
        "evidence_ids": json.loads(row["evidence_ids"]),
        "properties": json.loads(row["properties"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def add_entity(
    name: str,
    entity_type: str,
    description: str = "",
    aliases: Optional[list[str]] = None,
    source_memory_ids: Optional[list[str]] = None,
    properties: Optional[dict] = None,
) -> dict:
    """Add or update an entity node. Merges if same name+type exists."""
    conn = get_connection()
    try:
        existing = get_graph_entity_by_name(conn, name, entity_type)
        if existing:
            old_memory_ids = json.loads(existing["memory_ids"])
            old_aliases = json.loads(existing["aliases"])
            old_props = json.loads(existing["properties"])

            new_memory_ids = sorted(set(old_memory_ids + (source_memory_ids or [])))
            new_aliases = sorted(set(old_aliases + (aliases or [])))
            new_props = {**old_props, **(properties or {})}
            new_desc = description if description else existing["description"]

            update_graph_entity(
                conn, existing["id"],
                description=new_desc,
                aliases=new_aliases,
                memory_ids=new_memory_ids,
                properties=new_props,
            )
            row = get_graph_entity(conn, existing["id"])
            return {"status": "updated", "entity": _format_entity(row)}

        entity_id = _generate_id()
        insert_graph_entity(
            conn, entity_id, name, entity_type, description,
            aliases or [], source_memory_ids or [], properties or {},
        )
        row = get_graph_entity(conn, entity_id)
        return {"status": "created", "entity": _format_entity(row)}
    finally:
        conn.close()


def add_relationship(
    source_entity: str,
    target_entity: str,
    rel_type: str,
    weight: float = 1.0,
    evidence_ids: Optional[list[str]] = None,
    properties: Optional[dict] = None,
) -> dict:
    """Add or update a relationship edge. Resolves entities by ID or name."""
    conn = get_connection()
    try:
        source_row = get_graph_entity(conn, source_entity)
        if not source_row:
            source_row = get_graph_entity_by_name(conn, source_entity)
        if not source_row:
            return {"error": f"Source entity not found: {source_entity}"}

        target_row = get_graph_entity(conn, target_entity)
        if not target_row:
            target_row = get_graph_entity_by_name(conn, target_entity)
        if not target_row:
            return {"error": f"Target entity not found: {target_entity}"}

        source_id = source_row["id"]
        target_id = target_row["id"]

        existing = get_graph_relationship_by_triple(conn, source_id, target_id, rel_type)
        if existing:
            old_evidence = json.loads(existing["evidence_ids"])
            old_props = json.loads(existing["properties"])
            new_evidence = sorted(set(old_evidence + (evidence_ids or [])))
            new_props = {**old_props, **(properties or {})}

            update_graph_relationship(
                conn, existing["id"],
                weight=weight,
                evidence_ids=new_evidence,
                properties=new_props,
            )
            return {
                "status": "updated",
                "relationship_id": existing["id"],
                "source": source_row["name"],
                "target": target_row["name"],
                "rel_type": rel_type,
                "weight": weight,
            }

        rel_id = _generate_id()
        insert_graph_relationship(
            conn, rel_id, source_id, target_id, rel_type,
            weight, evidence_ids or [], properties or {},
        )
        return {
            "status": "created",
            "relationship_id": rel_id,
            "source": source_row["name"],
            "target": target_row["name"],
            "rel_type": rel_type,
            "weight": weight,
        }
    finally:
        conn.close()


def query_neighborhood(
    entity_name: str,
    depth: int = GRAPH_DEFAULT_DEPTH,
    entity_type: Optional[str] = None,
) -> dict:
    """Get an entity and its N-depth neighborhood via BFS traversal."""
    depth = min(depth, GRAPH_MAX_DEPTH)
    conn = get_connection()
    try:
        center = get_graph_entity_by_name(conn, entity_name, entity_type)
        if not center:
            center = get_graph_entity(conn, entity_name)
        if not center:
            return {"error": f"Entity not found: {entity_name}"}

        center_id = center["id"]
        visited_entities: dict[str, dict] = {center_id: _format_entity(center)}
        all_relationships: list[dict] = []
        frontier: set[str] = {center_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for eid in frontier:
                rels = get_entity_relationships(conn, eid, direction="both")
                for rel in rels:
                    rel_dict = _format_relationship(rel)
                    if not any(r["id"] == rel_dict["id"] for r in all_relationships):
                        all_relationships.append(rel_dict)

                    neighbor_id = (
                        rel["target_entity_id"]
                        if rel["source_entity_id"] == eid
                        else rel["source_entity_id"]
                    )
                    if neighbor_id not in visited_entities:
                        neighbor_row = get_graph_entity(conn, neighbor_id)
                        if neighbor_row:
                            visited_entities[neighbor_id] = _format_entity(neighbor_row)
                            next_frontier.add(neighbor_id)
            frontier = next_frontier

        return {
            "center": _format_entity(center),
            "entities": list(visited_entities.values()),
            "relationships": all_relationships,
            "depth": depth,
            "entity_count": len(visited_entities),
            "relationship_count": len(all_relationships),
        }
    finally:
        conn.close()


def search_entities(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Search entities by name substring."""
    conn = get_connection()
    try:
        rows = search_graph_entities(conn, query, entity_type, limit)
        return [_format_entity(row) for row in rows]
    finally:
        conn.close()


def get_entities(
    entity_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """List all entities, optionally filtered by type."""
    conn = get_connection()
    try:
        rows = list_graph_entities(conn, entity_type, limit)
        return [_format_entity(row) for row in rows]
    finally:
        conn.close()
