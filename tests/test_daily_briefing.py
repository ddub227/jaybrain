"""Tests for the daily_briefing module (data collectors, HTML builder, Telegram formatter).

Tests the pure logic functions; external services (Gmail, Sheets, Telegram) are not tested.
"""

import pytest
import sqlite3
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from jaybrain.db import init_db, get_connection, insert_task, insert_job_posting, insert_application
from jaybrain.db import insert_forge_concept, upsert_forge_streak
from jaybrain.config import ensure_data_dirs
from jaybrain.daily_briefing import (
    collect_tasks,
    collect_job_pipeline,
    collect_forge_stats,
    collect_upcoming_deadlines,
    collect_time_allocation,
    format_telegram_briefing,
    build_email_html,
    _badge,
    _section_header,
)


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


def _get_plain_conn(temp_data_dir):
    """Get a plain sqlite3 connection (no sqlite-vec) like daily_briefing uses."""
    import jaybrain.config as config
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


class TestCollectTasks:
    def test_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = _get_plain_conn(temp_data_dir)
        result = collect_tasks(conn)
        assert result["tasks"] == []
        assert result["overdue_count"] == 0
        conn.close()

    def test_with_tasks(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn_rw = get_connection()
        insert_task(conn_rw, "t1", "High task", "", "todo", "high", "proj", [], None)
        insert_task(conn_rw, "t2", "Low task", "", "todo", "low", "", [], None)
        insert_task(conn_rw, "t3", "Done task", "", "done", "medium", "", [], None)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_tasks(conn)
        # Only active tasks (todo/in_progress/blocked)
        assert len(result["tasks"]) == 2
        # High priority should come first
        assert result["tasks"][0]["priority"] == "high"
        conn.close()

    def test_overdue_count(self, temp_data_dir):
        _setup_db(temp_data_dir)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        conn_rw = get_connection()
        insert_task(conn_rw, "overdue", "Overdue", "", "todo", "high", "", [], yesterday)
        insert_task(conn_rw, "future", "Future", "", "todo", "low", "", [], tomorrow)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_tasks(conn)
        assert result["overdue_count"] == 1
        conn.close()


class TestCollectJobPipeline:
    def test_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = _get_plain_conn(temp_data_dir)
        result = collect_job_pipeline(conn)
        assert result["pipeline"] == {}
        assert result["active_apps"] == []
        conn.close()

    def test_with_applications(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn_rw = get_connection()
        insert_job_posting(
            conn_rw, "j1", "Dev", "Acme", "", "", [], [],
            None, None, "full_time", "remote", "", None, [],
        )
        insert_application(conn_rw, "a1", "j1", "discovered", "", [])
        insert_application(conn_rw, "a2", "j1", "applied", "", [])
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_job_pipeline(conn)
        assert result["pipeline"]["discovered"] == 1
        assert result["pipeline"]["applied"] == 1
        assert len(result["active_apps"]) == 2
        conn.close()


class TestCollectForgeStats:
    def test_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = _get_plain_conn(temp_data_dir)
        result = collect_forge_stats(conn)
        assert result["total_concepts"] == 0
        assert result["due_count"] == 0
        assert result["avg_mastery"] == 0.0
        conn.close()

    def test_with_concepts(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn_rw = get_connection()
        insert_forge_concept(conn_rw, "c1", "Python", "A language", "python", "beginner", [])
        insert_forge_concept(conn_rw, "c2", "SQL", "Query language", "databases", "intermediate", [])
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_forge_stats(conn)
        assert result["total_concepts"] == 2
        assert result["avg_mastery"] == 0.0  # both start at 0
        conn.close()

    def test_streak_calculation(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn_rw = get_connection()
        # Create a 3-day streak ending today
        today = date.today()
        for i in range(3):
            d = (today - timedelta(days=i)).isoformat()
            upsert_forge_streak(conn_rw, d, concepts_reviewed=5)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_forge_stats(conn)
        assert result["current_streak"] == 3
        conn.close()


class TestCollectUpcomingDeadlines:
    def test_no_deadlines(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = _get_plain_conn(temp_data_dir)
        result = collect_upcoming_deadlines(conn)
        assert result == []
        conn.close()

    def test_upcoming_deadline(self, temp_data_dir):
        _setup_db(temp_data_dir)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        conn_rw = get_connection()
        insert_task(conn_rw, "dl1", "Due soon", "", "todo", "high", "proj", [], tomorrow)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_upcoming_deadlines(conn)
        assert len(result) == 1
        assert result[0]["title"] == "Due soon"
        assert result[0]["overdue"] is False
        conn.close()

    def test_overdue_deadline(self, temp_data_dir):
        _setup_db(temp_data_dir)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        conn_rw = get_connection()
        insert_task(conn_rw, "dl2", "Overdue", "", "todo", "critical", "", [], yesterday)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_upcoming_deadlines(conn)
        assert len(result) == 1
        assert result[0]["overdue"] is True
        conn.close()

    def test_done_tasks_excluded(self, temp_data_dir):
        _setup_db(temp_data_dir)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        conn_rw = get_connection()
        insert_task(conn_rw, "done_dl", "Done", "", "done", "high", "", [], tomorrow)
        conn_rw.close()

        conn = _get_plain_conn(temp_data_dir)
        result = collect_upcoming_deadlines(conn)
        assert len(result) == 0
        conn.close()


class TestHtmlBuilder:
    def test_badge(self):
        html = _badge("HIGH", "#ff0000")
        assert "HIGH" in html
        assert "#ff0000" in html

    def test_section_header(self):
        html = _section_header("My Section")
        assert "My Section" in html

    def test_build_email_html(self):
        html = build_email_html(
            tasks_data={"tasks": [], "overdue_count": 0},
            pipeline_data={"pipeline": {}, "active_apps": []},
            sheets_pipeline=[],
            networking_data={"items": [], "action_needed": []},
            forge_data={
                "total_concepts": 0, "due_count": 0, "avg_mastery": 0.0,
                "mastery_distribution": {}, "current_streak": 0,
                "total_reviews": 0, "subjects": [],
            },
            deadlines=[],
        )
        assert "JayBrain Daily Briefing" in html
        assert "<!DOCTYPE html>" in html
        assert "Active Tasks" in html

    def test_build_email_with_data(self):
        html = build_email_html(
            tasks_data={
                "tasks": [{"title": "Fix bug", "status": "todo", "priority": "high",
                           "project": "jaybrain", "due_date": "", "description": ""}],
                "overdue_count": 0,
            },
            pipeline_data={"pipeline": {"applied": 2}, "active_apps": [
                {"title": "Dev", "company": "Acme", "status": "applied",
                 "work_mode": "remote", "applied_date": "2026-02-14", "url": ""},
            ]},
            sheets_pipeline=[],
            networking_data={"items": [], "action_needed": []},
            forge_data={
                "total_concepts": 10, "due_count": 3, "avg_mastery": 0.45,
                "mastery_distribution": {"Spark (0-20%)": 2, "Flame (40-60%)": 8},
                "current_streak": 5, "total_reviews": 50, "subjects": [],
            },
            deadlines=[],
        )
        assert "Fix bug" in html
        assert "Acme" in html
        assert "SynapseForge" in html


# ---------------------------------------------------------------------------
# Telegram formatter tests
# ---------------------------------------------------------------------------

# Minimal data fixtures for format_telegram_briefing
EMPTY_TASKS = {"tasks": [], "overdue_count": 0}
EMPTY_PIPELINE = {"pipeline": {}, "active_apps": []}
EMPTY_FORGE = {
    "total_concepts": 0, "due_count": 0, "avg_mastery": 0.0,
    "mastery_distribution": {}, "current_streak": 0,
    "total_reviews": 0, "subjects": [],
}


class TestFormatTelegramBriefing:
    def test_header_always_present(self):
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [])
        assert "JayBrain Daily Briefing" in msg

    def test_empty_sections_omitted(self):
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [])
        assert "TASKS" not in msg
        assert "JOB PIPELINE" not in msg
        assert "SYNAPSEFORGE" not in msg
        assert "CALENDAR" not in msg

    def test_tasks_section(self):
        tasks_data = {
            "tasks": [
                {"title": "Fix auth bug", "status": "todo", "priority": "critical",
                 "project": "jaybrain", "due_date": "", "description": ""},
                {"title": "Write docs", "status": "todo", "priority": "low",
                 "project": "", "due_date": "", "description": ""},
            ],
            "overdue_count": 0,
        }
        msg = format_telegram_briefing(tasks_data, EMPTY_PIPELINE, EMPTY_FORGE, [])
        assert "TASKS (2 active)" in msg
        assert "[critical] Fix auth bug" in msg
        assert "[low] Write docs" in msg

    def test_tasks_with_overdue(self):
        tasks_data = {
            "tasks": [{"title": "Late", "status": "todo", "priority": "high",
                       "project": "", "due_date": "2026-02-01", "description": ""}],
            "overdue_count": 1,
        }
        msg = format_telegram_briefing(tasks_data, EMPTY_PIPELINE, EMPTY_FORGE, [])
        assert "1 overdue" in msg

    def test_deadlines_section(self):
        deadlines = [
            {"title": "Tax filing", "due_date": "2026-02-28", "priority": "high",
             "project": "", "status": "todo", "overdue": False},
            {"title": "Old task", "due_date": "2026-02-15", "priority": "critical",
             "project": "", "status": "todo", "overdue": True},
        ]
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, deadlines)
        assert "DEADLINES" in msg
        assert "Tax filing (2026-02-28)" in msg
        assert "[OVERDUE] Old task" in msg

    def test_time_allocation_section(self):
        time_data = {
            "domains": [
                {"name": "JayBrain Development (HOBBY / ONGOING)", "actual_hours": 9.1,
                 "target_hours": 7.5, "pct": 121.0, "status": "on_track"},
                {"name": "Learning -- CompTIA Security+", "actual_hours": 1.9,
                 "target_hours": 15.0, "pct": 13.0, "status": "under"},
            ],
            "total_actual": 11.0,
            "total_target": 22.5,
            "period_days": 7,
            "sessions_analyzed": 10,
        }
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [], time_data=time_data)
        assert "TIME ALLOCATION" in msg
        assert "JayBrain Development: 9.1h / 7.5h" in msg
        assert "<< under" in msg
        assert "Total: 11.0h / 22.5h" in msg

    def test_calendar_section(self):
        cal = {
            "events": [
                {"summary": "Team standup", "start": "2026-02-24T09:00:00-05:00",
                 "end": "2026-02-24T09:30:00-05:00", "location": "", "all_day": False},
                {"summary": "Holiday", "start": "2026-02-24", "end": "2026-02-25",
                 "location": "", "all_day": True},
            ],
            "count": 2,
        }
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [], calendar_data=cal)
        assert "CALENDAR (2 events)" in msg
        assert "Team standup" in msg
        assert "[All day] Holiday" in msg

    def test_forge_section(self):
        forge = {
            "total_concepts": 50, "due_count": 8, "avg_mastery": 0.55,
            "mastery_distribution": {}, "current_streak": 3,
            "total_reviews": 200, "subjects": [],
        }
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, forge, [])
        assert "SYNAPSEFORGE" in msg
        assert "50 concepts" in msg
        assert "8 due" in msg
        assert "Streak: 3d" in msg

    def test_job_pipeline_section(self):
        pipeline = {
            "pipeline": {"applied": 2, "interviewing": 1},
            "active_apps": [
                {"title": "Dev", "company": "Acme", "status": "applied",
                 "work_mode": "remote", "applied_date": "2026-02-14", "url": ""},
            ],
        }
        msg = format_telegram_briefing(EMPTY_TASKS, pipeline, EMPTY_FORGE, [])
        assert "JOB PIPELINE" in msg
        assert "2 applied" in msg
        assert "Acme" in msg

    def test_homelab_section(self):
        homelab = {
            "past_entries": [{"date": "2026-02-22", "title": "Kerberoasting"}],
            "next_steps": ["Golden Ticket simulation"],
            "quick_stats": {},
            "in_progress_skills": [],
            "planned_queue": [],
        }
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [], homelab_data=homelab)
        assert "HOMELAB" in msg
        assert "Kerberoasting" in msg
        assert "Golden Ticket" in msg

    def test_exam_countdown(self):
        """Exam countdown appears when <=14 days away."""
        forge = {"total_concepts": 10, "due_count": 5, "avg_mastery": 0.62,
                 "mastery_distribution": {}, "current_streak": 1,
                 "total_reviews": 50, "subjects": []}

        with patch("jaybrain.config.SECURITY_PLUS_EXAM_DATE", "2026-02-28"):
            # The function reads SECURITY_PLUS_EXAM_DATE from .config at call time
            msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, forge, [])

        assert "EXAM COUNTDOWN" in msg
        assert "Security+" in msg

    def test_life_domains_section(self):
        domains = {
            "domains": [
                {"name": "Career -- Break Into Tech", "active_goal_count": 3, "progress": 0.25},
                {"name": "Learning -- Security+", "active_goal_count": 2, "progress": 0.4},
            ],
        }
        msg = format_telegram_briefing(EMPTY_TASKS, EMPTY_PIPELINE, EMPTY_FORGE, [], domains_data=domains)
        assert "LIFE DOMAINS" in msg
        assert "Career (3 goals, 25%)" in msg

    def test_message_under_4096(self):
        """Full briefing with all sections should stay under Telegram limit."""
        tasks_data = {
            "tasks": [{"title": f"Task {i}", "status": "todo", "priority": "medium",
                       "project": "", "due_date": "", "description": ""} for i in range(10)],
            "overdue_count": 2,
        }
        time_data = {
            "domains": [
                {"name": f"Domain {i}", "actual_hours": float(i), "target_hours": 10.0,
                 "pct": float(i * 10), "status": "on_track"} for i in range(8)
            ],
            "total_actual": 36.0, "total_target": 80.0, "period_days": 7, "sessions_analyzed": 20,
        }
        msg = format_telegram_briefing(
            tasks_data=tasks_data,
            pipeline_data={"pipeline": {"applied": 3}, "active_apps": []},
            forge_data={"total_concepts": 100, "due_count": 15, "avg_mastery": 0.55,
                        "mastery_distribution": {}, "current_streak": 7,
                        "total_reviews": 500, "subjects": []},
            deadlines=[{"title": f"Deadline {i}", "due_date": "2026-03-01",
                        "priority": "high", "project": "", "status": "todo",
                        "overdue": False} for i in range(5)],
            time_data=time_data,
        )
        assert len(msg) < 4096


