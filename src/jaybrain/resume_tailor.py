"""Resume/cover letter generation and skill analysis.

Reads JJ's resume template, analyzes skill fit against job postings,
and saves tailored resumes and cover letters to the output directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .config import JOB_SEARCH_DIR, RESUME_TEMPLATE_PATH
from .db import get_connection, get_job_posting
from .models import JobPosting

logger = logging.getLogger(__name__)


def _parse_posting_row(row) -> dict:
    """Convert a job posting row to a dict for analysis."""
    return {
        "id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "description": row["description"],
        "required_skills": json.loads(row["required_skills"]),
        "preferred_skills": json.loads(row["preferred_skills"]),
        "job_type": row["job_type"],
        "work_mode": row["work_mode"],
        "location": row["location"],
    }


def get_template() -> dict:
    """Read the resume template file and return its content.

    The template should be a markdown file with HTML comment markers
    indicating tailorable sections, e.g. <!-- SUMMARY --> ... <!-- /SUMMARY -->.
    """
    if not RESUME_TEMPLATE_PATH.exists():
        return {
            "status": "no_template",
            "message": f"No resume template found at {RESUME_TEMPLATE_PATH}. "
                       f"Create a markdown file there with <!-- SECTION --> markers for tailorable sections.",
            "expected_path": str(RESUME_TEMPLATE_PATH),
        }

    content = RESUME_TEMPLATE_PATH.read_text(encoding="utf-8")
    return {
        "status": "ok",
        "path": str(RESUME_TEMPLATE_PATH),
        "content": content,
        "length": len(content),
    }


def analyze_fit(job_id: str) -> dict:
    """Compare JJ's skills against a job posting.

    Reads the resume template to extract current skills, then compares
    against the posting's required and preferred skills. Returns match
    percentages, gaps, and recommendations.
    """
    conn = get_connection()
    try:
        row = get_job_posting(conn, job_id)
        if not row:
            raise ValueError(f"Job posting not found: {job_id}")

        job = _parse_posting_row(row)
        required = [s.lower() for s in job["required_skills"]]
        preferred = [s.lower() for s in job["preferred_skills"]]

        # Extract skills from resume template
        my_skills = _extract_skills_from_template()
        my_skills_lower = [s.lower() for s in my_skills]

        # Calculate matches
        required_matches = [s for s in required if s in my_skills_lower]
        required_gaps = [s for s in required if s not in my_skills_lower]
        preferred_matches = [s for s in preferred if s in my_skills_lower]
        preferred_gaps = [s for s in preferred if s not in my_skills_lower]

        total_required = len(required)
        total_preferred = len(preferred)
        required_score = len(required_matches) / total_required if total_required else 1.0
        preferred_score = len(preferred_matches) / total_preferred if total_preferred else 1.0

        # Weighted overall score (required counts 70%, preferred 30%)
        overall_score = (required_score * 0.7) + (preferred_score * 0.3)

        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "overall_fit_score": round(overall_score, 2),
            "required_match_pct": round(required_score * 100, 1),
            "preferred_match_pct": round(preferred_score * 100, 1),
            "required_matches": required_matches,
            "required_gaps": required_gaps,
            "preferred_matches": preferred_matches,
            "preferred_gaps": preferred_gaps,
            "my_skills": my_skills,
            "recommendation": _fit_recommendation(overall_score, required_gaps),
        }
    finally:
        conn.close()


def _extract_skills_from_template() -> list[str]:
    """Extract skill keywords from resume template.

    Looks for a section between <!-- SKILLS --> markers, or falls back
    to returning an empty list if no template or markers exist.
    """
    if not RESUME_TEMPLATE_PATH.exists():
        return []

    content = RESUME_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Try to extract skills from marked section
    import re
    skills_match = re.search(
        r"<!--\s*SKILLS\s*-->(.*?)<!--\s*/SKILLS\s*-->",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if skills_match:
        section = skills_match.group(1)
        # Extract individual skills: items after bullets, commas, or pipes
        skills = re.findall(r"[\w\+\#\.]+(?:\s+[\w\+\#\.]+)?", section)
        return [s.strip() for s in skills if len(s.strip()) > 1]

    return []


def _fit_recommendation(score: float, gaps: list[str]) -> str:
    """Generate a brief recommendation based on fit score."""
    if score >= 0.85:
        return "Strong fit. Tailor resume to highlight matching experience."
    elif score >= 0.65:
        gap_text = ", ".join(gaps[:3]) if gaps else "none"
        return f"Good fit with some gaps ({gap_text}). Emphasize transferable skills."
    elif score >= 0.45:
        return "Moderate fit. Consider addressing skill gaps in cover letter."
    else:
        return "Significant gaps. Evaluate if this role aligns with your growth goals."


def save_tailored_resume(company: str, role: str, content: str) -> dict:
    """Save a tailored resume as markdown."""
    resumes_dir = JOB_SEARCH_DIR / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)

    safe_company = _safe_filename(company)
    safe_role = _safe_filename(role)
    filename = f"Resume_JoshuaBudd_{safe_company}_{safe_role}.md"
    filepath = resumes_dir / filename

    filepath.write_text(content, encoding="utf-8")
    logger.info("Saved tailored resume: %s", filepath)

    return {
        "status": "saved",
        "path": str(filepath),
        "filename": filename,
    }


def save_cover_letter(company: str, role: str, content: str) -> dict:
    """Save a cover letter as markdown."""
    cover_dir = JOB_SEARCH_DIR / "cover_letters"
    cover_dir.mkdir(parents=True, exist_ok=True)

    safe_company = _safe_filename(company)
    safe_role = _safe_filename(role)
    filename = f"CoverLetter_JoshuaBudd_{safe_company}_{safe_role}.md"
    filepath = cover_dir / filename

    filepath.write_text(content, encoding="utf-8")
    logger.info("Saved cover letter: %s", filepath)

    return {
        "status": "saved",
        "path": str(filepath),
        "filename": filename,
    }


def _safe_filename(name: str) -> str:
    """Convert a name to a safe filename component."""
    import re
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"[\s]+", "", safe.title())
    return safe[:50]
