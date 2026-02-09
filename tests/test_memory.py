"""Tests for memory store, retrieve, and decay."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection, insert_memory
from jaybrain.memory import compute_decay, _fts5_safe_query, _write_memory_markdown, _parse_memory_row
from jaybrain.models import Memory, MemoryCategory


class TestComputeDecay:
    def test_fresh_memory(self):
        now = datetime.now(timezone.utc)
        decay = compute_decay(now, access_count=0, now=now)
        assert decay == pytest.approx(1.0, abs=0.01)

    def test_old_memory_decays(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=180)
        decay = compute_decay(old, access_count=0, now=now)
        # 180/365 ~ 0.49 decay, so remaining ~0.51
        assert 0.4 < decay < 0.6

    def test_very_old_memory_floors(self):
        now = datetime.now(timezone.utc)
        ancient = now - timedelta(days=730)
        decay = compute_decay(ancient, access_count=0, now=now)
        assert decay == pytest.approx(0.1, abs=0.01)

    def test_access_reinforcement(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=180)
        decay_no_access = compute_decay(old, access_count=0, now=now)
        decay_with_access = compute_decay(old, access_count=5, now=now)
        assert decay_with_access > decay_no_access

    def test_access_reinforcement_capped(self):
        now = datetime.now(timezone.utc)
        decay_8 = compute_decay(now, access_count=8, now=now)
        decay_100 = compute_decay(now, access_count=100, now=now)
        assert decay_8 == pytest.approx(decay_100, abs=0.01)

    def test_recency_boost(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=180)
        recently_accessed = now - timedelta(days=5)
        decay_no_recent = compute_decay(old, access_count=0, now=now)
        decay_recent = compute_decay(old, access_count=0, last_accessed=recently_accessed, now=now)
        assert decay_recent > decay_no_recent


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
