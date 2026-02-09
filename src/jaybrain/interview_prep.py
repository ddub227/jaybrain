"""Interview prep content management.

Saves and retrieves interview preparation content linked to applications.
Aggregates job details, application status, prep content, and profile
into a comprehensive interview context package.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from .db import (
    get_application,
    get_connection,
    get_interview_prep_for_app,
    get_job_posting,
    insert_interview_prep,
)
from .models import InterviewPrep, InterviewPrepType

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_prep_row(row) -> InterviewPrep:
    """Convert a database row to an InterviewPrep model."""
    return InterviewPrep(
        id=row["id"],
        application_id=row["application_id"],
        prep_type=InterviewPrepType(row["prep_type"]),
        content=row["content"],
        tags=json.loads(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def add_prep(
    application_id: str,
    prep_type: str = "general",
    content: str = "",
    tags: Optional[list[str]] = None,
) -> InterviewPrep:
    """Save interview prep content for an application."""
    conn = get_connection()
    try:
        # Verify application exists
        app_row = get_application(conn, application_id)
        if not app_row:
            raise ValueError(f"Application not found: {application_id}")

        prep_id = _generate_id()
        insert_interview_prep(conn, prep_id, application_id, prep_type, content, tags or [])

        # Fetch back the inserted row
        row = conn.execute(
            "SELECT * FROM interview_prep WHERE id = ?", (prep_id,)
        ).fetchone()
        return _parse_prep_row(row)
    finally:
        conn.close()


def get_prep_context(application_id: str) -> dict:
    """Get full interview context for an application.

    Aggregates: job posting, application details, all prep content,
    user profile excerpt, and resume template excerpt.
    """
    conn = get_connection()
    try:
        # Application
        app_row = get_application(conn, application_id)
        if not app_row:
            raise ValueError(f"Application not found: {application_id}")

        # Job posting
        job_row = get_job_posting(conn, app_row["job_id"])
        job_info = {}
        if job_row:
            job_info = {
                "id": job_row["id"],
                "title": job_row["title"],
                "company": job_row["company"],
                "description": job_row["description"],
                "required_skills": json.loads(job_row["required_skills"]),
                "preferred_skills": json.loads(job_row["preferred_skills"]),
                "work_mode": job_row["work_mode"],
                "location": job_row["location"],
            }

        # All prep entries
        prep_rows = get_interview_prep_for_app(conn, application_id)
        prep_by_type = {}
        for row in prep_rows:
            prep = _parse_prep_row(row)
            prep_type = prep.prep_type.value
            if prep_type not in prep_by_type:
                prep_by_type[prep_type] = []
            prep_by_type[prep_type].append({
                "id": prep.id,
                "content": prep.content,
                "tags": prep.tags,
                "created_at": prep.created_at.isoformat(),
            })

        # Profile excerpt
        profile_excerpt = {}
        try:
            from .profile import get_profile
            profile = get_profile()
            profile_excerpt = {
                "name": profile.get("name", ""),
                "preferences": profile.get("preferences", {}),
                "tools": profile.get("tools", []),
            }
        except Exception:
            pass

        # Resume template excerpt
        resume_excerpt = ""
        try:
            from .resume_tailor import get_template
            template_result = get_template()
            if template_result.get("status") == "ok":
                resume_excerpt = template_result["content"][:2000]
        except Exception:
            pass

        return {
            "application": {
                "id": app_row["id"],
                "status": app_row["status"],
                "notes": app_row["notes"],
                "applied_date": app_row["applied_date"],
                "resume_path": app_row["resume_path"],
                "cover_letter_path": app_row["cover_letter_path"],
            },
            "job": job_info,
            "prep": prep_by_type,
            "prep_count": len(prep_rows),
            "profile": profile_excerpt,
            "resume_excerpt": resume_excerpt,
        }
    finally:
        conn.close()
