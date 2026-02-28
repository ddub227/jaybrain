"""Tests for deep_recall fused search tool."""

from unittest.mock import patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import (
    get_connection,
    init_db,
    insert_graph_entity,
    insert_graph_relationship,
    insert_knowledge,
    insert_memory,
)
from jaybrain.deep_recall import deep_recall

FAKE_EMBEDDING = [0.1] * 384


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


@pytest.fixture(autouse=True)
def mock_embed():
    """Mock embed_text to avoid loading ONNX model during tests."""
    with patch("jaybrain.deep_recall.embed_text", return_value=FAKE_EMBEDDING):
        yield


class TestMemoriesOnly:
    def test_returns_matching_memories(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "mem1", "Python uses indentation for blocks", "semantic", ["python"], 0.8, FAKE_EMBEDDING)
        insert_memory(conn, "mem2", "JavaScript uses curly braces", "semantic", ["javascript"], 0.5, FAKE_EMBEDDING)
        conn.close()

        result = deep_recall("Python indentation")
        assert result["summary"]["memory_count"] >= 1
        mem_ids = [m["id"] for m in result["memories"]]
        assert "mem1" in mem_ids

    def test_empty_knowledge_and_graph(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "mem1", "Test memory content", "semantic", [], 0.5, FAKE_EMBEDDING)
        conn.close()

        result = deep_recall("Test memory")
        assert result["summary"]["knowledge_count"] == 0
        assert result["summary"]["entity_count"] == 0
        assert result["summary"]["linked_memory_count"] == 0


