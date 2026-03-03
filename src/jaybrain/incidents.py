"""Incident tracking: logging, search, metrics, and action item management."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from .db import (
    get_connection,
    insert_incident,
    update_incident,
    get_incident,
    list_incidents,
    search_incidents_fts,
    insert_action_item,
    update_action_item,
    get_action_items_for_incident,
    list_action_items,
    insert_lesson,
    get_lessons_for_incident,
    now_iso,
)
from .models import (
    Incident,
    ActionItem,
    Lesson,
    IncidentSeverity,
    IncidentType,
    IncidentErrorType,
    IncidentStatus,
    DetectionMethod,
    ActionItemType,
    ActionItemStatus,
    LessonType,
)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_incident_row(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "severity": row["severity"],
        "incident_type": row["incident_type"],
        "error_type": row["error_type"],
        "summary": row["summary"],
        "root_cause": row["root_cause"],
        "impact": row["impact"],
        "detection_method": row["detection_method"],
        "time_to_detect": row["time_to_detect"],
        "time_to_resolve": row["time_to_resolve"],
        "tags": json.loads(row["tags"]),
        "recurrence_of": row["recurrence_of"],
        "status": row["status"],
        "fix_applied": row["fix_applied"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _parse_action_item_row(row) -> dict:
    result = {
        "id": row["id"],
        "incident_id": row["incident_id"],
        "description": row["description"],
        "item_type": row["item_type"],
        "status": row["status"],
        "due_date": row["due_date"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    # JOIN queries may include incident_title
    try:
        result["incident_title"] = row["incident_title"]
    except (IndexError, KeyError):
        pass
    return result


def _parse_lesson_row(row) -> dict:
    return {
        "id": row["id"],
        "incident_id": row["incident_id"],
        "lesson_type": row["lesson_type"],
        "description": row["description"],
        "created_at": row["created_at"],
    }


def log_incident(
    title: str,
    summary: str,
    date: Optional[str] = None,
    severity: str = "medium",
    incident_type: str = "hit",
    error_type: str = "claude_mistake",
    root_cause: str = "",
    impact: str = "",
    detection_method: str = "user_reported",
    time_to_detect: Optional[int] = None,
    time_to_resolve: Optional[int] = None,
    tags: Optional[list[str]] = None,
    recurrence_of: Optional[str] = None,
    fix_applied: str = "",
    action_items: Optional[list[dict]] = None,
    lessons: Optional[list[dict]] = None,
) -> dict:
    """Create an incident with optional action items and lessons in one call."""
    # Validate enums
    IncidentSeverity(severity)
    IncidentType(incident_type)
    IncidentErrorType(error_type)
    DetectionMethod(detection_method)

    incident_id = _generate_id()
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        insert_incident(
            conn, incident_id, title, date, severity, incident_type,
            error_type, summary, root_cause, impact, detection_method,
            time_to_detect, time_to_resolve, tags, recurrence_of, fix_applied,
        )

        action_item_ids = []
        if action_items:
            for ai in action_items:
                ai_id = _generate_id()
                ActionItemType(ai.get("item_type", "prevent"))
                insert_action_item(
                    conn, ai_id, incident_id,
                    ai["description"],
                    ai.get("item_type", "prevent"),
                    ai.get("due_date"),
                )
                action_item_ids.append(ai_id)

        lesson_ids = []
        if lessons:
            for ls in lessons:
                ls_id = _generate_id()
                LessonType(ls.get("lesson_type", "went_wrong"))
                insert_lesson(
                    conn, ls_id, incident_id,
                    ls.get("lesson_type", "went_wrong"),
                    ls["description"],
                )
                lesson_ids.append(ls_id)

        row = get_incident(conn, incident_id)
        incident = _parse_incident_row(row)
        return {
            "incident": incident,
            "action_item_ids": action_item_ids,
            "lesson_ids": lesson_ids,
        }
    finally:
        conn.close()


def search_incidents(
    query: Optional[str] = None,
    severity: Optional[str] = None,
    error_type: Optional[str] = None,
    incident_type: Optional[str] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Search incidents by FTS query and/or structured filters."""
    conn = get_connection()
    try:
        if query:
            # FTS search first, then apply structured filters
            fts_results = search_incidents_fts(conn, query, limit=100)
            fts_ids = {r[0] for r in fts_results}
            if not fts_ids:
                return []
            # Get full rows and apply filters
            all_rows = list_incidents(
                conn, severity=severity, status=status,
                error_type=error_type, incident_type=incident_type,
                tag=tag, date_from=date_from, date_to=date_to, limit=100,
            )
            results = []
            for row in all_rows:
                if row["id"] in fts_ids and len(results) < limit:
                    results.append(_parse_incident_row(row))
            return results
        else:
            rows = list_incidents(
                conn, severity=severity, status=status,
                error_type=error_type, incident_type=incident_type,
                tag=tag, date_from=date_from, date_to=date_to, limit=limit,
            )
            return [_parse_incident_row(row) for row in rows]
    finally:
        conn.close()


