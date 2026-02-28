"""Tests for the heartbeat notification module."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db, now_iso


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestForgeStudyCheck:
    def test_no_trigger_when_studied_and_few_due(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_forge_study_morning

        conn = get_connection()
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            now = now_iso()
            conn.execute(
                "INSERT INTO forge_streaks (date, concepts_reviewed, created_at) VALUES (?, 5, ?)",
                (today, now),
            )
            conn.commit()
        finally:
            conn.close()

        result = check_forge_study_morning()
        assert result["triggered"] is False
        assert result["studied_today"] is True

    def test_triggers_when_not_studied(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_forge_study_morning

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = check_forge_study_morning()

        assert result["triggered"] is True
        assert result["studied_today"] is False

    def test_triggers_when_many_due(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_forge_study_morning

        conn = get_connection()
        try:
            now = now_iso()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            # Add 10 concepts all due today
            for i in range(10):
                conn.execute(
                    """INSERT INTO forge_concepts
                    (id, term, definition, next_review, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (f"c{i}", f"term{i}", f"def{i}", today, now, now),
                )
            conn.commit()
        finally:
            conn.close()

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = check_forge_study_morning()

        assert result["triggered"] is True
        assert result["due_count"] >= 10


class TestExamCountdown:
    def test_no_trigger_when_far_away(self, temp_data_dir, monkeypatch):
        _setup_db()
        import jaybrain.heartbeat as hb
        far_date = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
        monkeypatch.setattr(hb, "SECURITY_PLUS_EXAM_DATE", far_date)

        result = hb.check_exam_countdown()
        assert result["triggered"] is False

    def test_triggers_within_14_days(self, temp_data_dir, monkeypatch):
        _setup_db()
        import jaybrain.heartbeat as hb
        near_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        monkeypatch.setattr(hb, "SECURITY_PLUS_EXAM_DATE", near_date)

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = hb.check_exam_countdown()

        assert result["triggered"] is True
        assert 6 <= result["days_left"] <= 7  # Allow for time-of-day rounding

    def test_exam_date_passed(self, temp_data_dir, monkeypatch):
        _setup_db()
        import jaybrain.heartbeat as hb
        past_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        monkeypatch.setattr(hb, "SECURITY_PLUS_EXAM_DATE", past_date)

        result = hb.check_exam_countdown()
        assert result["triggered"] is False


class TestStaleApplications:
    def test_no_stale_apps(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_stale_applications

        result = check_stale_applications()
        assert result["triggered"] is False
        assert result["stale_count"] == 0

    def test_stale_app_detected(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_stale_applications

        conn = get_connection()
        try:
            now = now_iso()
            old_date = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
            # Create job and application
            conn.execute(
                """INSERT INTO job_postings
                (id, title, company, created_at, updated_at)
                VALUES ('j1', 'SOC Analyst', 'SecureCo', ?, ?)""",
                (now, now),
            )
            conn.execute(
                """INSERT INTO applications
                (id, job_id, status, applied_date, created_at, updated_at)
                VALUES ('a1', 'j1', 'applied', ?, ?, ?)""",
                (old_date, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = check_stale_applications()

        assert result["triggered"] is True
        assert result["stale_count"] == 1
        assert "SecureCo" in result["message"]


class TestSessionCrash:
    def test_no_stalled_sessions(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_session_crash

        result = check_session_crash()
        assert result["triggered"] is False

    def test_stalled_session_detected(self, temp_data_dir, monkeypatch):
        _setup_db()
        import jaybrain.config as config
        monkeypatch.setattr(config, "HEARTBEAT_SESSION_CRASH_ENABLED", True)

        from jaybrain.heartbeat import check_session_crash

        conn = get_connection()
        try:
            old_heartbeat = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
            conn.executescript("""
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
            """)
            conn.execute(
                """INSERT INTO claude_sessions
                (session_id, cwd, started_at, last_heartbeat, status, tool_count)
                VALUES ('stalled-123', '/test', ?, ?, 'active', 50)""",
                (old_heartbeat, old_heartbeat),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = check_session_crash()

        assert result["triggered"] is True
        assert result["stalled_count"] == 1


class TestGoalStaleness:
    def test_no_stale_goals(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_goal_staleness

        result = check_goal_staleness()
        assert result["triggered"] is False

    def test_stale_goal_detected(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import check_goal_staleness

        conn = get_connection()
        try:
            now = now_iso()
            old_date = (datetime.now(timezone.utc) - timedelta(weeks=3)).isoformat()
            conn.execute(
                """INSERT INTO life_domains
                (id, name, priority, created_at, updated_at)
                VALUES ('d1', 'Career', 5, ?, ?)""",
                (now, now),
            )
            conn.execute(
                """INSERT INTO life_goals
                (id, domain_id, title, status, progress, created_at, updated_at)
                VALUES ('g1', 'd1', 'Get certified', 'active', 0.3, ?, ?)""",
                (old_date, old_date),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = check_goal_staleness()

        assert result["triggered"] is True
        assert result["stale_count"] == 1


class TestRateLimiting:
    def test_rate_limited_notification(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import _was_recently_notified, _log_check

        # Log a recent notification
        _log_check("test_check", True, "test", True)

        # Should be rate limited
        assert _was_recently_notified("test_check") is True

    def test_not_rate_limited_when_no_history(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import _was_recently_notified

        assert _was_recently_notified("never_sent") is False


class TestRunSingleCheck:
    def test_unknown_check(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import run_single_check

        result = run_single_check("nonexistent")
        assert "error" in result
        assert "Unknown check" in result["error"]

    def test_valid_check_name(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import run_single_check

        with patch("jaybrain.heartbeat.dispatch_notification", return_value=True):
            result = run_single_check("forge_study")

        # Should run without error
        assert "error" not in result


class TestHeartbeatStatus:
    def test_empty_status(self, temp_data_dir):
        _setup_db()
        from jaybrain.heartbeat import get_heartbeat_status

        result = get_heartbeat_status()
        assert result["checks"] == {}
        assert result["recent_log"] == []


class TestMigration10:
    def test_heartbeat_log_table_exists(self, temp_data_dir):
        _setup_db()

        conn = get_connection()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "heartbeat_log" in tables
        finally:
            conn.close()
