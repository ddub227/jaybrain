"""Tests for the pulse module (cross-session awareness)."""

import pytest

from jaybrain.db import init_db, get_connection, now_iso
from jaybrain.config import ensure_data_dirs
from jaybrain.pulse import (
    get_active_sessions,
    get_session_activity,
    query_session,
    _minutes_since,
    _has_pulse_tables,
)


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


PULSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS claude_sessions (
    session_id TEXT PRIMARY KEY,
    cwd TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT NOT NULL DEFAULT '',
    tool_count INTEGER NOT NULL DEFAULT 0,
    last_tool TEXT NOT NULL DEFAULT '',
    last_tool_input TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    tool_input_summary TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
"""


def _create_pulse_tables(conn):
    """Create the Pulse tables that normally the hook script creates."""
    conn.executescript(PULSE_SCHEMA)
    conn.commit()


def _insert_session(conn, session_id, cwd="/home/test", status="active",
                     description="", tool_count=0, last_tool="", last_tool_input=""):
    now = now_iso()
    conn.execute(
        """INSERT INTO claude_sessions
        (session_id, cwd, started_at, last_heartbeat, status, description,
         tool_count, last_tool, last_tool_input)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, cwd, now, now, status, description,
         tool_count, last_tool, last_tool_input),
    )
    conn.commit()


def _insert_activity(conn, session_id, event_type, tool_name="", tool_input_summary=""):
    conn.execute(
        """INSERT INTO session_activity_log
        (session_id, event_type, tool_name, tool_input_summary, timestamp)
        VALUES (?, ?, ?, ?, ?)""",
        (session_id, event_type, tool_name, tool_input_summary, now_iso()),
    )
    conn.commit()


class TestMinutesSince:
    def test_recent_timestamp(self):
        now = now_iso()
        mins = _minutes_since(now)
        assert 0 <= mins < 1

    def test_invalid_timestamp(self):
        assert _minutes_since("not-a-date") == -1

    def test_none(self):
        assert _minutes_since(None) == -1


class TestHasPulseTables:
    def test_no_tables(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        assert _has_pulse_tables(conn) is False
        conn.close()

    def test_with_tables(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        assert _has_pulse_tables(conn) is True
        conn.close()


class TestGetActiveSessions:
    def test_no_pulse_tables(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = get_active_sessions()
        assert result["status"] == "no_data"

    def test_no_sessions(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        conn.close()

        result = get_active_sessions()
        assert result["status"] == "ok"
        assert result["active_count"] == 0

    def test_active_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "sess-abc123", cwd="/project/foo",
                        last_tool="Read", tool_count=5)
        conn.close()

        result = get_active_sessions()
        assert result["active_count"] == 1
        session = result["active_sessions"][0]
        assert session["session_id"] == "sess-abc123"
        assert session["cwd"] == "/project/foo"
        assert session["last_tool"] == "Read"
        assert session["tool_count"] == 5

    def test_ended_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "sess-ended", status="ended")
        conn.close()

        result = get_active_sessions()
        assert result["active_count"] == 0
        assert len(result["recently_ended"]) == 1

    def test_mixed_sessions(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "active-1", status="active")
        _insert_session(conn, "active-2", status="active")
        _insert_session(conn, "ended-1", status="ended")
        conn.close()

        result = get_active_sessions()
        assert result["active_count"] == 2
        assert len(result["recently_ended"]) == 1


class TestGetSessionActivity:
    def test_no_pulse_tables(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = get_session_activity()
        assert result["status"] == "no_data"

    def test_empty_activity(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        conn.close()

        result = get_session_activity()
        assert result["status"] == "ok"
        assert result["count"] == 0

    def test_activity_all_sessions(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_activity(conn, "s1", "PostToolUse", "Read", "file.py")
        _insert_activity(conn, "s2", "PostToolUse", "Write", "output.py")
        conn.close()

        result = get_session_activity()
        assert result["count"] == 2

    def test_activity_filtered_by_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_activity(conn, "s1", "PostToolUse", "Read")
        _insert_activity(conn, "s2", "PostToolUse", "Write")
        conn.close()

        result = get_session_activity(session_id="s1")
        assert result["count"] == 1
        assert result["activities"][0]["session_id"] == "s1"

    def test_activity_limit(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        for i in range(10):
            _insert_activity(conn, "s1", "PostToolUse", f"Tool{i}")
        conn.close()

        result = get_session_activity(limit=3)
        assert result["count"] == 3


class TestQuerySession:
    def test_no_pulse_tables(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = query_session("anything")
        assert result["status"] == "no_data"

    def test_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        conn.close()

        result = query_session("nonexistent")
        assert result["status"] == "not_found"

    def test_exact_match(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "sess-exact-match", cwd="/proj")
        _insert_activity(conn, "sess-exact-match", "PostToolUse", "Read")
        _insert_activity(conn, "sess-exact-match", "PostToolUse", "Read")
        _insert_activity(conn, "sess-exact-match", "PostToolUse", "Write")
        conn.close()

        result = query_session("sess-exact-match")
        assert result["status"] == "ok"
        assert result["session"]["session_id"] == "sess-exact-match"
        assert result["tool_usage"]["Read"] == 2
        assert result["tool_usage"]["Write"] == 1

    def test_partial_match(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "sess-abc123def456")
        conn.close()

        result = query_session("abc123")
        assert result["status"] == "ok"
        assert result["session"]["session_id"] == "sess-abc123def456"

    def test_ambiguous_match(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_pulse_tables(conn)
        _insert_session(conn, "sess-abc-1")
        _insert_session(conn, "sess-abc-2")
        conn.close()

        result = query_session("abc")
        assert result["status"] == "ambiguous"
        assert len(result["matches"]) == 2
