"""Tests for the queue module (prioritized task queue)."""

import pytest

from jaybrain.db import init_db
from jaybrain.config import ensure_data_dirs
from jaybrain.tasks import create_task, modify_task
from jaybrain.queue import (
    queue_next,
    queue_push,
    queue_pop,
    queue_view,
    queue_defer,
    queue_bump,
    queue_reorder,
    get_next_suggestion,
)


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


def _make_task(title="Test task", **kwargs):
    return create_task(title, **kwargs)


class TestQueueNext:
    def test_empty_queue(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_next()
        assert result["status"] == "empty"

    def test_returns_lowest_position(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        queue_push(t1.id)
        queue_push(t2.id)
        result = queue_next()
        assert result["status"] == "ok"
        assert result["next_task"]["id"] == t1.id


class TestQueuePush:
    def test_push_to_empty_queue(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("New task")
        result = queue_push(task.id)
        assert result["status"] == "queued"
        assert result["task"]["queue_position"] == 1

    def test_push_appends_to_end(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        queue_push(t1.id)
        result = queue_push(t2.id)
        assert result["task"]["queue_position"] == 2

    def test_push_at_position(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        t3 = _make_task("Inserted")
        queue_push(t1.id)
        queue_push(t2.id)
        result = queue_push(t3.id, position=1)
        assert result["task"]["queue_position"] == 1

        # Original first task should have shifted to 2
        view = queue_view()
        positions = {t["id"]: t["queue_position"] for t in view["queue"]}
        assert positions[t1.id] == 2

    def test_push_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_push("nonexistent")
        assert result["status"] == "not_found"

    def test_push_done_task(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Done task")
        modify_task(task.id, status="done")
        result = queue_push(task.id)
        assert result["status"] == "error"

    def test_push_already_queued(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Queued task")
        queue_push(task.id)
        result = queue_push(task.id)
        assert result["status"] == "already_queued"


class TestQueuePop:
    def test_pop_empty_queue(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_pop()
        assert result["status"] == "empty"

    def test_pop_sets_in_progress(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Pop me")
        queue_push(task.id)
        result = queue_pop()
        assert result["status"] == "popped"
        assert result["task"]["id"] == task.id
        assert result["task"]["queue_position"] is None

    def test_pop_removes_from_queue(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_pop()

        # Second task should now be first
        result = queue_next()
        assert result["next_task"]["id"] == t2.id
        assert result["next_task"]["queue_position"] == 1

    def test_pop_message(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Important work")
        queue_push(task.id)
        result = queue_pop()
        assert "Important work" in result["message"]


class TestQueueView:
    def test_view_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_view()
        assert result["queue_length"] == 0
        assert result["queue"] == []

    def test_view_ordered(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        t3 = _make_task("Third")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_push(t3.id)

        result = queue_view()
        assert result["queue_length"] == 3
        ids = [t["id"] for t in result["queue"]]
        assert ids == [t1.id, t2.id, t3.id]


class TestQueueDefer:
    def test_defer_moves_to_end(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        t3 = _make_task("Third")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_push(t3.id)

        result = queue_defer(t1.id)
        assert result["status"] == "deferred"
        assert result["next_task"]["id"] == t2.id

        view = queue_view()
        ids = [t["id"] for t in view["queue"]]
        assert ids[-1] == t1.id

    def test_defer_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_defer("nonexistent")
        assert result["status"] == "not_found"

    def test_defer_not_in_queue(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Not queued")
        result = queue_defer(task.id)
        assert result["status"] == "not_in_queue"


class TestQueueBump:
    def test_bump_to_top(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("First")
        t2 = _make_task("Second")
        t3 = _make_task("Bump me")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_push(t3.id)

        result = queue_bump(t3.id)
        assert result["status"] == "bumped"
        assert result["task"]["queue_position"] == 1

    def test_bump_unqueued_task(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("Existing")
        t2 = _make_task("Not queued")
        queue_push(t1.id)

        result = queue_bump(t2.id)
        assert result["status"] == "bumped"
        assert result["task"]["queue_position"] == 1

        # Existing task should now be at position 2
        view = queue_view()
        positions = {t["id"]: t["queue_position"] for t in view["queue"]}
        assert positions[t1.id] == 2

    def test_bump_done_task(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Done")
        modify_task(task.id, status="done")
        result = queue_bump(task.id)
        assert result["status"] == "error"

    def test_bump_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_bump("nonexistent")
        assert result["status"] == "not_found"


class TestQueueReorder:
    def test_reorder(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("A")
        t2 = _make_task("B")
        t3 = _make_task("C")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_push(t3.id)

        result = queue_reorder([t3.id, t1.id, t2.id])
        assert result["status"] == "reordered"
        ids = [t["id"] for t in result["queue"]]
        assert ids == [t3.id, t1.id, t2.id]

    def test_reorder_partial_list_appends_remaining(self, temp_data_dir):
        _setup_db(temp_data_dir)
        t1 = _make_task("A")
        t2 = _make_task("B")
        t3 = _make_task("C")
        queue_push(t1.id)
        queue_push(t2.id)
        queue_push(t3.id)

        # Only specify t3, t2 should be appended after
        result = queue_reorder([t3.id])
        ids = [t["id"] for t in result["queue"]]
        assert ids[0] == t3.id
        assert t1.id in ids
        assert t2.id in ids

    def test_reorder_nonexistent_task(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = queue_reorder(["nonexistent"])
        assert result["status"] == "not_found"


class TestGetNextSuggestion:
    def test_suggestion_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        assert get_next_suggestion() is None

    def test_suggestion_returns_next(self, temp_data_dir):
        _setup_db(temp_data_dir)
        task = _make_task("Suggested")
        queue_push(task.id)
        result = get_next_suggestion()
        assert result is not None
        assert result["id"] == task.id
