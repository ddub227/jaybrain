"""Tests for the tasks module (CRUD and filtering)."""

import pytest

from jaybrain.db import init_db, get_connection
from jaybrain.config import ensure_data_dirs
from jaybrain.tasks import create_task, modify_task, get_tasks
from jaybrain.models import TaskStatus, TaskPriority


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


class TestCreateTask:
    def test_create_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task("Write tests")
        assert task.title == "Write tests"
        assert task.status == TaskStatus.TODO
        assert task.priority == TaskPriority.MEDIUM
        assert task.description == ""
        assert task.tags == []
        assert task.project == ""
        assert task.due_date is None
        assert len(task.id) == 12

    def test_create_with_all_fields(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task(
            title="Deploy app",
            description="Push to prod",
            priority="high",
            project="jaybrain",
            tags=["devops", "urgent"],
            due_date="2026-03-01",
        )
        assert task.title == "Deploy app"
        assert task.description == "Push to prod"
        assert task.priority == TaskPriority.HIGH
        assert task.project == "jaybrain"
        assert task.tags == ["devops", "urgent"]

    def test_create_multiple_unique_ids(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = create_task("Task 1")
        t2 = create_task("Task 2")
        assert t1.id != t2.id


class TestModifyTask:
    def test_modify_title(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task("Original")
        updated = modify_task(task.id, title="Updated")
        assert updated is not None
        assert updated.title == "Updated"

    def test_modify_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task("Do something")
        updated = modify_task(task.id, status="in_progress")
        assert updated.status == TaskStatus.IN_PROGRESS

    def test_modify_multiple_fields(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task("Old title", priority="low")
        updated = modify_task(
            task.id,
            title="New title",
            priority="critical",
            project="new-project",
        )
        assert updated.title == "New title"
        assert updated.priority == TaskPriority.CRITICAL
        assert updated.project == "new-project"

    def test_modify_tags(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = create_task("Tagged task")
        updated = modify_task(task.id, tags=["alpha", "beta"])
        assert updated.tags == ["alpha", "beta"]

    def test_modify_nonexistent(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = modify_task("nonexistent_id", title="Nope")
        assert result is None


class TestGetTasks:
    def test_list_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        tasks = get_tasks()
        assert tasks == []

    def test_list_all(self, temp_data_dir):
        _setup_db(temp_data_dir)
        create_task("A")
        create_task("B")
        create_task("C")
        tasks = get_tasks()
        assert len(tasks) == 3

    def test_filter_by_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = create_task("Todo task")
        t2 = create_task("Done task")
        modify_task(t2.id, status="done")

        todo_tasks = get_tasks(status="todo")
        assert len(todo_tasks) == 1
        assert todo_tasks[0].title == "Todo task"

        done_tasks = get_tasks(status="done")
        assert len(done_tasks) == 1
        assert done_tasks[0].title == "Done task"

    def test_filter_by_project(self, temp_data_dir):
        _setup_db(temp_data_dir)
        create_task("JB task", project="jaybrain")
        create_task("Other task", project="other")

        jb_tasks = get_tasks(project="jaybrain")
        assert len(jb_tasks) == 1
        assert jb_tasks[0].project == "jaybrain"

    def test_filter_by_priority(self, temp_data_dir):
        _setup_db(temp_data_dir)
        create_task("Low", priority="low")
        create_task("High", priority="high")

        high_tasks = get_tasks(priority="high")
        assert len(high_tasks) == 1
        assert high_tasks[0].priority == TaskPriority.HIGH

    def test_limit(self, temp_data_dir):
        _setup_db(temp_data_dir)
        for i in range(10):
            create_task(f"Task {i}")
        tasks = get_tasks(limit=3)
        assert len(tasks) == 3

    def test_combined_filters(self, temp_data_dir):
        _setup_db(temp_data_dir)
        create_task("Match", priority="high", project="jaybrain")
        create_task("Wrong project", priority="high", project="other")
        create_task("Wrong priority", priority="low", project="jaybrain")

        tasks = get_tasks(priority="high", project="jaybrain")
        assert len(tasks) == 1
        assert tasks[0].title == "Match"
