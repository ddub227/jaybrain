"""Tests for the cleanup module (auto-close sessions on exit)."""

import pytest

from jaybrain.db import init_db, get_connection, insert_session, get_session
from jaybrain.config import ensure_data_dirs
from jaybrain.cleanup import cleanup_session
import jaybrain.cleanup as cleanup_mod


def _setup_db(temp_data_dir, monkeypatch):
    ensure_data_dirs()
    init_db()
    # Patch the module-level imports
    import jaybrain.config as config
    monkeypatch.setattr(cleanup_mod, "ACTIVE_SESSION_FILE", config.ACTIVE_SESSION_FILE)


class TestCleanupSession:
    def test_no_active_session(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir, monkeypatch)
        # Ensure stdin looks like a tty (no hook input)
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
        # Should not raise
        cleanup_session()

    def test_closes_active_session(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir, monkeypatch)
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())

        import jaybrain.config as config

        # Create a session and write its ID to disk
        conn = get_connection()
        insert_session(conn, "cleanup_test1", "Test session")
        conn.close()
        config.ACTIVE_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.ACTIVE_SESSION_FILE.write_text("cleanup_test1", encoding="utf-8")

        cleanup_session()

        # Session should be closed
        conn = get_connection()
        row = get_session(conn, "cleanup_test1")
        conn.close()
        assert row["ended_at"] is not None
        assert "[Auto-closed by Stop hook]" in row["summary"]

        # Active session file should be removed
        assert not config.ACTIVE_SESSION_FILE.exists()

    def test_stale_session_file_cleaned(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir, monkeypatch)
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())

        import jaybrain.config as config

        # Write a session ID that doesn't exist in DB
        config.ACTIVE_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.ACTIVE_SESSION_FILE.write_text("nonexistent_id", encoding="utf-8")

        cleanup_session()

        # File should be cleaned up
        assert not config.ACTIVE_SESSION_FILE.exists()

    def test_already_closed_session(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir, monkeypatch)
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())

        import jaybrain.config as config
        from jaybrain.db import end_session

        # Create and immediately close a session
        conn = get_connection()
        insert_session(conn, "already_done", "Done")
        end_session(conn, "already_done", "Done", [], [])
        conn.close()

        # Write its ID to the active file (stale)
        config.ACTIVE_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.ACTIVE_SESSION_FILE.write_text("already_done", encoding="utf-8")

        cleanup_session()

        # Should clean up the stale file without error
        assert not config.ACTIVE_SESSION_FILE.exists()
