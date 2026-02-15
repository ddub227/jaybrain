"""Tests for knowledge graph: entities, relationships, and traversal."""

import json

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestAddEntity:
    def test_create_entity(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity
        result = add_entity("JayBrain", "project", description="Personal AI memory system")
        assert result["status"] == "created"
        assert result["entity"]["name"] == "JayBrain"
        assert result["entity"]["entity_type"] == "project"
        assert result["entity"]["description"] == "Personal AI memory system"

    def test_upsert_merges_existing(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity

        # First create
        add_entity("Python", "skill", aliases=["py"], properties={"version": "3.12"})

        # Second call should merge
        result = add_entity(
            "Python", "skill",
            aliases=["python3"],
            properties={"use": "backend"},
            source_memory_ids=["mem1"],
        )
        assert result["status"] == "updated"
        entity = result["entity"]
        assert "py" in entity["aliases"]
        assert "python3" in entity["aliases"]
        assert entity["properties"]["version"] == "3.12"
        assert entity["properties"]["use"] == "backend"
        assert "mem1" in entity["memory_ids"]

    def test_different_types_are_separate(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity

        r1 = add_entity("Python", "skill")
        r2 = add_entity("Python", "tool")
        assert r1["status"] == "created"
        assert r2["status"] == "created"
        assert r1["entity"]["id"] != r2["entity"]["id"]


class TestAddRelationship:
    def test_create_relationship(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship

        add_entity("JJ", "person")
        add_entity("Python", "skill")
        result = add_relationship("JJ", "Python", "knows", weight=0.9)

        assert result["status"] == "created"
        assert result["source"] == "JJ"
        assert result["target"] == "Python"
        assert result["rel_type"] == "knows"
        assert result["weight"] == 0.9

    def test_upsert_relationship(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship

        add_entity("JJ", "person")
        add_entity("SQLite", "tool")
        add_relationship("JJ", "SQLite", "uses", evidence_ids=["e1"])
        result = add_relationship("JJ", "SQLite", "uses", weight=0.8, evidence_ids=["e2"])

        assert result["status"] == "updated"
        assert result["weight"] == 0.8

    def test_relationship_missing_entity_returns_error(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship

        add_entity("JJ", "person")
        result = add_relationship("JJ", "NonExistent", "knows")
        assert "error" in result

    def test_resolve_entity_by_name(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship

        add_entity("JayBrain", "project")
        add_entity("MCP", "concept")
        result = add_relationship("JayBrain", "MCP", "uses")
        assert result["status"] == "created"
        assert result["source"] == "JayBrain"
        assert result["target"] == "MCP"


class TestQueryNeighborhood:
    def test_depth_1_traversal(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship, query_neighborhood

        add_entity("JJ", "person")
        add_entity("Python", "skill")
        add_entity("SQLite", "tool")
        add_relationship("JJ", "Python", "knows")
        add_relationship("JJ", "SQLite", "uses")

        result = query_neighborhood("JJ", depth=1)
        assert result["center"]["name"] == "JJ"
        assert result["entity_count"] == 3
        assert result["relationship_count"] == 2
        entity_names = {e["name"] for e in result["entities"]}
        assert entity_names == {"JJ", "Python", "SQLite"}

    def test_depth_2_traversal(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, add_relationship, query_neighborhood

        # JJ -> Python -> FastAPI
        add_entity("JJ", "person")
        add_entity("Python", "skill")
        add_entity("FastAPI", "tool")
        add_relationship("JJ", "Python", "knows")
        add_relationship("Python", "FastAPI", "related_to")

        # At depth 1, should only find JJ + Python
        r1 = query_neighborhood("JJ", depth=1)
        assert r1["entity_count"] == 2

        # At depth 2, should find all 3
        r2 = query_neighborhood("JJ", depth=2)
        assert r2["entity_count"] == 3
        entity_names = {e["name"] for e in r2["entities"]}
        assert "FastAPI" in entity_names

    def test_not_found(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import query_neighborhood
        result = query_neighborhood("Ghost")
        assert "error" in result

    def test_isolated_entity(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, query_neighborhood

        add_entity("Lonely", "concept")
        result = query_neighborhood("Lonely")
        assert result["entity_count"] == 1
        assert result["relationship_count"] == 0


class TestSearchEntities:
    def test_search_by_name(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, search_entities

        add_entity("JayBrain", "project")
        add_entity("JayHelper", "tool")
        add_entity("Python", "skill")

        results = search_entities("Jay")
        names = [e["name"] for e in results]
        assert "JayBrain" in names
        assert "JayHelper" in names
        assert "Python" not in names

    def test_search_by_type(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, search_entities

        add_entity("Python", "skill")
        add_entity("Python", "tool")
        add_entity("SQLite", "tool")

        results = search_entities("Python", entity_type="skill")
        assert len(results) == 1
        assert results[0]["entity_type"] == "skill"

    def test_search_no_results(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import search_entities
        results = search_entities("ZZZnonexistent")
        assert results == []


class TestGetEntities:
    def test_list_all(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, get_entities

        add_entity("A", "skill")
        add_entity("B", "tool")
        add_entity("C", "person")

        results = get_entities()
        assert len(results) == 3

    def test_list_by_type(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, get_entities

        add_entity("Python", "skill")
        add_entity("Rust", "skill")
        add_entity("SQLite", "tool")

        results = get_entities(entity_type="skill")
        assert len(results) == 2
        assert all(e["entity_type"] == "skill" for e in results)

    def test_list_empty(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import get_entities
        results = get_entities()
        assert results == []

    def test_list_respects_limit(self, temp_data_dir):
        _setup_db()
        from jaybrain.graph import add_entity, get_entities

        for i in range(5):
            add_entity(f"Entity{i}", "concept")

        results = get_entities(limit=3)
        assert len(results) == 3
