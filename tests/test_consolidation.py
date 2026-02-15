"""Tests for memory consolidation: clustering, deduplication, merging, archival."""

import json
import struct
from datetime import datetime, timezone

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import (
    init_db,
    get_connection,
    insert_memory,
    get_memory,
    get_memories_batch,
    _serialize_f32,
)


def _make_embedding(seed: float, dim: int = 384) -> list[float]:
    """Create a deterministic unit-ish embedding from a seed value."""
    import math
    vec = [math.sin(seed + i * 0.1) for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


def _similar_embedding(base: list[float], noise: float = 0.02) -> list[float]:
    """Create an embedding very similar to base with slight noise."""
    import math
    vec = [v + noise * math.sin(i) for i, v in enumerate(base)]
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestFindClusters:
    def test_clusters_found_for_similar_memories(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            base = _make_embedding(1.0)
            insert_memory(conn, "c1", "Python is great for ML", "semantic", ["python"], 0.5, embedding=base)
            insert_memory(conn, "c2", "Python works well for machine learning", "semantic", ["python"], 0.5, embedding=_similar_embedding(base, 0.01))
            insert_memory(conn, "c3", "Python excels at ML tasks", "semantic", ["python"], 0.5, embedding=_similar_embedding(base, 0.015))
            # Dissimilar memory
            different = _make_embedding(100.0)
            insert_memory(conn, "c4", "SQL databases use tables", "semantic", ["sql"], 0.5, embedding=different)
        finally:
            conn.close()

        from jaybrain.consolidation import find_clusters
        clusters = find_clusters(min_similarity=0.95)
        assert len(clusters) >= 1
        # The 3 similar memories should cluster together
        biggest = clusters[0]
        assert biggest["memory_count"] >= 2
        cluster_ids = [m["id"] for m in biggest["memories"]]
        assert "c4" not in cluster_ids

    def test_no_clusters_for_dissimilar_memories(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            for i in range(3):
                emb = _make_embedding(float(i * 50))
                insert_memory(conn, f"d{i}", f"Topic {i}", "semantic", [], 0.5, embedding=emb)
        finally:
            conn.close()

        from jaybrain.consolidation import find_clusters
        clusters = find_clusters(min_similarity=0.99)
        assert len(clusters) == 0

    def test_empty_memories(self, temp_data_dir):
        _setup_db()
        from jaybrain.consolidation import find_clusters
        clusters = find_clusters()
        assert clusters == []

    def test_single_memory(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "only1", "Solo memory", "semantic", [], 0.5, embedding=_make_embedding(1.0))
        finally:
            conn.close()

        from jaybrain.consolidation import find_clusters
        clusters = find_clusters()
        assert clusters == []


class TestFindDuplicates:
    def test_finds_near_duplicates(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            base = _make_embedding(5.0)
            insert_memory(conn, "dup1", "JayBrain uses SQLite for storage", "semantic", [], 0.5, embedding=base)
            insert_memory(conn, "dup2", "JayBrain uses SQLite for storage", "semantic", [], 0.5, embedding=_similar_embedding(base, 0.005))
            # Different memory
            insert_memory(conn, "dup3", "Completely different topic", "semantic", [], 0.5, embedding=_make_embedding(200.0))
        finally:
            conn.close()

        from jaybrain.consolidation import find_duplicates
        pairs = find_duplicates(threshold=0.95)
        assert len(pairs) >= 1
        pair = pairs[0]
        assert pair["similarity"] >= 0.95
        pair_ids = {pair["memory_a"]["id"], pair["memory_b"]["id"]}
        assert pair_ids == {"dup1", "dup2"}

    def test_no_duplicates_when_dissimilar(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            for i in range(3):
                insert_memory(conn, f"nd{i}", f"Unique topic {i}", "semantic", [], 0.5, embedding=_make_embedding(float(i * 100)))
        finally:
            conn.close()

        from jaybrain.consolidation import find_duplicates
        pairs = find_duplicates(threshold=0.99)
        assert len(pairs) == 0


class TestMergeMemories:
    def test_merge_creates_new_and_archives_originals(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "m1", "Python is great", "semantic", ["python"], 0.5)
            insert_memory(conn, "m2", "Python is excellent", "semantic", ["coding"], 0.7)
        finally:
            conn.close()

        from jaybrain.consolidation import merge_memories
        result = merge_memories(
            ["m1", "m2"],
            merged_content="Python is an excellent programming language",
            reason="test merge",
        )

        assert result["status"] == "merged"
        assert result["archived_count"] == 2
        assert "new_memory_id" in result
        assert result["importance"] == 0.7  # max of originals

        # Verify originals are gone from live table
        conn = get_connection()
        try:
            assert get_memory(conn, "m1") is None
            assert get_memory(conn, "m2") is None
            # Verify new memory exists
            new = get_memory(conn, result["new_memory_id"])
            assert new is not None
            assert new["content"] == "Python is an excellent programming language"
            # Verify originals are in archive
            archived = conn.execute("SELECT COUNT(*) FROM memory_archive").fetchone()[0]
            assert archived == 2
        finally:
            conn.close()

    def test_merge_auto_combines_tags(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "t1", "Memory one", "semantic", ["alpha", "beta"], 0.5)
            insert_memory(conn, "t2", "Memory two", "semantic", ["beta", "gamma"], 0.5)
        finally:
            conn.close()

        from jaybrain.consolidation import merge_memories
        result = merge_memories(["t1", "t2"], merged_content="Combined memory")

        conn = get_connection()
        try:
            new = get_memory(conn, result["new_memory_id"])
            tags = json.loads(new["tags"])
            assert "alpha" in tags
            assert "beta" in tags
            assert "gamma" in tags
        finally:
            conn.close()

    def test_merge_missing_ids_returns_error(self, temp_data_dir):
        _setup_db()
        from jaybrain.consolidation import merge_memories
        result = merge_memories(["nonexistent1", "nonexistent2"], merged_content="test")
        assert "error" in result

    def test_merge_logs_action(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "log1", "First", "semantic", [], 0.5)
            insert_memory(conn, "log2", "Second", "semantic", [], 0.5)
        finally:
            conn.close()

        from jaybrain.consolidation import merge_memories
        result = merge_memories(["log1", "log2"], merged_content="Merged", reason="test")

        conn = get_connection()
        try:
            logs = conn.execute("SELECT * FROM consolidation_log").fetchall()
            assert len(logs) == 1
            log = logs[0]
            assert log["action"] == "merge"
            assert result["new_memory_id"] == log["result_memory_id"]
            source_ids = json.loads(log["source_memory_ids"])
            assert set(source_ids) == {"log1", "log2"}
        finally:
            conn.close()


class TestArchiveMemories:
    def test_archive_removes_from_search(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "a1", "Archive me", "semantic", [], 0.5)
            insert_memory(conn, "a2", "Keep me", "semantic", [], 0.5)
        finally:
            conn.close()

        from jaybrain.consolidation import archive_memories
        result = archive_memories(["a1"], reason="test_cleanup")

        assert result["status"] == "archived"
        assert "a1" in result["archived"]

        conn = get_connection()
        try:
            assert get_memory(conn, "a1") is None
            assert get_memory(conn, "a2") is not None
            # Check archive table
            archived = conn.execute(
                "SELECT * FROM memory_archive WHERE id = ?", ("a1",)
            ).fetchone()
            assert archived is not None
            assert archived["archive_reason"] == "test_cleanup"
        finally:
            conn.close()

    def test_archive_nonexistent_returns_not_found(self, temp_data_dir):
        _setup_db()
        from jaybrain.consolidation import archive_memories
        result = archive_memories(["ghost"], reason="cleanup")
        assert result["not_found"] == ["ghost"]
        assert result["archived"] == []


class TestConsolidationStats:
    def test_stats_with_activity(self, temp_data_dir):
        _setup_db()
        conn = get_connection()
        try:
            insert_memory(conn, "s1", "Active memory", "semantic", [], 0.5)
            insert_memory(conn, "s2", "To archive", "semantic", [], 0.5)
        finally:
            conn.close()

        from jaybrain.consolidation import archive_memories, get_consolidation_stats
        archive_memories(["s2"], reason="stats_test")
        stats = get_consolidation_stats()

        assert stats["active_memories"] == 1
        assert stats["archived_memories"] == 1
        assert stats["total_consolidation_runs"] >= 1
        assert "archive" in stats["actions_by_type"]

    def test_stats_empty(self, temp_data_dir):
        _setup_db()
        from jaybrain.consolidation import get_consolidation_stats
        stats = get_consolidation_stats()
        assert stats["active_memories"] == 0
        assert stats["archived_memories"] == 0
