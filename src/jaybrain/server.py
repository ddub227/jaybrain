"""MCP server entry point - all 33 tools for JayBrain."""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from fastmcp import FastMCP

from .config import ensure_data_dirs
from .db import init_db, get_connection, get_stats

# Configure logging to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("jaybrain")

# Initialize data directories and database
ensure_data_dirs()
init_db()

# Create the MCP server
mcp = FastMCP(
    "JayBrain",
    instructions=(
        "JayBrain is JJ's personal AI memory system. "
        "Use these tools to remember information across sessions, "
        "track tasks, manage knowledge, and maintain session continuity."
    ),
)


# =============================================================================
# Memory Tools (3)
# =============================================================================

@mcp.tool()
def remember(
    content: str,
    category: str = "semantic",
    tags: list[str] | None = None,
    importance: float = 0.5,
) -> str:
    """Store a memory. Writes to markdown file, generates embedding, indexes in DB.

    Categories: episodic (events), semantic (facts), procedural (how-to),
    decision (choices made), preference (user preferences).
    Importance: 0.0-1.0 (higher = more important, resists decay).
    """
    from .memory import remember as _remember

    try:
        memory = _remember(content, category, tags or [], importance)
        return json.dumps({
            "status": "stored",
            "memory_id": memory.id,
            "category": memory.category.value,
            "tags": memory.tags,
            "importance": memory.importance,
        })
    except Exception as e:
        logger.error("remember failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def recall(
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search memories using hybrid vector + keyword search.

    Returns memories ranked by relevance with decay and importance factored in.
    Optionally filter by category or tags.
    """
    from .memory import recall as _recall

    try:
        results = _recall(query, category, tags, limit)
        output = []
        for r in results:
            output.append({
                "id": r.memory.id,
                "content": r.memory.content,
                "category": r.memory.category.value,
                "tags": r.memory.tags,
                "importance": r.memory.importance,
                "score": r.score,
                "created_at": r.memory.created_at.isoformat(),
                "access_count": r.memory.access_count,
            })
        return json.dumps({"count": len(output), "memories": output})
    except Exception as e:
        logger.error("recall failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forget(memory_id: str) -> str:
    """Delete a specific memory by ID."""
    from .memory import forget as _forget

    try:
        deleted = _forget(memory_id)
        if deleted:
            return json.dumps({"status": "deleted", "memory_id": memory_id})
        return json.dumps({"status": "not_found", "memory_id": memory_id})
    except Exception as e:
        logger.error("forget failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Profile Tools (2)
# =============================================================================

@mcp.tool()
def profile_get() -> str:
    """Read the full user profile (name, preferences, projects, tools, notes)."""
    from .profile import get_profile

    try:
        profile = get_profile()
        return json.dumps(profile)
    except Exception as e:
        logger.error("profile_get failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def profile_update(section: str, key: str, value: str) -> str:
    """Update a specific field in the user profile.

    Sections: preferences, notes, projects, tools, root (top-level fields).
    For projects/tools, the value is appended to the list.
    """
    from .profile import update_profile

    try:
        profile = update_profile(section, key, value)
        return json.dumps({"status": "updated", "profile": profile})
    except Exception as e:
        logger.error("profile_update failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Task Tools (3)
# =============================================================================

@mcp.tool()
def task_create(
    title: str,
    description: str = "",
    priority: str = "medium",
    project: str = "",
    tags: list[str] | None = None,
    due_date: str | None = None,
) -> str:
    """Create a new task.

    Priority: low, medium, high, critical.
    Due date format: YYYY-MM-DD.
    """
    from .tasks import create_task

    try:
        task = create_task(title, description, priority, project, tags, due_date)
        return json.dumps({
            "status": "created",
            "task_id": task.id,
            "title": task.title,
            "priority": task.priority.value,
            "project": task.project,
        })
    except Exception as e:
        logger.error("task_create failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_update(
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
    due_date: str | None = None,
) -> str:
    """Update a task's fields.

    Status: todo, in_progress, blocked, done, cancelled.
    """
    from .tasks import modify_task

    try:
        fields = {}
        if status is not None:
            fields["status"] = status
        if title is not None:
            fields["title"] = title
        if description is not None:
            fields["description"] = description
        if priority is not None:
            fields["priority"] = priority
        if project is not None:
            fields["project"] = project
        if tags is not None:
            fields["tags"] = tags
        if due_date is not None:
            fields["due_date"] = due_date

        task = modify_task(task_id, **fields)
        if task:
            return json.dumps({
                "status": "updated",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "priority": task.priority.value,
                },
            })
        return json.dumps({"status": "not_found", "task_id": task_id})
    except Exception as e:
        logger.error("task_update failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def task_list(
    status: str | None = None,
    project: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> str:
    """List tasks with optional filters.

    Filter by status (todo/in_progress/blocked/done/cancelled),
    project name, or priority level.
    """
    from .tasks import get_tasks

    try:
        tasks = get_tasks(status, project, priority, limit)
        output = []
        for t in tasks:
            output.append({
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority.value,
                "project": t.project,
                "tags": t.tags,
                "due_date": str(t.due_date) if t.due_date else None,
                "created_at": t.created_at.isoformat(),
            })
        return json.dumps({"count": len(output), "tasks": output})
    except Exception as e:
        logger.error("task_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Session Tools (3)
# =============================================================================

@mcp.tool()
def session_start(title: str = "") -> str:
    """Start a new session. Returns previous session handoff for context continuity.

    Call this at the beginning of each conversation to restore context.
    """
    from .sessions import start_session

    try:
        result = start_session(title)
        return json.dumps(result)
    except Exception as e:
        logger.error("session_start failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def session_end(
    summary: str,
    decisions_made: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> str:
    """End the current session with a summary. Creates a handoff file for the next session.

    Call this before ending a conversation to preserve context.
    """
    from .sessions import end_current_session

    try:
        session = end_current_session(summary, decisions_made, next_steps)
        if session:
            return json.dumps({
                "status": "ended",
                "session_id": session.id,
                "summary": session.summary,
            })
        return json.dumps({"status": "no_active_session"})
    except Exception as e:
        logger.error("session_end failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def session_handoff() -> str:
    """Get the last session's context for continuity.

    Returns the summary, decisions, and next steps from the most recent session.
    """
    from .sessions import get_handoff

    try:
        handoff = get_handoff()
        if handoff:
            return json.dumps(handoff)
        return json.dumps({"status": "no_previous_sessions"})
    except Exception as e:
        logger.error("session_handoff failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Knowledge Tools (3)
# =============================================================================

@mcp.tool()
def knowledge_store(
    title: str,
    content: str,
    category: str = "general",
    tags: list[str] | None = None,
    source: str = "",
) -> str:
    """Store structured knowledge with title, content, category, and optional source.

    Use for reference material, documentation, how-to guides, etc.
    """
    from .knowledge import store_knowledge

    try:
        k = store_knowledge(title, content, category, tags, source)
        return json.dumps({
            "status": "stored",
            "knowledge_id": k.id,
            "title": k.title,
            "category": k.category,
        })
    except Exception as e:
        logger.error("knowledge_store failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_search(
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> str:
    """Search the knowledge base using hybrid vector + keyword search."""
    from .knowledge import search_knowledge_entries

    try:
        results = search_knowledge_entries(query, category, limit)
        output = []
        for r in results:
            output.append({
                "id": r.knowledge.id,
                "title": r.knowledge.title,
                "content": r.knowledge.content,
                "category": r.knowledge.category,
                "tags": r.knowledge.tags,
                "source": r.knowledge.source,
                "score": r.score,
                "created_at": r.knowledge.created_at.isoformat(),
            })
        return json.dumps({"count": len(output), "results": output})
    except Exception as e:
        logger.error("knowledge_search failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def knowledge_update(
    knowledge_id: str,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update a knowledge entry's fields."""
    from .knowledge import modify_knowledge

    try:
        fields = {}
        if title is not None:
            fields["title"] = title
        if content is not None:
            fields["content"] = content
        if category is not None:
            fields["category"] = category
        if tags is not None:
            fields["tags"] = tags

        k = modify_knowledge(knowledge_id, **fields)
        if k:
            return json.dumps({
                "status": "updated",
                "knowledge_id": k.id,
                "title": k.title,
            })
        return json.dumps({"status": "not_found", "knowledge_id": knowledge_id})
    except Exception as e:
        logger.error("knowledge_update failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# SynapseForge Tools (7)
# =============================================================================

@mcp.tool()
def forge_add(
    term: str,
    definition: str,
    category: str = "general",
    difficulty: str = "beginner",
    tags: list[str] | None = None,
    related_jaybrain_component: str = "",
    source: str = "",
    notes: str = "",
) -> str:
    """Quick-capture a concept for spaced repetition learning.

    Categories: python, networking, mcp, databases, security, linux, git, ai_ml, web, devops, general.
    Difficulty: beginner, intermediate, advanced.
    """
    from .forge import add_concept

    try:
        concept = add_concept(
            term, definition, category, difficulty,
            tags or [], related_jaybrain_component, source, notes,
        )
        return json.dumps({
            "status": "added",
            "concept_id": concept.id,
            "term": concept.term,
            "category": concept.category.value,
            "mastery_name": concept.mastery_name,
            "next_review": concept.next_review.isoformat() if concept.next_review else None,
        })
    except Exception as e:
        logger.error("forge_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_review(
    concept_id: str,
    outcome: str,
    confidence: int = 3,
    time_spent_seconds: int = 0,
    notes: str = "",
) -> str:
    """Record a review outcome for a concept.

    Outcome: understood, reviewed, struggled, skipped.
    Confidence: 1-5 (1=no idea, 5=perfect recall).
    """
    from .forge import record_review

    try:
        concept = record_review(concept_id, outcome, confidence, time_spent_seconds, notes)
        return json.dumps({
            "status": "reviewed",
            "concept_id": concept.id,
            "term": concept.term,
            "mastery_level": concept.mastery_level,
            "mastery_name": concept.mastery_name,
            "review_count": concept.review_count,
            "next_review": concept.next_review.isoformat() if concept.next_review else None,
        })
    except Exception as e:
        logger.error("forge_review failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_study(
    category: str | None = None,
    limit: int = 10,
) -> str:
    """Get a prioritized study queue.

    Returns concepts in priority order: due_now > new > struggling > up_next.
    Optionally filter by category.
    """
    from .forge import get_study_queue

    try:
        queue = get_study_queue(category, limit)
        return json.dumps(queue)
    except Exception as e:
        logger.error("forge_study failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_search(
    query: str,
    category: str | None = None,
    difficulty: str | None = None,
    limit: int = 10,
) -> str:
    """Search concepts using hybrid vector + keyword search."""
    from .forge import search_concepts

    try:
        results = search_concepts(query, category, difficulty, limit)
        return json.dumps({"count": len(results), "results": results})
    except Exception as e:
        logger.error("forge_search failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_update(
    concept_id: str,
    term: str | None = None,
    definition: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    tags: list[str] | None = None,
    related_jaybrain_component: str | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> str:
    """Update a concept's fields."""
    from .forge import update_concept

    try:
        fields = {}
        if term is not None:
            fields["term"] = term
        if definition is not None:
            fields["definition"] = definition
        if category is not None:
            fields["category"] = category
        if difficulty is not None:
            fields["difficulty"] = difficulty
        if tags is not None:
            fields["tags"] = tags
        if related_jaybrain_component is not None:
            fields["related_jaybrain_component"] = related_jaybrain_component
        if source is not None:
            fields["source"] = source
        if notes is not None:
            fields["notes"] = notes

        concept = update_concept(concept_id, **fields)
        if concept:
            return json.dumps({
                "status": "updated",
                "concept_id": concept.id,
                "term": concept.term,
                "mastery_name": concept.mastery_name,
            })
        return json.dumps({"status": "not_found", "concept_id": concept_id})
    except Exception as e:
        logger.error("forge_update failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_stats() -> str:
    """Get SynapseForge learning statistics: totals, distributions, streaks, mastery."""
    from .forge import get_forge_stats

    try:
        stats_data = get_forge_stats()
        return json.dumps(stats_data)
    except Exception as e:
        logger.error("forge_stats failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_explain(concept_id: str) -> str:
    """Get full concept details with review history."""
    from .forge import get_concept_detail

    try:
        detail = get_concept_detail(concept_id)
        if detail:
            return json.dumps(detail)
        return json.dumps({"status": "not_found", "concept_id": concept_id})
    except Exception as e:
        logger.error("forge_explain failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# System Tools (3)
# =============================================================================

@mcp.tool()
def stats() -> str:
    """Get JayBrain system statistics: memory/task/session/knowledge counts and storage."""
    try:
        conn = get_connection()
        try:
            s = get_stats(conn)
        finally:
            conn.close()
        return json.dumps(s)
    except Exception as e:
        logger.error("stats failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def context_pack() -> str:
    """Get full startup context: profile + last session handoff + active tasks + recent decisions.

    Call this at the start of every session for complete context restoration.
    """
    from .profile import get_profile
    from .sessions import get_handoff
    from .tasks import get_tasks
    from .memory import recall as _recall

    try:
        profile = get_profile()
        handoff = get_handoff()
        active_tasks = get_tasks(status="todo") + get_tasks(status="in_progress")

        # Get recent decisions
        recent_decisions = []
        try:
            decision_results = _recall("decisions", category="decision", limit=5)
            recent_decisions = [
                {"id": r.memory.id, "content": r.memory.content, "date": r.memory.created_at.isoformat()}
                for r in decision_results
            ]
        except Exception:
            pass

        tasks_output = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority.value,
                "project": t.project,
            }
            for t in active_tasks[:20]
        ]

        # SynapseForge context
        forge_due = []
        forge_streak = 0
        try:
            from .forge import get_study_queue, get_forge_stats
            queue = get_study_queue(limit=5)
            forge_due = queue.get("due_now", [])
            stats_data = get_forge_stats()
            forge_streak = stats_data.get("current_streak", 0)
        except Exception:
            pass

        return json.dumps({
            "profile": profile,
            "last_session": handoff,
            "active_tasks": tasks_output,
            "recent_decisions": recent_decisions,
            "forge_due": forge_due,
            "forge_streak": forge_streak,
        })
    except Exception as e:
        logger.error("context_pack failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_reinforce(memory_id: str) -> str:
    """Boost a memory's importance by incrementing its access count.

    Use this to counteract time-based decay on important memories.
    """
    from .memory import reinforce

    try:
        memory = reinforce(memory_id)
        if memory:
            return json.dumps({
                "status": "reinforced",
                "memory_id": memory.id,
                "access_count": memory.access_count,
            })
        return json.dumps({"status": "not_found", "memory_id": memory_id})
    except Exception as e:
        logger.error("memory_reinforce failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Job Board Tools (3)
# =============================================================================

@mcp.tool()
def job_board_add(
    name: str,
    url: str,
    board_type: str = "general",
    tags: list[str] | None = None,
) -> str:
    """Register a job board URL to monitor.

    Board types: general, niche, company.
    """
    from .job_boards import add_board

    try:
        board = add_board(name, url, board_type, tags)
        return json.dumps({
            "status": "added",
            "board_id": board.id,
            "name": board.name,
            "url": board.url,
            "board_type": board.board_type,
        })
    except Exception as e:
        logger.error("job_board_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def job_board_list(active_only: bool = True) -> str:
    """List all registered job boards with last-checked dates."""
    from .job_boards import get_boards

    try:
        boards = get_boards(active_only=active_only)
        output = []
        for b in boards:
            output.append({
                "id": b.id,
                "name": b.name,
                "url": b.url,
                "board_type": b.board_type,
                "tags": b.tags,
                "active": b.active,
                "last_checked": b.last_checked.isoformat() if b.last_checked else None,
                "created_at": b.created_at.isoformat(),
            })
        return json.dumps({"count": len(output), "boards": output})
    except Exception as e:
        logger.error("job_board_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def job_board_fetch(
    board_id: str,
    max_pages: int = 0,
    render: str = "auto",
) -> str:
    """Fetch a job board URL with smart scraping: SPA detection, pagination, metadata.

    Fetches the page, auto-detects JS-rendered SPAs (Playwright fallback),
    follows pagination links, extracts clean text + OG/JSON-LD metadata.
    Use the returned text to identify job postings, then call job_add() for each.

    render: "auto" (detect SPAs), "always" (force Playwright), "never" (plain HTTP only).
    max_pages: pagination pages to follow (0 = default from config).
    """
    from .job_boards import fetch_board

    try:
        result = fetch_board(board_id, max_pages=max_pages, render=render)
        return json.dumps(result)
    except Exception as e:
        logger.error("job_board_fetch failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Job Posting Tools (3)
# =============================================================================

@mcp.tool()
def job_add(
    title: str,
    company: str,
    url: str = "",
    description: str = "",
    required_skills: list[str] | None = None,
    preferred_skills: list[str] | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    job_type: str = "full_time",
    work_mode: str = "remote",
    location: str = "",
    board_id: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Add a job posting (from scraping or manual entry).

    Job types: full_time, part_time, contract, internship.
    Work modes: remote, hybrid, onsite.
    """
    from .jobs import add_job

    try:
        posting = add_job(
            title, company, url, description,
            required_skills, preferred_skills,
            salary_min, salary_max,
            job_type, work_mode, location, board_id, tags,
        )
        return json.dumps({
            "status": "added",
            "job_id": posting.id,
            "title": posting.title,
            "company": posting.company,
            "work_mode": posting.work_mode.value,
        })
    except Exception as e:
        logger.error("job_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def job_search(
    query: str | None = None,
    company: str | None = None,
    work_mode: str | None = None,
    limit: int = 20,
) -> str:
    """Search saved job postings using full-text search and filters.

    Search by keyword query, company name, or work mode (remote/hybrid/onsite).
    """
    from .jobs import search_jobs

    try:
        postings = search_jobs(query, company, work_mode, limit)
        output = []
        for p in postings:
            output.append({
                "id": p.id,
                "title": p.title,
                "company": p.company,
                "url": p.url,
                "required_skills": p.required_skills,
                "preferred_skills": p.preferred_skills,
                "salary_min": p.salary_min,
                "salary_max": p.salary_max,
                "job_type": p.job_type.value,
                "work_mode": p.work_mode.value,
                "location": p.location,
                "tags": p.tags,
                "created_at": p.created_at.isoformat(),
            })
        return json.dumps({"count": len(output), "postings": output})
    except Exception as e:
        logger.error("job_search failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def job_get(job_id: str) -> str:
    """Get full job posting details including description."""
    from .jobs import get_job

    try:
        posting = get_job(job_id)
        if not posting:
            return json.dumps({"status": "not_found", "job_id": job_id})
        return json.dumps({
            "id": posting.id,
            "title": posting.title,
            "company": posting.company,
            "url": posting.url,
            "description": posting.description,
            "required_skills": posting.required_skills,
            "preferred_skills": posting.preferred_skills,
            "salary_min": posting.salary_min,
            "salary_max": posting.salary_max,
            "job_type": posting.job_type.value,
            "work_mode": posting.work_mode.value,
            "location": posting.location,
            "board_id": posting.board_id,
            "tags": posting.tags,
            "created_at": posting.created_at.isoformat(),
        })
    except Exception as e:
        logger.error("job_get failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Application Tools (3)
# =============================================================================

@mcp.tool()
def app_create(
    job_id: str,
    status: str = "discovered",
    notes: str = "",
    tags: list[str] | None = None,
) -> str:
    """Start tracking an application for a job posting.

    Status: discovered, preparing, ready, applied, interviewing, offered, rejected, withdrawn.
    """
    from .applications import create_application

    try:
        app = create_application(job_id, status, notes, tags)
        return json.dumps({
            "status": "created",
            "application_id": app.id,
            "job_id": app.job_id,
            "app_status": app.status.value,
        })
    except Exception as e:
        logger.error("app_create failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def app_update(
    application_id: str,
    status: str | None = None,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    applied_date: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update an application's status, documents, or notes.

    Status: discovered, preparing, ready, applied, interviewing, offered, rejected, withdrawn.
    Applied date format: YYYY-MM-DD.
    """
    from .applications import modify_application

    try:
        fields = {}
        if status is not None:
            fields["status"] = status
        if resume_path is not None:
            fields["resume_path"] = resume_path
        if cover_letter_path is not None:
            fields["cover_letter_path"] = cover_letter_path
        if applied_date is not None:
            fields["applied_date"] = applied_date
        if notes is not None:
            fields["notes"] = notes
        if tags is not None:
            fields["tags"] = tags

        app = modify_application(application_id, **fields)
        if app:
            return json.dumps({
                "status": "updated",
                "application": {
                    "id": app.id,
                    "job_id": app.job_id,
                    "app_status": app.status.value,
                    "resume_path": app.resume_path,
                    "cover_letter_path": app.cover_letter_path,
                    "applied_date": app.applied_date,
                },
            })
        return json.dumps({"status": "not_found", "application_id": application_id})
    except Exception as e:
        logger.error("app_update failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def app_list(
    status: str | None = None,
    limit: int = 50,
) -> str:
    """List applications with pipeline summary (counts by status).

    Optionally filter by status. Returns both the list and a pipeline dashboard.
    """
    from .applications import get_applications

    try:
        result = get_applications(status=status, limit=limit)
        return json.dumps(result)
    except Exception as e:
        logger.error("app_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Resume & Skills Tools (3)
# =============================================================================

@mcp.tool()
def resume_get_template() -> str:
    """Read the resume template with all HTML comment markers.

    Returns the full template content from the configured path.
    Use the markers to identify tailorable sections.
    """
    from .resume_tailor import get_template

    try:
        result = get_template()
        return json.dumps(result)
    except Exception as e:
        logger.error("resume_get_template failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def resume_analyze_fit(job_id: str) -> str:
    """Compare JJ's skills against a job posting.

    Returns match score, missing skills, and recommendations.
    Uses the resume template's SKILLS section for comparison.
    """
    from .resume_tailor import analyze_fit

    try:
        result = analyze_fit(job_id)
        return json.dumps(result)
    except Exception as e:
        logger.error("resume_analyze_fit failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def resume_save_tailored(company: str, role: str, content: str) -> str:
    """Save a tailored resume as markdown.

    Saves to: Documents/job_search/resumes/Resume_JoshuaBudd_Company_Role.md
    """
    from .resume_tailor import save_tailored_resume

    try:
        result = save_tailored_resume(company, role, content)
        return json.dumps(result)
    except Exception as e:
        logger.error("resume_save_tailored failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Cover Letter & Interview Tools (3)
# =============================================================================

@mcp.tool()
def cover_letter_save(company: str, role: str, content: str) -> str:
    """Save a cover letter as markdown.

    Saves to: Documents/job_search/cover_letters/CoverLetter_JoshuaBudd_Company_Role.md
    """
    from .resume_tailor import save_cover_letter

    try:
        result = save_cover_letter(company, role, content)
        return json.dumps(result)
    except Exception as e:
        logger.error("cover_letter_save failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def interview_prep_add(
    application_id: str,
    prep_type: str = "general",
    content: str = "",
    tags: list[str] | None = None,
) -> str:
    """Save interview prep content for an application.

    Prep types: general, technical, behavioral, company_research.
    """
    from .interview_prep import add_prep

    try:
        prep = add_prep(application_id, prep_type, content, tags)
        return json.dumps({
            "status": "added",
            "prep_id": prep.id,
            "application_id": prep.application_id,
            "prep_type": prep.prep_type.value,
        })
    except Exception as e:
        logger.error("interview_prep_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def interview_prep_get(application_id: str) -> str:
    """Get full interview context: job, application, all prep, profile, resume excerpt.

    Aggregates everything needed to prepare for an interview into one response.
    """
    from .interview_prep import get_prep_context

    try:
        result = get_prep_context(application_id)
        return json.dumps(result)
    except Exception as e:
        logger.error("interview_prep_get failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Server entry point
# =============================================================================

def main():
    """Run the MCP server."""
    logger.info("JayBrain MCP server starting...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
