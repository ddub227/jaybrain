"""Tests for daemon startup hardening (Feature 1).

Validates stale lock cleanup, DB PID checks, and lifecycle logging
for the startup_refused event.
"""

import os
import sqlite3

import pytest


def _setup_db(data_dir):
    """Initialize a minimal DB with daemon tables."""
    from jaybrain.config import ensure_data_dirs
    from jaybrain.db import init_db

    ensure_data_dirs()
    init_db()


def _write_daemon_state(data_dir, pid, status="running"):
    """Write a daemon_state row for testing."""
    db_path = data_dir / "jaybrain.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daemon_state (
            id INTEGER PRIMARY KEY,
            pid INTEGER,
            started_at TEXT,
            last_heartbeat TEXT,
            modules TEXT DEFAULT '[]',
            status TEXT DEFAULT 'running'
        )
    """)
    conn.execute(
        "INSERT OR REPLACE INTO daemon_state (id, pid, started_at, last_heartbeat, status) "
        "VALUES (1, ?, '2026-01-01', '2026-01-01', ?)",
        (pid, status),
    )
    conn.commit()
    conn.close()


class TestCheckDbForAliveDaemon:
    def test_returns_none_when_no_db(self, temp_data_dir, monkeypatch):
        """No DB file should return None."""
        import sys
        sys.path.insert(0, str(temp_data_dir.parent.parent / "scripts"))
        from scripts.start_daemon import _check_db_for_alive_daemon

        result = _check_db_for_alive_daemon(temp_data_dir)
        assert result is None

    def test_returns_none_when_pid_is_dead(self, temp_data_dir, monkeypatch):
        """Dead PID in daemon_state should return None."""
        _setup_db(temp_data_dir)
        _write_daemon_state(temp_data_dir, 999999)  # PID that doesn't exist

        from scripts.start_daemon import _check_db_for_alive_daemon

        result = _check_db_for_alive_daemon(temp_data_dir)
        assert result is None

    def test_returns_pid_when_alive(self, temp_data_dir, monkeypatch):
        """Alive PID in daemon_state should be returned."""
        _setup_db(temp_data_dir)
        my_pid = os.getpid()
        _write_daemon_state(temp_data_dir, my_pid)

        from scripts.start_daemon import _check_db_for_alive_daemon

        result = _check_db_for_alive_daemon(temp_data_dir)
        assert result == my_pid

    def test_returns_none_when_status_stopped(self, temp_data_dir, monkeypatch):
        """Stopped daemon should return None even if PID is alive."""
        _setup_db(temp_data_dir)
        _write_daemon_state(temp_data_dir, os.getpid(), status="stopped")

        from scripts.start_daemon import _check_db_for_alive_daemon

        result = _check_db_for_alive_daemon(temp_data_dir)
        assert result is None


class TestStaleLockCleanup:
    def test_stale_lock_file_cleaned(self, temp_data_dir):
        """Lock file with dead PID should be removed."""
        from scripts.start_daemon import _is_pid_alive

        lock_file = temp_data_dir / "daemon.lock"
        lock_file.write_text("999999")  # Dead PID
        assert lock_file.exists()

        # Simulate the cleanup logic from run_foreground
        stale_pid_text = lock_file.read_text().strip()
        if stale_pid_text.isdigit():
            stale_pid = int(stale_pid_text)
            if not _is_pid_alive(stale_pid):
                lock_file.unlink(missing_ok=True)

        assert not lock_file.exists()

    def test_alive_lock_file_preserved(self, temp_data_dir):
        """Lock file with alive PID should NOT be removed."""
        from scripts.start_daemon import _is_pid_alive

        lock_file = temp_data_dir / "daemon.lock"
        lock_file.write_text(str(os.getpid()))  # Our own PID (alive)

        stale_pid_text = lock_file.read_text().strip()
        if stale_pid_text.isdigit():
            stale_pid = int(stale_pid_text)
            if not _is_pid_alive(stale_pid):
                lock_file.unlink(missing_ok=True)

        assert lock_file.exists()


class TestLogStartupRefused:
    def test_startup_refused_logged(self, temp_data_dir):
        """startup_refused event should appear in daemon_lifecycle_log."""
        _setup_db(temp_data_dir)

        from scripts.start_daemon import _log_startup_refused

        _log_startup_refused(temp_data_dir, 12345)

        db_path = temp_data_dir / "jaybrain.db"
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT * FROM daemon_lifecycle_log WHERE event_type = 'startup_refused'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_startup_refused_with_no_db(self, temp_data_dir):
        """Should not crash when no DB exists."""
        from scripts.start_daemon import _log_startup_refused

        # Should not raise
        _log_startup_refused(temp_data_dir, 12345)


class TestDaemonStartPreCheck:
    def test_start_refused_when_alive_pid(self, temp_data_dir):
        """DaemonManager.start() should return early if daemon_state has alive PID."""
        _setup_db(temp_data_dir)
        _write_daemon_state(temp_data_dir, os.getpid())  # Write our PID as "another" daemon

        from jaybrain.daemon import DaemonManager

        dm = DaemonManager()
        # Override PID so it sees "another" daemon (our PID) as rival
        dm._pid = 999999

        # start() should return early without starting scheduler
        dm.start()

        # Scheduler should NOT have been started
        assert not dm._running

    def test_start_proceeds_when_dead_pid(self, temp_data_dir, monkeypatch):
        """DaemonManager.start() should proceed if daemon_state PID is dead."""
        _setup_db(temp_data_dir)
        _write_daemon_state(temp_data_dir, 999999)  # Dead PID

        from jaybrain.daemon import DaemonManager

        dm = DaemonManager()

        # Mock scheduler.start to avoid blocking
        started = []
        monkeypatch.setattr(dm.scheduler, "start", lambda: started.append(True))

        dm.start()

        # Should have proceeded to start
        assert dm._running is True or len(started) > 0

    def test_start_proceeds_when_no_prior_daemon(self, temp_data_dir, monkeypatch):
        """DaemonManager.start() should proceed when daemon_state is empty."""
        _setup_db(temp_data_dir)

        from jaybrain.daemon import DaemonManager

        dm = DaemonManager()

        # Mock scheduler.start to avoid blocking
        started = []
        monkeypatch.setattr(dm.scheduler, "start", lambda: started.append(True))

        dm.start()

        assert dm._running is True or len(started) > 0
