"""Onboarding intake -- structured questionnaire for new user setup.

Collects information about the user and populates Life Domains, profile,
and initial memories. Designed as a multi-step flow that can be paused
and resumed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Onboarding questionnaire steps
INTAKE_QUESTIONS = [
    {
        "step": 0,
        "question": "What's your name and what do you prefer to be called?",
        "field": "name",
        "category": "profile",
    },
    {
        "step": 1,
        "question": "What's your current job title or professional role?",
        "field": "current_role",
        "category": "profile",
    },
    {
        "step": 2,
        "question": "What career are you working toward? What's your dream role?",
        "field": "target_role",
        "category": "career",
    },
    {
        "step": 3,
        "question": "What certifications or exams are you studying for? Include any target dates.",
        "field": "certifications",
        "category": "learning",
    },
    {
        "step": 4,
        "question": "What are your top 3-5 life priorities right now? (e.g., career change, health, family, learning)",
        "field": "life_priorities",
        "category": "domains",
    },
    {
        "step": 5,
        "question": "What tools and technologies do you use regularly? (programming languages, platforms, etc.)",
        "field": "tech_stack",
        "category": "skills",
    },
    {
        "step": 6,
        "question": "How many hours per week can you dedicate to personal development outside of work?",
        "field": "available_hours",
        "category": "scheduling",
    },
    {
        "step": 7,
        "question": "What's your preferred communication style? (concise, detailed, casual, professional)",
        "field": "communication_style",
        "category": "preference",
    },
    {
        "step": 8,
        "question": "Anything else I should know about you -- hobbies, interests, constraints, pet peeves?",
        "field": "additional",
        "category": "profile",
    },
]


def start_onboarding() -> dict:
    """Initialize or resume the onboarding flow."""
    conn = get_connection()
    try:
        now = now_iso()

        # Check existing state
        row = conn.execute(
            "SELECT * FROM onboarding_state WHERE id = 1"
        ).fetchone()

        if row and row["completed"]:
            return {
                "status": "already_completed",
                "completed_at": row["completed_at"],
                "message": "Onboarding was already completed. Use onboarding_progress() to review.",
            }

        if row:
            # Resume from where we left off
            current_step = row["current_step"]
            responses = json.loads(row["responses"]) if row["responses"] else {}
            return {
                "status": "resuming",
                "current_step": current_step,
                "total_steps": len(INTAKE_QUESTIONS),
                "next_question": INTAKE_QUESTIONS[current_step],
                "completed_steps": list(responses.keys()),
            }

        # Start fresh
        conn.execute(
            """INSERT INTO onboarding_state
            (id, current_step, total_steps, responses, completed, started_at)
            VALUES (1, 0, ?, '{}', 0, ?)""",
            (len(INTAKE_QUESTIONS), now),
        )
        conn.commit()

        return {
            "status": "started",
            "current_step": 0,
            "total_steps": len(INTAKE_QUESTIONS),
            "next_question": INTAKE_QUESTIONS[0],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def answer_step(step: int, response: str) -> dict:
    """Record an answer for an onboarding step and advance."""
    conn = get_connection()
    try:
        now = now_iso()

        row = conn.execute(
            "SELECT * FROM onboarding_state WHERE id = 1"
        ).fetchone()
        if not row:
            return {"error": "Onboarding not started. Call onboarding_start() first."}
        if row["completed"]:
            return {"error": "Onboarding already completed."}

        responses = json.loads(row["responses"]) if row["responses"] else {}

        # Validate step
        if step < 0 or step >= len(INTAKE_QUESTIONS):
            return {"error": f"Invalid step {step}. Must be 0-{len(INTAKE_QUESTIONS) - 1}"}

        # Record response
        field = INTAKE_QUESTIONS[step]["field"]
        responses[field] = response

        next_step = step + 1
        completed = next_step >= len(INTAKE_QUESTIONS)

        conn.execute(
            """UPDATE onboarding_state SET
            current_step = ?,
            responses = ?,
            completed = ?,
            completed_at = ?
            WHERE id = 1""",
            (next_step, json.dumps(responses), int(completed), now if completed else None),
        )
        conn.commit()

        if completed:
            # Process completed intake
            _process_completed_intake(responses)
            return {
                "status": "completed",
                "message": "Onboarding complete! Your profile, domains, and memories have been initialized.",
                "responses": responses,
            }

        return {
            "status": "recorded",
            "step_completed": step,
            "next_step": next_step,
            "next_question": INTAKE_QUESTIONS[next_step],
            "progress": f"{next_step}/{len(INTAKE_QUESTIONS)}",
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def get_progress() -> dict:
    """Check onboarding progress."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM onboarding_state WHERE id = 1"
        ).fetchone()

        if not row:
            return {
                "status": "not_started",
                "message": "Onboarding has not been started yet.",
            }

        responses = json.loads(row["responses"]) if row["responses"] else {}

        return {
            "status": "completed" if row["completed"] else "in_progress",
            "current_step": row["current_step"],
            "total_steps": row["total_steps"],
            "completed_steps": list(responses.keys()),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "responses": responses,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def _process_completed_intake(responses: dict) -> None:
    """Process completed intake responses to populate JayBrain systems."""

    # 1. Update profile
    try:
        from .profile import update_profile
        if "name" in responses:
            update_profile("personal", "name", responses["name"])
        if "current_role" in responses:
            update_profile("professional", "current_role", responses["current_role"])
        if "target_role" in responses:
            update_profile("professional", "target_role", responses["target_role"])
        if "communication_style" in responses:
            update_profile("preferences", "communication_style", responses["communication_style"])
        if "tech_stack" in responses:
            update_profile("skills", "tech_stack", responses["tech_stack"])
    except Exception as e:
        logger.error("Failed to update profile from intake: %s", e)

    # 2. Store key responses as memories
    try:
        from .memory import remember
        if "target_role" in responses:
            remember(
                f"Career goal: {responses['target_role']}",
                category="decision",
                tags=["career", "onboarding"],
                importance=0.9,
            )
        if "certifications" in responses:
            remember(
                f"Certifications being pursued: {responses['certifications']}",
                category="semantic",
                tags=["learning", "certifications", "onboarding"],
                importance=0.8,
            )
        if "additional" in responses and responses["additional"]:
            remember(
                f"Additional context from onboarding: {responses['additional']}",
                category="episodic",
                tags=["onboarding"],
                importance=0.6,
            )
    except Exception as e:
        logger.error("Failed to store intake memories: %s", e)

    # 3. Generate initial life domains from priorities
    try:
        if "life_priorities" in responses:
            _generate_initial_domains(responses["life_priorities"])
    except Exception as e:
        logger.error("Failed to generate domains from intake: %s", e)


def _generate_initial_domains(priorities_text: str) -> None:
    """Create life domains from the user's stated priorities."""
    conn = get_connection()
    try:
        now = now_iso()
        import re

        items = _parse_priority_items(priorities_text)

        for i, item in enumerate(items[:8]):  # Max 8 domains
            name = _extract_domain_name(item)
            from .life_domains import _generate_id
            conn.execute(
                """INSERT OR IGNORE INTO life_domains
                (id, name, description, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (_generate_id(), name, item, len(items) - i, now, now),
            )
        conn.commit()
    except Exception as e:
        logger.error("Failed to generate domains: %s", e)
    finally:
        conn.close()


def _parse_priority_items(text: str) -> list[str]:
    """Extract individual priority items from freeform text.

    Handles numbered lists (1) ... 2) ...), comma-separated, newline-separated.
    """
    import re

    # Try numbered list first: "1) item. 2) item" or "1. item 2. item"
    numbered = re.findall(r'\d+[.)]\s*([^.!?]+(?:[.!?](?!\s*\d+[.)]))*)', text)
    if numbered:
        return [item.strip().rstrip('.!? ') for item in numbered if item.strip()]

    # Try newline-separated (with optional bullets/dashes)
    lines = text.strip().split('\n')
    if len(lines) >= 2:
        items = []
        for line in lines:
            cleaned = re.sub(r'^[-*]\s*', '', line.strip())
            if cleaned:
                items.append(cleaned)
        return items

    # Fall back to comma/semicolon split
    parts = re.split(r'[,;]+', text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]


def _extract_domain_name(description: str) -> str:
    """Derive a short domain name (2-4 words) from a priority description."""
    # Common patterns to extract the core noun phrase
    import re

    core = description

    # Truncate at " -- " to drop elaboration
    if ' -- ' in core:
        core = core.split(' -- ')[0]

    # Remove leading verbs like "Pass", "Find", "Get", "Plan", "Build"
    core = re.sub(
        r'^(pass|find|get|land|plan|execute|build|achieve|complete|earn|save|move|figure out|work on|focus on)\s+',
        '', core, flags=re.IGNORECASE,
    ).strip()

    # Take first 3-4 meaningful words
    words = core.split()
    # Skip articles and prepositions at the start
    skip = {'a', 'an', 'the', 'my', 'for', 'to', 'and', 'or', 'in', 'on', 'up'}
    meaningful = [w for w in words if w.lower() not in skip]

    if not meaningful:
        meaningful = words[:3]

    name = ' '.join(meaningful[:4])

    # Capitalize nicely
    name = name.title()

    # Truncate if still too long
    if len(name) > 40:
        name = name[:37] + '...'

    return name
