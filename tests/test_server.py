"""Tests for server tool logic (testing underlying modules directly)."""

import json

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db


@pytest.fixture(autouse=True)
def setup_db(temp_data_dir):
    """Ensure DB is initialized for each test."""
    ensure_data_dirs()
    init_db()


class TestProfileTools:
    def test_profile_get(self):
        from jaybrain.profile import get_profile
        profile = get_profile()
        assert "name" in profile
        assert profile["name"] == "Joshua"

    def test_profile_update(self):
        from jaybrain.profile import update_profile, get_profile
        update_profile("preferences", "editor", "vscode")
        profile = get_profile()
        assert profile["preferences"]["editor"] == "vscode"


class TestTaskTools:
    def test_task_create(self):
        from jaybrain.tasks import create_task
        task = create_task("Test task", priority="high", project="jaybrain")
        assert task.title == "Test task"
        assert task.priority.value == "high"
        assert task.project == "jaybrain"

    def test_task_list(self):
        from jaybrain.tasks import create_task, get_tasks
        create_task("Task A", project="proj1")
        create_task("Task B", project="proj2")
        tasks = get_tasks()
        assert len(tasks) == 2

    def test_task_update(self):
        from jaybrain.tasks import create_task, modify_task
        task = create_task("Update me")
        updated = modify_task(task.id, status="done")
        assert updated is not None
        assert updated.status.value == "done"

    def test_task_list_filter(self):
        from jaybrain.tasks import create_task, modify_task, get_tasks
        t1 = create_task("Active task")
        t2 = create_task("Done task")
        modify_task(t2.id, status="done")
        active = get_tasks(status="todo")
        assert len(active) == 1
        assert active[0].title == "Active task"


class TestSessionTools:
    def test_session_start(self):
        from jaybrain.sessions import start_session
        result = start_session("Test session")
        assert "session_id" in result
        assert result["previous_session"] is None

    def test_session_lifecycle(self):
        from jaybrain.sessions import start_session, end_current_session, get_handoff
        # Start
        result = start_session("Session 1")
        assert result["session_id"]
        # End
        session = end_current_session(
            "Did testing",
            decisions_made=["Use pytest"],
            next_steps=["Add more tests"],
        )
        assert session is not None
        assert session.summary == "Did testing"
        # Handoff
        handoff = get_handoff()
        assert handoff is not None
        assert handoff["summary"] == "Did testing"
        assert "Use pytest" in handoff["decisions_made"]

    def test_session_continuity(self):
        from jaybrain.sessions import start_session, end_current_session
        # First session
        start_session("First")
        end_current_session("Completed first session")
        # Second session should have previous context
        result = start_session("Second")
        assert result["previous_session"] is not None
        assert result["previous_session"]["summary"] == "Completed first session"


class TestSystemTools:
    def test_stats_empty(self):
        from jaybrain.db import get_connection, get_stats
        conn = get_connection()
        try:
            s = get_stats(conn)
            assert s["memory_count"] == 0
            assert s["task_count"] == 0
        finally:
            conn.close()

    def test_stats_after_data(self):
        from jaybrain.tasks import create_task
        from jaybrain.db import get_connection, get_stats
        create_task("Task 1")
        create_task("Task 2")
        conn = get_connection()
        try:
            s = get_stats(conn)
            assert s["task_count"] == 2
            assert s["active_tasks"] == 2
        finally:
            conn.close()
