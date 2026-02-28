"""Job posting CRUD and FTS search.

Stores job postings extracted from board scraping or added manually.
Provides full-text search across title, company, description, and skills.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from .db import (
    fts5_safe_query,
    get_connection,
    get_job_posting,
    insert_job_posting,
    list_job_postings,
    search_job_postings_fts,
)
from .models import JobPosting, JobType, WorkMode

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]



def _parse_posting_row(row) -> JobPosting:
    """Convert a database row to a JobPosting model."""
    return JobPosting(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        url=row["url"],
        description=row["description"],
        required_skills=json.loads(row["required_skills"]),
        preferred_skills=json.loads(row["preferred_skills"]),
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        job_type=JobType(row["job_type"]),
        work_mode=WorkMode(row["work_mode"]),
        location=row["location"],
        board_id=row["board_id"],
        tags=json.loads(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def add_job(
    title: str,
    company: str,
    url: str = "",
    description: str = "",
    required_skills: Optional[list[str]] = None,
    preferred_skills: Optional[list[str]] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    job_type: str = "full_time",
    work_mode: str = "remote",
    location: str = "",
    board_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> JobPosting:
    """Add a job posting (from scraping or manual entry)."""
    job_id = _generate_id()
    conn = get_connection()
    try:
        insert_job_posting(
            conn, job_id, title, company, url, description,
            required_skills or [], preferred_skills or [],
            salary_min, salary_max, job_type, work_mode,
            location, board_id, tags or [],
        )
        row = get_job_posting(conn, job_id)
        return _parse_posting_row(row)
    finally:
        conn.close()


def get_job(job_id: str) -> Optional[JobPosting]:
    """Get full posting details by ID."""
    conn = get_connection()
    try:
        row = get_job_posting(conn, job_id)
        if not row:
            return None
        return _parse_posting_row(row)
    finally:
        conn.close()


def search_jobs(
    query: Optional[str] = None,
    company: Optional[str] = None,
    work_mode: Optional[str] = None,
    limit: int = 20,
) -> list[JobPosting]:
    """Search job postings using FTS or filters."""
    conn = get_connection()
    try:
        if query:
            safe_query = fts5_safe_query(query)
            if safe_query:
                fts_results = search_job_postings_fts(conn, safe_query, limit)
                postings = []
                for job_id, score in fts_results:
                    row = get_job_posting(conn, job_id)
                    if row:
                        posting = _parse_posting_row(row)
                        if company and posting.company.lower() != company.lower():
                            continue
                        if work_mode and posting.work_mode.value != work_mode:
                            continue
                        postings.append(posting)
                return postings[:limit]

        rows = list_job_postings(conn, company=company, work_mode=work_mode, limit=limit)
        return [_parse_posting_row(r) for r in rows]
    finally:
        conn.close()
