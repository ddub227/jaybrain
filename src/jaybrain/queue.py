"""Prioritized task queue operations.

Provides a FIFO-ish queue on top of the tasks table using the
queue_position column. Tasks in the queue are ordered by position
(lower = higher priority). Completed/cancelled tasks are excluded
from the active queue automatically.
"""

from __future__ import annotations

from typing import Optional

from .db import (
    get_connection,
    get_task,
    get_queue_tasks,
    get_next_queue_task,
    get_max_queue_position,
    set_queue_position,
    clear_queue_position,
    shift_queue_positions,
    reindex_queue,
    update_task,
)
from .tasks import _parse_task_row


def _task_to_dict(row) -> dict:
    """Convert a task row to a dict suitable for JSON output."""
    task = _parse_task_row(row)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "project": task.project,
        "tags": task.tags,
        "due_date": str(task.due_date) if task.due_date else None,
        "queue_position": row["queue_position"],
        "created_at": task.created_at.isoformat(),
    }


def queue_next() -> dict:
    """Return the next task in the queue (lowest position, not done/cancelled).

    This is the "what should I do next?" command.
    """
    conn = get_connection()
    try:
        row = get_next_queue_task(conn)
        if row is None:
            return {"status": "empty", "message": "Queue is empty. All caught up!"}
        return {"status": "ok", "next_task": _task_to_dict(row)}
    finally:
        conn.close()


def queue_push(task_id: str, position: Optional[int] = None) -> dict:
    """Add a task to the queue.

    If position is None, appends to the end.
    If position is given, inserts there and shifts everything else down.
    """
    conn = get_connection()
    try:
        row = get_task(conn, task_id)
        if row is None:
            return {"status": "not_found", "task_id": task_id}

        if row["status"] in ("done", "cancelled"):
            return {
                "status": "error",
                "message": f"Cannot queue a {row['status']} task.",
            }

        # Check if already in queue
        if row["queue_position"] is not None:
            return {
                "status": "already_queued",
                "task_id": task_id,
                "queue_position": row["queue_position"],
                "message": "Task is already in the queue. Use queue_reorder or queue_bump to move it.",
            }

        if position is None:
            # Append to end
            max_pos = get_max_queue_position(conn)
            new_pos = max_pos + 1
        else:
            new_pos = max(1, position)
            # Shift existing items down to make room
            shift_queue_positions(conn, new_pos, delta=1)

        set_queue_position(conn, task_id, new_pos)

        # Re-fetch to get updated data
        row = get_task(conn, task_id)
        return {
            "status": "queued",
            "task": _task_to_dict(row),
        }
    finally:
        conn.close()


def queue_pop() -> dict:
    """Mark the top task as in_progress and return it.

    Removes it from the queue and reindexes.
    """
    conn = get_connection()
    try:
        row = get_next_queue_task(conn)
        if row is None:
            return {"status": "empty", "message": "Queue is empty. Nothing to pop."}

        task_id = row["id"]

        # Set status to in_progress
        update_task(conn, task_id, status="in_progress")
        # Remove from queue
        clear_queue_position(conn, task_id)
        # Reindex remaining queue
        reindex_queue(conn)

        # Re-fetch for fresh data
        row = get_task(conn, task_id)
        task_data = _task_to_dict(row)
        task_data["queue_position"] = None  # No longer in queue

        return {
            "status": "popped",
            "task": task_data,
            "message": f"Now working on: {row['title']}",
        }
    finally:
        conn.close()


def queue_reorder(task_ids: list[str]) -> dict:
    """Reorder the queue by providing task IDs in the desired order.

    Tasks not in the provided list but currently in the queue
    will be appended after the specified tasks (preserving their
    relative order).
    """
    conn = get_connection()
    try:
        # Validate all provided task IDs exist
        for tid in task_ids:
            row = get_task(conn, tid)
            if row is None:
                return {"status": "not_found", "task_id": tid}
            if row["status"] in ("done", "cancelled"):
                return {
                    "status": "error",
                    "message": f"Task {tid} is {row['status']} and cannot be in the queue.",
                }

        # Get current queue to find any tasks not in the provided list
        current_queue = get_queue_tasks(conn)
        current_ids = [r["id"] for r in current_queue]

        # Tasks in provided list that aren't already queued get added
        # Tasks in current queue but not in provided list get appended
        remaining = [tid for tid in current_ids if tid not in task_ids]
        full_order = list(task_ids) + remaining

        # Assign new positions
        for i, tid in enumerate(full_order, start=1):
            set_queue_position(conn, tid, i)

        # Build output
        queue = get_queue_tasks(conn)
        queue_list = [_task_to_dict(r) for r in queue]

        return {
            "status": "reordered",
            "queue_length": len(queue_list),
            "queue": queue_list,
        }
    finally:
        conn.close()


def queue_view() -> dict:
    """Show the full queue in order."""
    conn = get_connection()
    try:
        rows = get_queue_tasks(conn)
        queue_list = [_task_to_dict(r) for r in rows]
        return {
            "status": "ok",
            "queue_length": len(queue_list),
            "queue": queue_list,
        }
    finally:
        conn.close()


def queue_defer(task_id: str) -> dict:
    """Move a task to the end of the queue.

    Useful when going on a tangent -- push current work to the back.
    """
    conn = get_connection()
    try:
        row = get_task(conn, task_id)
        if row is None:
            return {"status": "not_found", "task_id": task_id}

        if row["queue_position"] is None:
            return {
                "status": "not_in_queue",
                "task_id": task_id,
                "message": "Task is not in the queue. Use queue_push to add it first.",
            }

        # Move to end
        max_pos = get_max_queue_position(conn)
        set_queue_position(conn, task_id, max_pos + 1)
        # Reindex to close gaps
        reindex_queue(conn)

        row = get_task(conn, task_id)
        task_data = _task_to_dict(row)

        # Also show what's next now
        next_row = get_next_queue_task(conn)
        next_task = _task_to_dict(next_row) if next_row else None

        return {
            "status": "deferred",
            "task": task_data,
            "next_task": next_task,
            "message": f"Deferred '{row['title']}' to end of queue.",
        }
    finally:
        conn.close()


def queue_bump(task_id: str) -> dict:
    """Move a task to position 1 (urgent / top priority).

    Everything else shifts down.
    """
    conn = get_connection()
    try:
        row = get_task(conn, task_id)
        if row is None:
            return {"status": "not_found", "task_id": task_id}

        if row["status"] in ("done", "cancelled"):
            return {
                "status": "error",
                "message": f"Cannot bump a {row['status']} task.",
            }

        # If already in queue, remove first to avoid double-counting
        if row["queue_position"] is not None:
            clear_queue_position(conn, task_id)
            reindex_queue(conn)

        # Shift everything down from position 1
        shift_queue_positions(conn, 1, delta=1)
        # Place this task at position 1
        set_queue_position(conn, task_id, 1)

        row = get_task(conn, task_id)
        task_data = _task_to_dict(row)

        return {
            "status": "bumped",
            "task": task_data,
            "message": f"'{row['title']}' is now #1 in the queue.",
        }
    finally:
        conn.close()


def get_next_suggestion() -> Optional[dict]:
    """Get the next queue task as a suggestion (for auto-resurface).

    Returns None if queue is empty. Used by task_update to suggest
    the next item when a task is completed.
    """
    conn = get_connection()
    try:
        row = get_next_queue_task(conn)
        if row is None:
            return None
        return _task_to_dict(row)
    finally:
        conn.close()
