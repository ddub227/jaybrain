"""Tests for the JayBrain daemon module."""

import json
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db


class TestDaemonManager:
    def _setup_db(self):
        ensure_data_dirs()
        init_db()

    def test_register_module(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager
        from apscheduler.triggers.interval import IntervalTrigger

        dm = DaemonManager()
        mock_func = MagicMock()
        dm.register_module(
            "test_module",
            mock_func,
            IntervalTrigger(seconds=60),
            "A test module",
        )
        assert "test_module" in dm.modules
        assert len(dm.modules) == 1

    def test_register_multiple_modules(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        dm = DaemonManager()
        dm.register_module("mod_a", MagicMock(), IntervalTrigger(seconds=30), "Module A")
        dm.register_module("mod_b", MagicMock(), CronTrigger(hour=2), "Module B")
        assert sorted(dm.modules) == ["mod_a", "mod_b"]

    def test_write_heartbeat(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager

        dm = DaemonManager()
        dm._write_heartbeat()

        # Verify heartbeat was written to DB
        conn = sqlite3.connect(str(temp_data_dir / "jaybrain.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        conn.close()

        assert row is not None
        assert row["status"] == "running"
        assert row["pid"] == os.getpid()

    def test_write_status(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager

        dm = DaemonManager()
        dm._write_status("stopped")

        conn = sqlite3.connect(str(temp_data_dir / "jaybrain.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        conn.close()

        assert row["status"] == "stopped"

    def test_heartbeat_updates_modules_list(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager
        from apscheduler.triggers.interval import IntervalTrigger

        dm = DaemonManager()
        dm.register_module("archive", MagicMock(), IntervalTrigger(seconds=60))
        dm._write_heartbeat()

        conn = sqlite3.connect(str(temp_data_dir / "jaybrain.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        conn.close()

        modules = json.loads(row["modules"])
        assert "archive" in modules


class TestDaemonStatus:
    def _setup_db(self):
        ensure_data_dirs()
        init_db()

    def test_status_when_no_daemon(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import get_daemon_status

        status = get_daemon_status()
        assert status["status"] == "stopped"
        assert status["pid"] is None

    def test_status_with_running_daemon(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import DaemonManager, get_daemon_status

        dm = DaemonManager()
        dm._write_status("running")

        status = get_daemon_status()
        # PID is current process so it should be alive
        assert status["status"] == "running"
        assert status["pid"] == os.getpid()
        assert status["process_alive"] is True

    def test_status_with_dead_pid(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import get_daemon_status

        # Write a fake PID that doesn't exist
        conn = sqlite3.connect(str(temp_data_dir / "jaybrain.db"))
        conn.execute("""
            INSERT INTO daemon_state (id, pid, started_at, last_heartbeat, modules, status)
            VALUES (1, 999999, '2024-01-01T00:00:00', '2024-01-01T00:00:00', '[]', 'running')
        """)
        conn.commit()
        conn.close()

        status = get_daemon_status()
        # Dead PID should show as stopped
        assert status["status"] == "stopped"
        assert status["process_alive"] is False


class TestDaemonControl:
    def _setup_db(self):
        ensure_data_dirs()
        init_db()

    def test_stop_when_not_running(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import daemon_control

        result = daemon_control("stop")
        assert result["status"] == "not_running"

    def test_unknown_action(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import daemon_control

        result = daemon_control("invalid")
        assert result["status"] == "error"
        assert "Unknown action" in result["message"]


class TestBuildDaemon:
    def _setup_db(self):
        ensure_data_dirs()
        init_db()

    def test_build_daemon_creates_manager(self, temp_data_dir):
        self._setup_db()
        from jaybrain.daemon import build_daemon

        dm = build_daemon()
        # Should return a DaemonManager even if no modules loaded
        assert dm is not None
        assert isinstance(dm.modules, list)


class TestMigration7:
    def _setup_db(self):
        ensure_data_dirs()
        init_db()

    def test_daemon_state_table_exists(self, temp_data_dir):
        self._setup_db()
        from jaybrain.db import get_connection

        conn = get_connection()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "daemon_state" in tables
        finally:
            conn.close()

    def test_daemon_state_single_row_constraint(self, temp_data_dir):
        self._setup_db()
        from jaybrain.db import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO daemon_state (id, status) VALUES (1, 'stopped')"
            )
            conn.commit()
            # Second row with id != 1 should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO daemon_state (id, status) VALUES (2, 'stopped')"
                )
        finally:
            conn.close()