def get_incident_detail(incident_id: str) -> Optional[dict]:
    """Get full incident with action items and lessons."""
    conn = get_connection()
    try:
        row = get_incident(conn, incident_id)
        if not row:
            return None
        incident = _parse_incident_row(row)
        action_items = [
            _parse_action_item_row(r)
            for r in get_action_items_for_incident(conn, incident_id)
        ]
        lessons = [
            _parse_lesson_row(r)
            for r in get_lessons_for_incident(conn, incident_id)
        ]
        return {
            "incident": incident,
            "action_items": action_items,
            "lessons": lessons,
        }
    finally:
        conn.close()


def modify_incident(incident_id: str, **fields) -> Optional[dict]:
    """Update incident fields. Returns updated incident or None if not found."""
    conn = get_connection()
    try:
        success = update_incident(conn, incident_id, **fields)
        if not success:
            return None
        row = get_incident(conn, incident_id)
        if not row:
            return None
        return _parse_incident_row(row)
    finally:
        conn.close()


def track_action_item(item_id: str, status: str) -> Optional[dict]:
    """Update action item status. Auto-sets completed_at when done."""
    ActionItemStatus(status)
    fields: dict = {"status": status}
    if status == "done":
        fields["completed_at"] = now_iso()
    elif status != "done":
        fields["completed_at"] = None

    conn = get_connection()
    try:
        success = update_action_item(conn, item_id, **fields)
        if not success:
            return None
        row = conn.execute(
            "SELECT * FROM incident_action_items WHERE id = ?", (item_id,)
        ).fetchone()
        return _parse_action_item_row(row) if row else None
    finally:
        conn.close()


def get_open_action_items(limit: int = 50) -> list[dict]:
    """Get all open action items with parent incident titles."""
    conn = get_connection()
    try:
        rows = list_action_items(conn, status="todo", limit=limit)
        in_progress = list_action_items(conn, status="in_progress", limit=limit)
        all_items = list(rows) + list(in_progress)
        return [_parse_action_item_row(r) for r in all_items]
    finally:
        conn.close()


def get_action_items_by_incident(incident_id: str) -> list[dict]:
    """Get action items for a specific incident."""
    conn = get_connection()
    try:
        rows = get_action_items_for_incident(conn, incident_id)
        return [_parse_action_item_row(r) for r in rows]
    finally:
        conn.close()


def compute_metrics() -> dict:
    """Aggregate incident metrics."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        if total == 0:
            return {
                "total": 0,
                "by_severity": {},
                "by_error_type": {},
                "by_status": {},
                "recurrence_count": 0,
                "recurrence_rate": 0.0,
                "avg_time_to_detect": None,
                "avg_time_to_resolve": None,
                "action_item_total": 0,
                "action_item_done": 0,
                "action_item_completion_rate": 0.0,
                "top_tags": [],
                "recent": [],
            }

        by_severity = {}
        for row in conn.execute(
            "SELECT severity, COUNT(*) as cnt FROM incidents GROUP BY severity"
        ).fetchall():
            by_severity[row["severity"]] = row["cnt"]

        by_error_type = {}
        for row in conn.execute(
            "SELECT error_type, COUNT(*) as cnt FROM incidents GROUP BY error_type"
        ).fetchall():
            by_error_type[row["error_type"]] = row["cnt"]

        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM incidents GROUP BY status"
        ).fetchall():
            by_status[row["status"]] = row["cnt"]

        recurrence_count = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE recurrence_of IS NOT NULL"
        ).fetchone()[0]
        recurrence_rate = recurrence_count / total if total > 0 else 0.0

        avg_ttd_row = conn.execute(
            "SELECT AVG(time_to_detect) FROM incidents WHERE time_to_detect IS NOT NULL"
        ).fetchone()
        avg_ttd = avg_ttd_row[0]

        avg_ttr_row = conn.execute(
            "SELECT AVG(time_to_resolve) FROM incidents WHERE time_to_resolve IS NOT NULL"
        ).fetchone()
        avg_ttr = avg_ttr_row[0]

        ai_total = conn.execute(
            "SELECT COUNT(*) FROM incident_action_items"
        ).fetchone()[0]
        ai_done = conn.execute(
            "SELECT COUNT(*) FROM incident_action_items WHERE status = 'done'"
        ).fetchone()[0]
        ai_rate = ai_done / ai_total if ai_total > 0 else 0.0

        # Top tags — explode JSON arrays and count
        tag_counts: dict[str, int] = {}
        for row in conn.execute("SELECT tags FROM incidents").fetchall():
            for t in json.loads(row["tags"]):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        recent_rows = conn.execute(
            "SELECT * FROM incidents ORDER BY date DESC LIMIT 5"
        ).fetchall()
        recent = [_parse_incident_row(r) for r in recent_rows]

        return {
            "total": total,
            "by_severity": by_severity,
            "by_error_type": by_error_type,
            "by_status": by_status,
            "recurrence_count": recurrence_count,
            "recurrence_rate": round(recurrence_rate, 3),
            "avg_time_to_detect": round(avg_ttd, 1) if avg_ttd is not None else None,
            "avg_time_to_resolve": round(avg_ttr, 1) if avg_ttr is not None else None,
            "action_item_total": ai_total,
            "action_item_done": ai_done,
            "action_item_completion_rate": round(ai_rate, 3),
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "recent": recent,
        }
    finally:
        conn.close()
