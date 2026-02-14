"""Tests for memory store, retrieve, and decay."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection, insert_memory, get_memories_batch
from jaybrain.memory import compute_decay, _fts5_safe_query, _write_memory_markdown, _parse_memory_row
from jaybrain.models import Memory, MemoryCategory


class TestComputeDecay:
    """Tests for SM-2 inspired exponential decay model."""

    def test_fresh_memory(self):
        now = datetime.now(timezone.utc)
        decay = compute_decay(now, importance=0.5, access_count=0, now=now)
        # Fresh memory: raw_decay=1.0, importance=0.5 -> 1.0 * (0.5 + 0.25) = 0.75
        assert decay == pytest.approx(0.75, abs=0.01)

    def test_fresh_memory_high_importance(self):
        now = datetime.now(timezone.utc)
        decay = compute_decay(now, importance=1.0, access_count=0, now=now)
        # importance=1.0 -> 1.0 * (0.5 + 0.5) = 1.0
        assert decay == pytest.approx(1.0, abs=0.01)

    def test_fresh_memory_low_importance(self):
        now = datetime.now(timezone.utc)
        decay = compute_decay(now, importance=0.0, access_count=0, now=now)
        # importance=0.0 -> 1.0 * (0.5 + 0.0) = 0.5
        assert decay == pytest.approx(0.5, abs=0.01)

    def test_half_life_decay(self):
        """At exactly one half-life, raw decay should be 0.5."""
        now = datetime.now(timezone.utc)
        at_half_life = now - timedelta(days=90)  # base half-life = 90 days
        decay = compute_decay(at_half_life, importance=1.0, access_count=0, now=now)
        # raw_decay=0.5, importance=1.0 -> 0.5 * 1.0 = 0.5
        assert decay == pytest.approx(0.5, abs=0.01)

    def test_old_memory_decays_below_linear(self):
        """At 180 days with no access, should be well below 0.5."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=180)
        decay = compute_decay(old, importance=0.5, access_count=0, now=now)
        # 180 days = 2 half-lives, raw_decay=0.25, * 0.75 = 0.1875
        assert decay == pytest.approx(0.1875, abs=0.02)

    def test_very_old_memory_floors(self):
        now = datetime.now(timezone.utc)
        ancient = now - timedelta(days=730)
        decay = compute_decay(ancient, importance=0.5, access_count=0, now=now)
        assert decay == pytest.approx(0.05, abs=0.02)

    def test_access_extends_half_life(self):
        """More accesses should result in slower decay."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=180)
        decay_no_access = compute_decay(old, importance=0.5, access_count=0, now=now)
        decay_with_access = compute_decay(old, importance=0.5, access_count=5, now=now)
        assert decay_with_access > decay_no_access

    def test_access_half_life_capped(self):
        """Half-life should be capped at DECAY_MAX_HALF_LIFE (730 days)."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=90)
        # 100 accesses: 90 + 100*30 = 3090, but capped at 730
        decay_100 = compute_decay(old, importance=0.5, access_count=100, now=now)
        # 22 accesses: 90 + 22*30 = 750, capped at 730 -- effectively same
        decay_22 = compute_decay(old, importance=0.5, access_count=22, now=now)
        assert decay_100 == pytest.approx(decay_22, abs=0.01)

    def test_recent_access_resets_decay_clock(self):
        """Accessing a memory recently should decay from that access time, not creation."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=365)
        recently_accessed = now - timedelta(days=5)
        decay_no_recent = compute_decay(old, importance=0.5, access_count=0, now=now)
        decay_recent = compute_decay(
            old, importance=0.5, access_count=1,
            last_accessed=recently_accessed, now=now,
        )
        # Recently accessed memory should have much higher score
        assert decay_recent > decay_no_recent * 2

    def test_importance_scales_result(self):
        """Higher importance should yield higher decay scores."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=90)
        decay_low = compute_decay(old, importance=0.0, access_count=0, now=now)
        decay_high = compute_decay(old, importance=1.0, access_count=0, now=now)
        assert decay_high > decay_low

    def test_min_decay_floor(self):
        """Decay should never go below MIN_DECAY (0.05)."""
        now = datetime.now(timezone.utc)
        ancient = now - timedelta(days=5000)
        decay = compute_decay(ancient, importance=0.0, access_count=0, now=now)
        assert decay >= 0.05


