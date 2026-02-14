"""Tests for the sessions module (lifecycle, handoff, orphan cleanup)."""

import pytest

from jaybrain.db import init_db, get_connection, insert_session, get_session
from jaybrain.config import ensure_data_dirs
import jaybrain.config as config
from jaybrain.sessions import (
    start_session,
    end_current_session,
    get_handoff,
    get_current_session_id,
    _persist_session_id,
    _load_session_id_from_disk,
)
import jaybrain.sessions as sessions_mod


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()
    # Reset module-level state between tests
    sessions_mod._current_session_id = None


class TestStartSession:
    def test_start_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = start_session("Test session")
        assert "session_id" in result
        assert result["title"] == "Test session"
        assert len(result["session_id"]) == 12

    def test_start_without_title(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = start_session()
        assert result["title"] == ""
        assert "session_id" in result

    def test_start_returns_previous_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        # Start and end a session
        r1 = start_session("First")
        end_current_session("Did stuff", ["decision1"], ["next1"])

        # Start a new session
        r2 = start_session("Second")
        assert r2["previous_session"] is not None
        assert r2["previous_session"]["title"] == "First"
        assert r2["previous_session"]["summary"] == "Did stuff"

    def test_start_closes_orphans(self, temp_data_dir):
        _setup_db(temp_data_dir)
        # Manually insert an orphaned session (started, never ended)
        conn = get_connection()
        insert_session(conn, "orphan123456", "Orphan session")
        conn.close()

        # Reset module state so it doesn't think orphan is current
        sessions_mod._current_session_id = None

        result = start_session("New session")
        assert "closed_orphans" in result
        assert "orphan123456" in result["closed_orphans"]

        # Verify the orphan was actually closed in DB
        conn = get_connection()
        row = get_session(conn, "orphan123456")
        conn.close()
        assert row["ended_at"] is not None


class TestEndSession:
    def test_end_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        start_session("To end")
        session = end_current_session(
            summary="Accomplished things",
            decisions_made=["decided X"],
            next_steps=["do Y"],
        )
        assert session is not None
        assert session.summary == "Accomplished things"
        assert session.decisions_made == ["decided X"]
        assert session.next_steps == ["do Y"]
        assert session.ended_at is not None

    def test_end_no_active_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = end_current_session("Nothing to end")
        assert result is None

    def test_end_creates_handoff_file(self, temp_data_dir):
        _setup_db(temp_data_dir)
        sessions_dir = sessions_mod.SESSIONS_DIR
        sessions_dir.mkdir(parents=True, exist_ok=True)
        start_session("Handoff test")
        end_current_session("Summary here")

        # Check that a handoff file was created
        handoff_files = list(sessions_dir.glob("handoff_*.md"))
        assert len(handoff_files) >= 1

        content = handoff_files[0].read_text(encoding="utf-8")
        assert "Summary here" in content
        assert "Handoff test" in content

    def test_end_clears_session_id(self, temp_data_dir):
        _setup_db(temp_data_dir)
        start_session("Clear me")
        assert get_current_session_id() is not None
        end_current_session("Done")
        # Module-level ID should be cleared
        assert sessions_mod._current_session_id is None


class TestGetHandoff:
    def test_no_sessions(self, temp_data_dir):
        _setup_db(temp_data_dir)
        assert get_handoff() is None

    def test_returns_latest_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        start_session("Session 1")
        end_current_session("First summary")

        handoff = get_handoff()
        assert handoff is not None
        assert handoff["summary"] == "First summary"
        assert handoff["is_active"] is False

    def test_returns_active_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        start_session("Active session")

        handoff = get_handoff()
        assert handoff is not None
        assert handoff["is_active"] is True


class TestSessionPersistence:
    def test_persist_and_load(self, temp_data_dir):
        _setup_db(temp_data_dir)
        _persist_session_id("abc123def456")
        loaded = _load_session_id_from_disk()
        assert loaded == "abc123def456"

    def test_persist_none_clears(self, temp_data_dir):
        _setup_db(temp_data_dir)
        _persist_session_id("abc123def456")
        _persist_session_id(None)
        loaded = _load_session_id_from_disk()
        assert loaded is None

    def test_load_from_disk_fallback(self, temp_data_dir):
        _setup_db(temp_data_dir)
        # Start a session, then clear the in-memory state
        result = start_session("Persistent")
        sid = result["session_id"]
        sessions_mod._current_session_id = None

        # Should recover from disk
        recovered = get_current_session_id()
        assert recovered == sid

    def test_stale_disk_file_cleaned(self, temp_data_dir):
        _setup_db(temp_data_dir)
        # Write a session ID to disk that's already ended in DB
        start_session("Ended")
        sid = sessions_mod._current_session_id
        end_current_session("Done")

        # Manually re-write stale ID to disk
        _persist_session_id(sid)
        sessions_mod._current_session_id = None

        # Should detect it's ended and clean up
        result = get_current_session_id()
        assert result is None


class TestGetCurrentSessionId:
    def test_returns_in_memory(self, temp_data_dir):
        _setup_db(temp_data_dir)
        start_session("In memory")
        sid = sessions_mod._current_session_id
        assert get_current_session_id() == sid

    def test_returns_none_when_no_session(self, temp_data_dir):
        _setup_db(temp_data_dir)
        assert get_current_session_id() is None