class TestCollectTimeAllocation:
    def test_returns_dict(self):
        """collect_time_allocation returns a dict even on error."""
        with patch("jaybrain.time_allocation.get_weekly_report", side_effect=Exception("boom")):
            result = collect_time_allocation()
        assert "error" in result

    def test_returns_report(self):
        mock_report = {"domains": [], "total_actual": 5.0, "total_target": 20.0}
        with patch("jaybrain.time_allocation.get_weekly_report", return_value=mock_report):
            result = collect_time_allocation()
        assert result["total_actual"] == 5.0


class TestRunTelegramBriefing:
    def test_sends_message(self):
        """run_telegram_briefing collects data and sends via Telegram."""
        from jaybrain.daily_briefing import run_telegram_briefing

        with patch("jaybrain.daily_briefing._get_db_connection", return_value=None), \
             patch("jaybrain.daily_briefing._get_google_credentials", return_value=None), \
             patch("jaybrain.daily_briefing.collect_homelab", return_value={"error": "skip"}), \
             patch("jaybrain.daily_briefing.collect_time_allocation", return_value={"domains": []}), \
             patch("jaybrain.telegram.send_telegram_message") as mock_send:
            mock_send.return_value = {"status": "sent", "chunks": 1}
            result = run_telegram_briefing()

        assert result["status"] == "sent"
        mock_send.assert_called_once()
        # Verify the message was passed
        msg = mock_send.call_args[0][0]
        assert "JayBrain Daily Briefing" in msg
