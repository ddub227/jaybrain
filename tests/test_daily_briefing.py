"""Tests for the daily_briefing module (data collectors and HTML builder).

Tests the pure logic functions; external services (Gmail, Sheets) are not tested.
"""

import pytest
import sqlite3
from datetime import date, timedelta

from jaybrain.db import init_db, get_connection, insert_task, insert_job_posting, insert_application
from jaybrain.db import insert_forge_concept, upsert_forge_streak
from jaybrain.config import ensure_data_dirs
from jaybrain.daily_briefing import (
    collect_tasks,
    collect_job_pipeline,
    collect_forge_stats,
    collect_upcoming_deadlines,
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