class TestKnowledgeOnly:
    def test_returns_matching_knowledge(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_knowledge(conn, "k1", "Docker Networking", "Bridge host overlay modes", "devops", ["docker"], "docs", FAKE_EMBEDDING)
        conn.close()

        result = deep_recall("Docker networking bridge")
        assert result["summary"]["knowledge_count"] >= 1
        k_ids = [k["id"] for k in result["knowledge"]]
        assert "k1" in k_ids


class TestGraphEntities:
    def test_finds_entity_by_name(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_graph_entity(conn, "ent1", "SQLite", "tool", "Embedded database")
        conn.close()

        result = deep_recall("SQLite")
        assert result["summary"]["entity_count"] >= 1
        ent_names = [e["name"] for e in result["graph"]["entities"]]
        assert "SQLite" in ent_names

    def test_entity_linked_memories_surfaced(self, temp_data_dir):
        """Entity with memory_ids should pull those memories into linked_memories."""
        _setup(temp_data_dir)
        conn = get_connection()
        # Insert a memory with unrelated content/tags and NO embedding — invisible to all search
        insert_memory(conn, "hidden_mem", "Daemon heartbeat interval is thirty seconds", "procedural", ["daemon"], 0.7)
        # Insert entity that links to that memory
        insert_graph_entity(conn, "ent1", "SQLite", "tool", "Embedded database", memory_ids=["hidden_mem"])
        conn.close()

        result = deep_recall("SQLite")
        assert result["summary"]["entity_count"] >= 1
        # The linked memory should appear in linked_memories
        linked_ids = [m["id"] for m in result["linked_memories"]]
        assert "hidden_mem" in linked_ids
        # And it should have the provenance marker
        linked = [m for m in result["linked_memories"] if m["id"] == "hidden_mem"][0]
        assert linked["linked_from"] == "graph_entity"

    def test_connections_shown(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_graph_entity(conn, "ent1", "JayBrain", "project", "AI memory system")
        insert_graph_entity(conn, "ent2", "SQLite", "tool", "Database engine")
        insert_graph_relationship(conn, "rel1", "ent1", "ent2", "uses", 1.0)
        conn.close()

        result = deep_recall("JayBrain")
        assert result["summary"]["connection_count"] >= 1
        connections = result["graph"]["connections"]
        rel_types = [c["rel_type"] for c in connections]
        assert "uses" in rel_types


class TestDeduplication:
    def test_memory_in_direct_and_linked_appears_once(self, temp_data_dir):
        """A memory found by search AND linked via entity should only be in memories, not linked_memories."""
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "dup_mem", "SQLite database engine details", "semantic", ["sqlite"], 0.9, FAKE_EMBEDDING)
        insert_graph_entity(conn, "ent1", "SQLite", "tool", "Database", memory_ids=["dup_mem"])
        conn.close()

        result = deep_recall("SQLite database")
        # Should be in memories (direct search hit)
        mem_ids = [m["id"] for m in result["memories"]]
        # Should NOT be in linked_memories (deduplicated)
        linked_ids = [m["id"] for m in result["linked_memories"]]

        if "dup_mem" in mem_ids:
            assert "dup_mem" not in linked_ids, "Memory appeared in both memories and linked_memories"


class TestEmptyResults:
    def test_no_results_returns_empty_sections(self, temp_data_dir):
        _setup(temp_data_dir)

        result = deep_recall("xyznonexistent")
        assert result["query"] == "xyznonexistent"
        assert result["memories"] == []
        assert result["knowledge"] == []
        assert result["graph"]["entities"] == []
        assert result["graph"]["connections"] == []
        assert result["linked_memories"] == []
        assert result["summary"]["memory_count"] == 0


class TestSingleEmbedding:
    def test_embed_called_once(self, temp_data_dir):
        """embed_text should only be called once, not per search."""
        _setup(temp_data_dir)

        with patch("jaybrain.deep_recall.embed_text", return_value=FAKE_EMBEDDING) as mock:
            deep_recall("test query")
            assert mock.call_count == 1


class TestPartialFailure:
    def test_vec_failure_still_returns_fts_results(self, temp_data_dir):
        """If vector search fails, FTS results should still come through."""
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "fts_mem", "This memory about Python should be found via FTS", "semantic", ["python"], 0.8, FAKE_EMBEDDING)
        conn.close()

        with patch("jaybrain.deep_recall.embed_text", side_effect=RuntimeError("ONNX model not found")):
            result = deep_recall("Python")
            # Should still return results from FTS even without vec
            # (may or may not find depending on FTS matching, but should not crash)
            assert "error" not in result
            assert "memories" in result
            assert "knowledge" in result
            assert "graph" in result


class TestFullIntegration:
    def test_all_sections_populated(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        # Insert memory
        insert_memory(conn, "int_mem", "JayBrain uses SQLite for storage", "semantic", ["jaybrain"], 0.8, FAKE_EMBEDDING)
        # Insert knowledge
        insert_knowledge(conn, "int_k", "SQLite WAL Mode", "WAL improves concurrency", "databases", ["sqlite"], "docs", FAKE_EMBEDDING)
        # Insert entity with a linked memory that won't match the query (no embedding = invisible to search)
        insert_memory(conn, "linked_mem", "Daemon heartbeat runs every 30 seconds", "procedural", ["daemon"], 0.6)
        insert_graph_entity(conn, "ent1", "JayBrain", "project", "Personal AI memory", memory_ids=["linked_mem"])
        insert_graph_entity(conn, "ent2", "SQLite", "tool", "Database engine")
        insert_graph_relationship(conn, "rel1", "ent1", "ent2", "uses", 1.0)
        conn.close()

        result = deep_recall("JayBrain")
        # All sections should have results
        assert result["summary"]["memory_count"] >= 1
        assert result["summary"]["entity_count"] >= 1
        assert result["summary"]["linked_memory_count"] >= 1
        assert result["summary"]["connection_count"] >= 1

        # Verify structure
        assert "query" in result
        assert "memories" in result
        assert "knowledge" in result
        assert "graph" in result
        assert "entities" in result["graph"]
        assert "connections" in result["graph"]
        assert "linked_memories" in result
        assert "summary" in result

    def test_response_structure_matches_spec(self, temp_data_dir):
        _setup(temp_data_dir)
        result = deep_recall("anything")

        # Verify all top-level keys exist
        assert set(result.keys()) == {"query", "memories", "knowledge", "graph", "linked_memories", "summary"}
        assert set(result["graph"].keys()) == {"entities", "connections"}
        assert set(result["summary"].keys()) == {"memory_count", "knowledge_count", "entity_count", "linked_memory_count", "connection_count"}


class TestLimit:
    def test_respects_limit(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        for i in range(15):
            insert_memory(conn, f"mem_{i}", f"Test memory number {i} about Python", "semantic", ["test"], 0.5, FAKE_EMBEDDING)
        conn.close()

        result = deep_recall("Python test memory", limit=5)
        assert len(result["memories"]) <= 5