class TestFts5SafeQuery:
    def test_simple_query(self):
        assert _fts5_safe_query("hello world") == '"hello" "world"'

    def test_special_characters(self):
        result = _fts5_safe_query("AND OR NOT -test")
        assert '"AND"' in result
        assert '"test"' in result

    def test_empty_query(self):
        assert _fts5_safe_query("") == ""

    def test_punctuation_stripped(self):
        result = _fts5_safe_query("hello, world!")
        assert '"hello"' in result
        assert '"world"' in result


class TestDatabaseOperations:
    def test_init_db(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            # Verify tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            assert "memories" in table_names
            assert "tasks" in table_names
            assert "sessions" in table_names
            assert "knowledge" in table_names
        finally:
            conn.close()

    def test_memories_has_session_id_column(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            assert "session_id" in columns
        finally:
            conn.close()

    def test_indexes_exist(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {row["name"] for row in indexes}
            assert "idx_memories_category" in index_names
            assert "idx_memories_created_at" in index_names
            assert "idx_memories_importance" in index_names
            assert "idx_memories_session_id" in index_names
            assert "idx_knowledge_category" in index_names
            assert "idx_knowledge_created_at" in index_names
        finally:
            conn.close()

    def test_insert_and_get_memory(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(conn, "test123", "Hello world", "semantic", ["test"], 0.5)
            from jaybrain.db import get_memory
            row = get_memory(conn, "test123")
            assert row is not None
            assert row["content"] == "Hello world"
            assert row["category"] == "semantic"
        finally:
            conn.close()

    def test_insert_memory_with_session_id(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(
                conn, "sess1", "Session memory", "semantic", [], 0.5,
                session_id="session-abc",
            )
            from jaybrain.db import get_memory
            row = get_memory(conn, "sess1")
            assert row is not None
            assert row["session_id"] == "session-abc"
        finally:
            conn.close()

    def test_delete_memory(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(conn, "del123", "To delete", "semantic", [], 0.5)
            from jaybrain.db import delete_memory, get_memory
            assert delete_memory(conn, "del123")
            assert get_memory(conn, "del123") is None
        finally:
            conn.close()

    def test_fts_search(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(conn, "fts1", "Python is a great programming language", "semantic", ["python"], 0.5)
            insert_memory(conn, "fts2", "JavaScript runs in the browser", "semantic", ["js"], 0.5)
            from jaybrain.db import search_memories_fts
            results = search_memories_fts(conn, '"Python"')
            ids = [r[0] for r in results]
            assert "fts1" in ids
        finally:
            conn.close()

    def test_batch_fetch_memories(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(conn, "b1", "First memory", "semantic", [], 0.5)
            insert_memory(conn, "b2", "Second memory", "semantic", [], 0.7)
            insert_memory(conn, "b3", "Third memory", "episodic", [], 0.3)

            result = get_memories_batch(conn, ["b1", "b2", "b3"])
            assert len(result) == 3
            assert result["b1"]["content"] == "First memory"
            assert result["b2"]["importance"] == 0.7
            assert result["b3"]["category"] == "episodic"
        finally:
            conn.close()

    def test_batch_fetch_empty(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            result = get_memories_batch(conn, [])
            assert result == {}
        finally:
            conn.close()

    def test_batch_fetch_missing_ids(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            insert_memory(conn, "exists", "I exist", "semantic", [], 0.5)
            result = get_memories_batch(conn, ["exists", "nope"])
            assert len(result) == 1
            assert "exists" in result
            assert "nope" not in result
        finally:
            conn.close()
