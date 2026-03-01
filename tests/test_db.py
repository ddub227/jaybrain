"""Tests for the db module (schema, CRUD, serialization)."""

import json
import struct
import pytest

from jaybrain.db import (
    init_db,
    get_connection,
    now_iso,
    _serialize_f32,
    _deserialize_f32,
    _validate_fields,
    # Memory CRUD
    insert_memory,
    get_memory,
    delete_memory,
    get_memories_batch,
    update_memory_access,
    get_all_memories,
    # Task CRUD
    insert_task,
    get_task,
    update_task,
    list_tasks,
    # Session CRUD
    insert_session,
    end_session,
    get_session,
    get_latest_session,
    get_open_sessions,
    # Knowledge CRUD
    insert_knowledge,
    get_knowledge,
    update_knowledge,
    # Queue CRUD
    get_queue_tasks,
    get_next_queue_task,
    get_max_queue_position,
    set_queue_position,
    clear_queue_position,
    shift_queue_positions,
    reindex_queue,
    # Stats
    get_stats,
)
from jaybrain.config import ensure_data_dirs


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


class TestSerialization:
    def test_serialize_deserialize_f32(self):
        original = [1.0, 2.5, -3.14, 0.0]
        serialized = _serialize_f32(original)
        assert isinstance(serialized, bytes)
        assert len(serialized) == 4 * len(original)

        result = _deserialize_f32(serialized)
        assert len(result) == len(original)
        for a, b in zip(original, result):
            assert abs(a - b) < 1e-5

    def test_serialize_empty(self):
        assert _serialize_f32([]) == b""
        assert _deserialize_f32(b"") == []


