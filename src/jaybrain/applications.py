"""Application tracking and pipeline dashboard.

Tracks job applications through the pipeline from discovery to offer/rejection.
Provides status management and pipeline summary views.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from .db import (
    get_application,
    get_application_pipeline,
    get_connection,
    get_job_posting,
    insert_application,
    list_applications,
    update_application,
)
from .models import Application, ApplicationStatus

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_app_row(row) -> Application:
    """Convert a database row to an Application model."""
    return Application(
        id=row["id"],
        job_id=row["job_id"],
        status=ApplicationStatus(row["status"]),
        resume_path=row["resume_path"],
        cover_letter_path=row["cover_letter_path"],
        applied_date=row["applied_date"],
        notes=row["notes"],
        tags=json.loads(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def create_application(
    job_id: str,
    status: str = "discovered",
    notes: str = "",
    tags: Optional[list[str]] = None,
) -> Application:
    """Start tracking an application for a job posting."""
    conn = get_connection()
    try:
        # Verify job exists
        job_row = get_job_posting(conn, job_id)
        if not job_row:
            raise ValueError(f"Job posting not found: {job_id}")

        app_id = _generate_id()
        insert_application(conn, app_id, job_id, status, notes, tags or [])
        row = get_application(conn, app_id)
        return _parse_app_row(row)
    finally:
        conn.close()


def modify_application(app_id: str, **fields) -> Optional[Application]:
    """Update application status, paths, notes, etc."""
    conn = get_connection()
    try:
        row = get_application(conn, app_id)
        if not row:
            return None

        update_application(conn, app_id, **fields)
        row = get_application(conn, app_id)
        return _parse_app_row(row)
    finally:
        conn.close()


def get_applications(
    status: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """List applications with pipeline summary.

    Returns both the application list and a pipeline summary
    showing counts by status.
    """
    conn = get_connection()
    try:
        rows = list_applications(conn, status=status, limit=limit)
        apps = []
        for row in rows:
            app = _parse_app_row(row)
            # Attach job info
            job_row = get_job_posting(conn, app.job_id)
            job_info = {}
            if job_row:
                job_info = {
                    "title": job_row["title"],
                    "company": job_row["company"],
                    "work_mode": job_row["work_mode"],
                }
            apps.append({
                "id": app.id,
                "job_id": app.job_id,
                "job": job_info,
                "status": app.status.value,
                "resume_path": app.resume_path,
                "cover_letter_path": app.cover_letter_path,
                "applied_date": app.applied_date,
                "notes": app.notes,
                "tags": app.tags,
                "created_at": app.created_at.isoformat(),
                "updated_at": app.updated_at.isoformat(),
            })

        pipeline = get_application_pipeline(conn)

        return {
            "applications": apps,
            "count": len(apps),
            "pipeline": pipeline,
        }
    finally:
        conn.close()
