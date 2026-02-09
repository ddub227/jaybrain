"""Task CRUD and filtering operations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from .db import get_connection, insert_task, update_task, get_task, list_tasks
from .models import Task, TaskStatus, TaskPriority


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_task_row(row) -> Task:
    """Convert a database row to a Task model."""
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        priority=TaskPriority(row["priority"]),
        project=row["project"],
        tags=json.loads(row["tags"]),
        due_date=row["due_date"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def create_task(
    title: str,
    description: str = "",
    priority: str = "medium",
    project: str = "",
    tags: Optional[list[str]] = None,
    due_date: Optional[str] = None,
) -> Task:
    """Create a new task."""
    tags = tags or []
    task_id = _generate_id()

    conn = get_connection()
    try:
        insert_task(
            conn, task_id, title, description,
            TaskStatus.TODO.value, priority, project, tags, due_date,
        )
        row = get_task(conn, task_id)
        return _parse_task_row(row)
    finally:
        conn.close()


def modify_task(task_id: str, **fields) -> Optional[Task]:
    """Update a task's fields. Returns updated task or None if not found."""
    conn = get_connection()
    try:
        success = update_task(conn, task_id, **fields)
        if not success:
            return None
        row = get_task(conn, task_id)
        if not row:
            return None
        return _parse_task_row(row)
    finally:
        conn.close()


def get_tasks(
    status: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
) -> list[Task]:
    """List tasks with optional filters."""
    conn = get_connection()
    try:
        rows = list_tasks(conn, status, project, priority, limit)
        return [_parse_task_row(row) for row in rows]
    finally:
        conn.close()