class TestValidateFields:
    """Tests for column allowlist enforcement (SEC-1)."""

    def test_allows_valid_task_fields(self):
        _validate_fields("tasks", {"title": "new", "status": "done"})

    def test_allows_valid_knowledge_fields(self):
        _validate_fields("knowledge", {"title": "t", "content": "c", "category": "ref"})

    def test_rejects_id_column(self):
        with pytest.raises(ValueError, match="Invalid column"):
            _validate_fields("tasks", {"id": "injected", "title": "test"})

    def test_rejects_created_at(self):
        with pytest.raises(ValueError, match="Invalid column"):
            _validate_fields("tasks", {"created_at": "2024-01-01"})

    def test_rejects_unknown_column(self):
        with pytest.raises(ValueError, match="Invalid column"):
            _validate_fields("tasks", {"drop_table": "yes"})

    def test_rejects_sql_injection_column(self):
        with pytest.raises(ValueError, match="Invalid column"):
            _validate_fields("tasks", {"title = 'x'; DROP TABLE tasks; --": "val"})

    def test_rejects_unknown_table(self):
        with pytest.raises(ValueError, match="No column allowlist"):
            _validate_fields("nonexistent_table", {"anything": "val"})

    def test_empty_fields_passes(self):
        _validate_fields("tasks", {})

    def test_all_tables_have_allowlists(self):
        from jaybrain.db import _UPDATABLE_COLUMNS
        expected_tables = {
            "tasks", "knowledge", "forge_concepts", "job_boards",
            "applications", "graph_entities", "graph_relationships",
            "telegram_bot_state", "cram_topics", "news_feed_sources",
            "signalforge_articles", "signalforge_clusters",
            "signalforge_synthesis",
        }
        assert set(_UPDATABLE_COLUMNS.keys()) == expected_tables

    def test_integration_update_task_rejects_bad_column(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        try:
            insert_task(conn, "t1", "Test Task", "", "todo", "medium", "", [], None)
            with pytest.raises(ValueError, match="Invalid column"):
                update_task(conn, "t1", id="injected_id")
        finally:
            conn.close()

    def test_integration_update_task_accepts_valid_column(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        try:
            insert_task(conn, "t1", "Test Task", "", "todo", "medium", "", [], None)
            result = update_task(conn, "t1", status="done")
            assert result is True
            row = get_task(conn, "t1")
            assert row["status"] == "done"
        finally:
            conn.close()


class TestConnection:
    def test_get_connection(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert conn is not None
        # Verify WAL mode
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_init_db_creates_tables(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {row[0] for row in tables}
        assert "memories" in table_names
        assert "tasks" in table_names
        assert "sessions" in table_names
        assert "knowledge" in table_names
        assert "forge_concepts" in table_names
        assert "job_postings" in table_names
        assert "applications" in table_names
        assert "graph_entities" in table_names
        assert "graph_relationships" in table_names
        conn.close()

    def test_init_db_idempotent(self, temp_data_dir):
        _setup(temp_data_dir)
        # Calling init_db again should not raise
        init_db()
        conn = get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) > 0
        conn.close()


class TestMemoryCRUD:
    def test_insert_and_get(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "mem1", "Test content", "semantic", ["tag1"], 0.8)
        row = get_memory(conn, "mem1")
        assert row is not None
        assert row["content"] == "Test content"
        assert row["category"] == "semantic"
        assert row["importance"] == 0.8
        assert json.loads(row["tags"]) == ["tag1"]
        conn.close()

    def test_get_nonexistent(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert get_memory(conn, "doesntexist") is None
        conn.close()

    def test_delete(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "mem_del", "Delete me", "semantic", [], 0.5)
        assert delete_memory(conn, "mem_del") is True
        assert get_memory(conn, "mem_del") is None
        conn.close()

    def test_delete_nonexistent(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert delete_memory(conn, "nope") is False
        conn.close()

    def test_batch_get(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "b1", "One", "semantic", [], 0.5)
        insert_memory(conn, "b2", "Two", "semantic", [], 0.5)
        insert_memory(conn, "b3", "Three", "semantic", [], 0.5)

        result = get_memories_batch(conn, ["b1", "b3"])
        assert len(result) == 2
        assert "b1" in result
        assert "b3" in result
        assert "b2" not in result
        conn.close()

    def test_batch_get_empty(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert get_memories_batch(conn, []) == {}
        conn.close()

    def test_update_access(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "access_mem", "Content", "semantic", [], 0.5)
        update_memory_access(conn, "access_mem")
        update_memory_access(conn, "access_mem")

        row = get_memory(conn, "access_mem")
        assert row["access_count"] == 2
        assert row["last_accessed"] is not None
        conn.close()

    def test_get_all_memories(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "m1", "Semantic", "semantic", [], 0.5)
        insert_memory(conn, "m2", "Episodic", "episodic", [], 0.5)
        insert_memory(conn, "m3", "Semantic 2", "semantic", [], 0.5)

        all_mems = get_all_memories(conn)
        assert len(all_mems) == 3

        semantic_only = get_all_memories(conn, category="semantic")
        assert len(semantic_only) == 2
        conn.close()


class TestTaskCRUD:
    def test_insert_and_get(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "t1", "My task", "Description", "todo", "medium", "proj", ["tag"], None)
        row = get_task(conn, "t1")
        assert row is not None
        assert row["title"] == "My task"
        assert row["status"] == "todo"
        assert row["priority"] == "medium"
        assert row["project"] == "proj"
        conn.close()

    def test_update_task(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "t_up", "Original", "", "todo", "low", "", [], None)
        assert update_task(conn, "t_up", title="Changed", status="in_progress") is True
        row = get_task(conn, "t_up")
        assert row["title"] == "Changed"
        assert row["status"] == "in_progress"
        conn.close()

    def test_update_nonexistent(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert update_task(conn, "nope", title="X") is False
        conn.close()

    def test_update_empty_fields(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert update_task(conn, "whatever") is False
        conn.close()

    def test_list_tasks_filters(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "f1", "Task A", "", "todo", "high", "alpha", [], None)
        insert_task(conn, "f2", "Task B", "", "done", "low", "beta", [], None)
        insert_task(conn, "f3", "Task C", "", "todo", "high", "alpha", [], None)

        todo = list_tasks(conn, status="todo")
        assert len(todo) == 2

        alpha = list_tasks(conn, project="alpha")
        assert len(alpha) == 2

        high_alpha = list_tasks(conn, status="todo", priority="high", project="alpha")
        assert len(high_alpha) == 2

        limited = list_tasks(conn, limit=1)
        assert len(limited) == 1
        conn.close()


class TestSessionCRUD:
    def test_insert_and_get(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_session(conn, "s1", "Session 1")
        row = get_session(conn, "s1")
        assert row is not None
        assert row["title"] == "Session 1"
        assert row["ended_at"] is None
        conn.close()

    def test_end_session(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_session(conn, "s_end", "To end")
        assert end_session(conn, "s_end", "Summary", ["d1"], ["n1"]) is True
        row = get_session(conn, "s_end")
        assert row["ended_at"] is not None
        assert row["summary"] == "Summary"
        assert json.loads(row["decisions_made"]) == ["d1"]
        assert json.loads(row["next_steps"]) == ["n1"]
        conn.close()

    def test_get_latest(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_session(conn, "old", "Old session")
        import time
        time.sleep(0.05)  # Ensure different timestamps
        insert_session(conn, "new", "New session")
        latest = get_latest_session(conn)
        assert latest["id"] == "new"
        conn.close()

    def test_get_open_sessions(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_session(conn, "open1", "Open")
        insert_session(conn, "open2", "Also open")
        insert_session(conn, "closed", "Closed")
        end_session(conn, "closed", "Done", [], [])

        open_sessions = get_open_sessions(conn)
        open_ids = [r["id"] for r in open_sessions]
        assert "open1" in open_ids
        assert "open2" in open_ids
        assert "closed" not in open_ids
        conn.close()


class TestKnowledgeCRUD:
    def test_insert_and_get(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_knowledge(conn, "k1", "Python GIL", "The GIL limits threading", "python", ["python"], "docs")
        row = get_knowledge(conn, "k1")
        assert row is not None
        assert row["title"] == "Python GIL"
        assert row["content"] == "The GIL limits threading"
        conn.close()

    def test_update(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_knowledge(conn, "k_up", "Title", "Content", "general", [], "")
        assert update_knowledge(conn, "k_up", title="New Title", content="New Content") is True
        row = get_knowledge(conn, "k_up")
        assert row["title"] == "New Title"
        assert row["content"] == "New Content"
        conn.close()

    def test_update_nonexistent(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert update_knowledge(conn, "nope", title="X") is False
        conn.close()


class TestQueueCRUD:
    def test_empty_queue(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        assert get_queue_tasks(conn) == []
        assert get_next_queue_task(conn) is None
        assert get_max_queue_position(conn) == 0
        conn.close()

    def test_set_and_get_position(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "qt1", "Queued", "", "todo", "medium", "", [], None)
        set_queue_position(conn, "qt1", 1)
        row = get_task(conn, "qt1")
        assert row["queue_position"] == 1

        next_task = get_next_queue_task(conn)
        assert next_task["id"] == "qt1"
        conn.close()

    def test_clear_position(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "qt_clr", "Clear me", "", "todo", "medium", "", [], None)
        set_queue_position(conn, "qt_clr", 1)
        clear_queue_position(conn, "qt_clr")

        row = get_task(conn, "qt_clr")
        assert row["queue_position"] is None
        assert get_next_queue_task(conn) is None
        conn.close()

    def test_shift_positions(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "sh1", "A", "", "todo", "medium", "", [], None)
        insert_task(conn, "sh2", "B", "", "todo", "medium", "", [], None)
        set_queue_position(conn, "sh1", 1)
        set_queue_position(conn, "sh2", 2)

        shift_queue_positions(conn, 1, delta=1)

        r1 = get_task(conn, "sh1")
        r2 = get_task(conn, "sh2")
        assert r1["queue_position"] == 2
        assert r2["queue_position"] == 3
        conn.close()

    def test_reindex(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "ri1", "A", "", "todo", "medium", "", [], None)
        insert_task(conn, "ri2", "B", "", "todo", "medium", "", [], None)
        set_queue_position(conn, "ri1", 3)
        set_queue_position(conn, "ri2", 7)

        reindex_queue(conn)

        r1 = get_task(conn, "ri1")
        r2 = get_task(conn, "ri2")
        assert r1["queue_position"] == 1
        assert r2["queue_position"] == 2
        conn.close()

    def test_done_tasks_excluded(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_task(conn, "active", "Active", "", "todo", "medium", "", [], None)
        insert_task(conn, "done", "Done", "", "done", "medium", "", [], None)
        set_queue_position(conn, "active", 1)
        set_queue_position(conn, "done", 2)

        queue = get_queue_tasks(conn)
        assert len(queue) == 1
        assert queue[0]["id"] == "active"
        conn.close()


class TestStats:
    def test_stats_empty_db(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        stats = get_stats(conn)
        assert stats["memory_count"] == 0
        assert stats["task_count"] == 0
        assert stats["session_count"] == 0
        assert stats["knowledge_count"] == 0
        assert stats["active_tasks"] == 0
        conn.close()

    def test_stats_with_data(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = get_connection()
        insert_memory(conn, "s_m1", "Mem", "semantic", [], 0.5)
        insert_memory(conn, "s_m2", "Mem2", "episodic", [], 0.5)
        insert_task(conn, "s_t1", "Task", "", "todo", "medium", "", [], None)
        insert_task(conn, "s_t2", "Task2", "", "done", "medium", "", [], None)
        insert_session(conn, "s_s1", "Session")
        insert_knowledge(conn, "s_k1", "K", "Content", "general", [], "")

        stats = get_stats(conn)
        assert stats["memory_count"] == 2
        assert stats["task_count"] == 2
        assert stats["active_tasks"] == 1
        assert stats["session_count"] == 1
        assert stats["knowledge_count"] == 1
        assert stats["memories_by_category"]["semantic"] == 1
        assert stats["memories_by_category"]["episodic"] == 1
        conn.close()


class TestMigrations:
    def test_migrations_idempotent(self, temp_data_dir):
        _setup(temp_data_dir)
        # Running init_db multiple times should not error
        init_db()
        init_db()
        conn = get_connection()
        # Verify migrated columns exist
        task_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        assert "queue_position" in task_cols
        conn.close()
