"""MCP server entry point - all tools for JayBrain."""

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
            result = {
                "status": "updated",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "priority": task.priority.value,
                },
            }

            # Auto-resurface: when a task is marked done/cancelled, remove it
            # from the queue and suggest the next item
            if status in ("done", "cancelled"):
                try:
                    from .queue import get_next_suggestion
                    from .db import get_connection, clear_queue_position, reindex_queue

                    conn = get_connection()
                    try:
                        clear_queue_position(conn, task_id)
                        reindex_queue(conn)
                    finally:
                        conn.close()

                    next_task = get_next_suggestion()
                    if next_task:
                        result["next_in_queue"] = next_task
                        result["queue_hint"] = (
                            f"Next up: {next_task['title']} (#{next_task['queue_position']})"
                        )
                except Exception:
                    pass  # Queue suggestion is best-effort

            return json.dumps(result)
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
# Task Queue Tools (7)
# =============================================================================

@mcp.tool()
def queue_next() -> str:
    """Returns the next task in the queue (lowest queue_position that's not done/cancelled).

    This is the "what should I do next?" command.
    """
    from .queue import queue_next as _queue_next

    try:
        result = _queue_next()
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_next failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_push(task_id: str, position: int | None = None) -> str:
    """Add a task to the queue.

    If position is None, adds to the end of the queue.
    If position is given, inserts there and shifts others down.
    """
    from .queue import queue_push as _queue_push

    try:
        result = _queue_push(task_id, position)
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_push failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_pop() -> str:
    """Mark the current top task as in_progress and return it.

    Removes it from the queue and sets its status to in_progress.
    Use this to start working on the next queued task.
    """
    from .queue import queue_pop as _queue_pop

    try:
        result = _queue_pop()
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_pop failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_reorder(task_ids: list[str]) -> str:
    """Reorder the queue by providing task IDs in the desired order.

    Tasks not in the provided list but currently in the queue
    will be appended after the specified tasks.
    """
    from .queue import queue_reorder as _queue_reorder

    try:
        result = _queue_reorder(task_ids)
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_reorder failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_view() -> str:
    """Show the full task queue in order.

    Displays all queued tasks sorted by position, excluding
    done and cancelled tasks.
    """
    from .queue import queue_view as _queue_view

    try:
        result = _queue_view()
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_view failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_defer(task_id: str) -> str:
    """Move a task to the end of the queue (when going on a tangent).

    Pushes the task to the back and shows what's next.
    """
    from .queue import queue_defer as _queue_defer

    try:
        result = _queue_defer(task_id)
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_defer failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def queue_bump(task_id: str) -> str:
    """Move a task to position 1 (urgent).

    Bumps the task to the front of the queue, shifting everything else down.
    Works even if the task is not currently in the queue.
    """
    from .queue import queue_bump as _queue_bump

    try:
        result = _queue_bump(task_id)
        return json.dumps(result)
    except Exception as e:
        logger.error("queue_bump failed: %s", e, exc_info=True)
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
    subject_id: str = "",
    bloom_level: str = "remember",
) -> str:
    """Quick-capture a concept for spaced repetition learning.

    Categories: python, networking, mcp, databases, security, linux, git, ai_ml, web, devops, general.
    Difficulty: beginner, intermediate, advanced.
    Bloom levels: remember, understand, apply, analyze.
    """
    from .forge import add_concept

    try:
        concept = add_concept(
            term, definition, category, difficulty,
            tags or [], related_jaybrain_component, source, notes,
            subject_id=subject_id, bloom_level=bloom_level,
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
    was_correct: bool | None = None,
    error_type: str = "",
    bloom_level: str = "",
) -> str:
    """Record a review outcome for a concept.

    Outcome: understood, reviewed, struggled, skipped.
    Confidence: 1-5 (1=no idea, 5=perfect recall).
    v2: Pass was_correct (true/false) for confidence-weighted scoring.
    Error types: slip, lapse, mistake, misconception (auto-classified if omitted).
    Bloom levels: remember, understand, apply, analyze.
    """
    from .forge import record_review

    try:
        concept = record_review(
            concept_id, outcome, confidence, time_spent_seconds, notes,
            was_correct=was_correct, error_type=error_type, bloom_level=bloom_level,
        )
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
    subject_id: str | None = None,
) -> str:
    """Get a prioritized study queue.

    Without subject_id: due_now > new > struggling > up_next ordering.
    With subject_id: interleaved queue weighted by exam_weight * (1 - mastery).
    """
    from .forge import get_study_queue

    try:
        queue = get_study_queue(category, limit, subject_id=subject_id)
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
# SynapseForge v2 Tools (7)
# =============================================================================

@mcp.tool()
def forge_subject_create(
    name: str,
    short_name: str,
    description: str = "",
    pass_score: float = 0.0,
    total_questions: int = 0,
    time_limit_minutes: int = 0,
) -> str:
    """Create a new learning subject (e.g. an exam, a course).

    pass_score: 0.0-1.0 (e.g. 0.833 for 750/900 on Security+).
    """
    from .forge import create_subject

    try:
        subject = create_subject(
            name, short_name, description,
            pass_score, total_questions, time_limit_minutes,
        )
        return json.dumps({"status": "created", **subject})
    except Exception as e:
        logger.error("forge_subject_create failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_subject_list() -> str:
    """List all learning subjects with concept and objective counts."""
    from .forge import get_subjects

    try:
        subjects = get_subjects()
        return json.dumps({"count": len(subjects), "subjects": subjects})
    except Exception as e:
        logger.error("forge_subject_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_objective_add(
    subject_id: str,
    code: str,
    title: str,
    domain: str = "",
    exam_weight: float = 0.0,
) -> str:
    """Add an exam objective to a subject.

    code: e.g. '1.1', '2.3'. domain: e.g. '1.0 - General Security Concepts'.
    exam_weight: domain weight as decimal (e.g. 0.12 for 12%).
    """
    from .forge import add_objective

    try:
        obj = add_objective(subject_id, code, title, domain, exam_weight)
        return json.dumps({"status": "added", **obj})
    except Exception as e:
        logger.error("forge_objective_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_readiness(subject_id: str) -> str:
    """Get exam readiness score with domain breakdown and recommendations.

    Returns overall pass probability, per-domain and per-objective mastery,
    weakest areas, coverage, calibration score, and study recommendation.
    """
    from .forge import calculate_readiness

    try:
        readiness = calculate_readiness(subject_id)
        return json.dumps(readiness)
    except Exception as e:
        logger.error("forge_readiness failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_knowledge_map(subject_id: str) -> str:
    """Generate a markdown knowledge map for a subject.

    Shows all domains, objectives, and concepts organized hierarchically
    with mastery bars, review counts, and error patterns.
    """
    from .forge import generate_knowledge_map

    try:
        markdown = generate_knowledge_map(subject_id)
        return json.dumps({"status": "generated", "markdown": markdown})
    except Exception as e:
        logger.error("forge_knowledge_map failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_calibration(subject_id: str = "") -> str:
    """Get calibration analytics: how well confidence predicts actual performance.

    Returns 4-quadrant breakdown (confident+correct, confident+wrong,
    unsure+correct, unsure+wrong), calibration score, and over/under-confidence rates.
    """
    from .forge import get_calibration

    try:
        cal = get_calibration(subject_id)
        return json.dumps(cal)
    except Exception as e:
        logger.error("forge_calibration failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def forge_errors(
    subject_id: str = "",
    concept_id: str = "",
) -> str:
    """Get error pattern analysis: misconceptions, slips, lapses, mistakes.

    Filter by subject_id and/or concept_id. Shows error type distribution
    and concepts with recurring errors.
    """
    from .forge import get_error_analysis

    try:
        analysis = get_error_analysis(subject_id, concept_id)
        return json.dumps(analysis)
    except Exception as e:
        logger.error("forge_errors failed: %s", e, exc_info=True)
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
    """Save a tailored resume as markdown and create a Google Doc.

    Saves locally to: Documents/job_search/resumes/Resume_JoshuaBudd_Company_Role.md
    Also creates a formatted Google Doc shared with JJ and returns its URL.
    If Google Docs is unavailable, the local save still succeeds.
    """
    from .resume_tailor import save_tailored_resume

    try:
        result = save_tailored_resume(company, role, content)
        return json.dumps(result)
    except Exception as e:
        logger.error("resume_save_tailored failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Google Docs Tools (1)
# =============================================================================

@mcp.tool()
def gdoc_create(
    title: str,
    content: str,
    folder_id: str = "",
    share_with: str = "",
) -> str:
    """Create a formatted Google Doc from markdown content.

    Converts markdown (headings, bold, italic, bullets, rules) into a
    styled Google Doc. Shares with JJ by default.

    Args:
        title: Document title.
        content: Markdown-formatted content.
        folder_id: Optional Drive folder ID (uses default if empty).
        share_with: Optional email to share with (uses default if empty).

    Returns doc_id, doc_url, and title on success.
    """
    from .gdocs import create_google_doc

    try:
        result = create_google_doc(title, content, folder_id, share_with)
        return json.dumps(result)
    except Exception as e:
        logger.error("gdoc_create failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Cover Letter & Interview Tools (3)
# =============================================================================

@mcp.tool()
def cover_letter_save(company: str, role: str, content: str) -> str:
    """Save a cover letter as markdown and create a Google Doc.

    Saves locally to: Documents/job_search/cover_letters/CoverLetter_JoshuaBudd_Company_Role.md
    Also creates a formatted Google Doc shared with JJ and returns its URL.
    If Google Docs is unavailable, the local save still succeeds.
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
# Memory Consolidation Tools (5)
# =============================================================================

@mcp.tool()
def memory_find_clusters(
    min_similarity: float = 0.80,
    max_age_days: int | None = None,
    category: str | None = None,
    limit: int = 10,
) -> str:
    """Find clusters of semantically similar memories for review and merging.

    Uses pairwise cosine similarity to group related memories.
    Review the returned clusters, then call memory_merge() to consolidate.

    min_similarity: 0.0-1.0 threshold (default 0.80).
    max_age_days: only consider memories created within N days.
    """
    from .consolidation import find_clusters

    try:
        clusters = find_clusters(min_similarity, max_age_days, category, limit)
        return json.dumps({
            "cluster_count": len(clusters),
            "clusters": clusters,
        })
    except Exception as e:
        logger.error("memory_find_clusters failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_find_duplicates(
    threshold: float = 0.92,
    category: str | None = None,
    limit: int = 20,
) -> str:
    """Find near-duplicate memory pairs above the similarity threshold.

    Returns pairs sorted by similarity (highest first).
    Use memory_merge() or memory_archive() to clean up duplicates.

    threshold: 0.0-1.0 (default 0.92 for near-exact matches).
    """
    from .consolidation import find_duplicates

    try:
        pairs = find_duplicates(threshold, category, limit)
        return json.dumps({
            "pair_count": len(pairs),
            "pairs": pairs,
        })
    except Exception as e:
        logger.error("memory_find_duplicates failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_merge(
    memory_ids: list[str],
    merged_content: str,
    merged_tags: list[str] | None = None,
    merged_importance: float | None = None,
    reason: str = "",
) -> str:
    """Merge multiple memories into one consolidated memory.

    Provide the merged_content (a rewritten summary combining the originals).
    Original memories are archived with an audit trail.
    Tags and importance are auto-derived from originals if not specified.
    """
    from .consolidation import merge_memories

    try:
        result = merge_memories(
            memory_ids, merged_content, merged_tags, merged_importance, reason,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("memory_merge failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_archive(
    memory_ids: list[str],
    reason: str = "manual_archive",
) -> str:
    """Archive multiple memories (soft delete) without merging.

    Archived memories are removed from search but preserved in the archive table.
    Use for outdated, irrelevant, or superseded memories.
    """
    from .consolidation import archive_memories

    try:
        result = archive_memories(memory_ids, reason)
        return json.dumps(result)
    except Exception as e:
        logger.error("memory_archive failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def memory_consolidation_stats() -> str:
    """Get consolidation history: archive counts, merge logs, and action breakdown."""
    from .consolidation import get_consolidation_stats

    try:
        result = get_consolidation_stats()
        return json.dumps(result)
    except Exception as e:
        logger.error("memory_consolidation_stats failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Knowledge Graph Tools (5)
# =============================================================================

@mcp.tool()
def graph_add_entity(
    name: str,
    entity_type: str,
    description: str = "",
    aliases: list[str] | None = None,
    source_memory_ids: list[str] | None = None,
    properties: dict | None = None,
) -> str:
    """Add or update an entity in the knowledge graph.

    If an entity with the same name+type exists, merges aliases, memory_ids, and properties.
    Entity types: person, project, tool, skill, company, concept, location, organization.
    """
    from .graph import add_entity

    try:
        result = add_entity(
            name, entity_type, description,
            aliases, source_memory_ids, properties,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("graph_add_entity failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def graph_add_relationship(
    source_entity: str,
    target_entity: str,
    rel_type: str,
    weight: float = 1.0,
    evidence_ids: list[str] | None = None,
    properties: dict | None = None,
) -> str:
    """Add or update a relationship between two entities.

    Entities can be referenced by ID or name. If the same triple exists, merges evidence and properties.
    Relationship types: uses, knows, related_to, part_of, depends_on, works_at, created_by, collaborates_with, learned_from.
    """
    from .graph import add_relationship

    try:
        result = add_relationship(
            source_entity, target_entity, rel_type,
            weight, evidence_ids, properties,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("graph_add_relationship failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def graph_query(
    entity_name: str,
    depth: int = 1,
    entity_type: str | None = None,
) -> str:
    """Get an entity and its N-depth neighborhood via BFS traversal.

    Returns the center entity, all connected entities within depth hops,
    and all relationships between them. Max depth: 3.
    """
    from .graph import query_neighborhood

    try:
        result = query_neighborhood(entity_name, depth, entity_type)
        return json.dumps(result)
    except Exception as e:
        logger.error("graph_query failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def graph_search(
    query: str,
    entity_type: str | None = None,
    limit: int = 20,
) -> str:
    """Search entities by name substring."""
    from .graph import search_entities

    try:
        results = search_entities(query, entity_type, limit)
        return json.dumps({"count": len(results), "entities": results})
    except Exception as e:
        logger.error("graph_search failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def graph_list(
    entity_type: str | None = None,
    limit: int = 100,
) -> str:
    """List all entities in the knowledge graph, optionally filtered by type."""
    from .graph import get_entities

    try:
        results = get_entities(entity_type, limit)
        return json.dumps({"count": len(results), "entities": results})
    except Exception as e:
        logger.error("graph_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Homelab Tools (7)
# =============================================================================

@mcp.tool()
def homelab_status() -> str:
    """Quick stats, skills, SOC readiness, recent entries from the homelab journal.

    Parses JOURNAL_INDEX.md for lab session count, skills progression,
    SOC Analyst readiness checklist, and recent journal entries.
    """
    from .homelab import get_status

    try:
        result = get_status()
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_status failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_journal_create(date: str, content: str) -> str:
    """Create a journal entry file and update JOURNAL_INDEX.md.

    Claude should read the Codex first (homelab_codex_read), compose the
    full markdown entry following its rules, then pass the finished content here.
    The tool handles file write, directory creation, and index update.

    date: ISO date string (YYYY-MM-DD).
    content: Full pre-formatted markdown content.
    """
    from .homelab import create_journal_entry

    try:
        result = create_journal_entry(date, content)
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_journal_create failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_journal_list(limit: int = 10) -> str:
    """List recent journal entries from JOURNAL_INDEX.md."""
    from .homelab import list_journal_entries

    try:
        result = list_journal_entries(limit)
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_journal_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_tools_list(status: str | None = None) -> str:
    """Read HOMELAB_TOOLS_INVENTORY.csv, optionally filtered by status.

    Status values: Deployed, Planned, Deprecated.
    """
    from .homelab import list_tools

    try:
        result = list_tools(status)
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_tools_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_tools_add(
    tool: str,
    creator: str,
    purpose: str,
    status: str = "Deployed",
) -> str:
    """Add a new tool to HOMELAB_TOOLS_INVENTORY.csv.

    Checks for duplicates before adding. Status: Deployed, Planned, Deprecated.
    """
    from .homelab import add_tool

    try:
        result = add_tool(tool, creator, purpose, status)
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_tools_add failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_nexus_read() -> str:
    """Read the full LAB_NEXUS.md infrastructure overview.

    Contains network topology, VM specs, service inventory, and architecture diagrams.
    """
    from .homelab import read_nexus

    try:
        result = read_nexus()
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_nexus_read failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def homelab_codex_read() -> str:
    """Read the LABSCRIBE_CODEX.md formatting rules.

    Contains journal entry structure, section templates, trigger commands,
    and style rules. Read this before composing journal entries.
    """
    from .homelab import read_codex

    try:
        result = read_codex()
        return json.dumps(result)
    except Exception as e:
        logger.error("homelab_codex_read failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Browser Automation Tools (8)
# =============================================================================

# =============================================================================
# Pulse: Cross-Session Awareness Tools (3)
# =============================================================================

@mcp.tool()
def pulse_active(stale_minutes: int = 60) -> str:
    """List all active Claude Code sessions and what they're doing.

    Shows session IDs, working directories, last tool used, and time since
    last activity. Use this to see what other sessions are currently up to.

    stale_minutes: sessions idle longer than this get a warning (default 60).
    """
    from .pulse import get_active_sessions

    try:
        result = get_active_sessions(stale_minutes)
        return json.dumps(result)
    except Exception as e:
        logger.error("pulse_active failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def pulse_activity(session_id: str | None = None, limit: int = 20) -> str:
    """Get recent activity stream across all sessions or a specific one.

    Returns a chronological feed of tool calls with timestamps.
    Omit session_id to see activity across ALL sessions.
    """
    from .pulse import get_session_activity

    try:
        result = get_session_activity(session_id, limit)
        return json.dumps(result)
    except Exception as e:
        logger.error("pulse_activity failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def pulse_session(session_id: str) -> str:
    """Get full details on a specific session: tool usage breakdown, recent activity.

    Supports partial session ID matching.
    """
    from .pulse import query_session

    try:
        result = query_session(session_id)
        return json.dumps(result)
    except Exception as e:
        logger.error("pulse_session failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def pulse_context(
    session_id: str,
    snippet: str = "",
    last_n: int = 30,
    context_window: int = 10,
) -> str:
    """Read another session's full conversation transcript. Codename: X-Ray.

    Reads the JSONL transcript file from another Claude Code session and
    returns the actual user/assistant conversation (filtered, no noise).

    Two modes:
    - Snippet mode: pass `snippet` text to find it in the transcript and
      get surrounding context (context_window turns before and after).
    - Recent mode: omit snippet to get the last `last_n` turns plus the
      session opening (first 3 turns showing the session plan).

    Supports partial session ID matching. Use pulse_active() first to
    discover session IDs.
    """
    from .pulse import get_session_context

    try:
        result = get_session_context(
            session_id,
            snippet=snippet if snippet else None,
            last_n=last_n,
            context_window=context_window,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("pulse_context (X-Ray) failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_launch(
    headless: bool = True,
    url: str = "",
    stealth: bool = False,
) -> str:
    """Launch a Chromium browser instance.

    headless: True for background operation, False for visible window.
    url: Optional URL to navigate to immediately after launch.
    stealth: Use Patchright anti-bot mode to bypass detection (requires: pip install patchright).
    Requires: pip install jaybrain[render] && playwright install chromium
    """
    from .browser import launch_browser

    try:
        result = launch_browser(headless=headless, url=url, stealth=stealth)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_launch failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL.

    Waits for DOM content to load before returning.
    """
    from .browser import navigate

    try:
        result = navigate(url)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_navigate failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_snapshot() -> str:
    """Get the page's accessibility tree with numbered element refs.

    Returns a text representation of the page structure. Interactive
    elements (links, buttons, inputs) get [ref] numbers you can pass
    to browser_click() or browser_type().
    """
    from .browser import snapshot

    try:
        result = snapshot()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_snapshot failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_screenshot(full_page: bool = False) -> str:
    """Take a screenshot of the current page.

    Returns the file path to the saved PNG image.
    Use the Read tool on the returned path to view the screenshot.
    full_page: True to capture the entire scrollable page.
    """
    from .browser import take_screenshot

    try:
        result = take_screenshot(full_page=full_page)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_screenshot failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_click(
    ref: int | None = None,
    selector: str | None = None,
) -> str:
    """Click an element on the page.

    ref: Element number from browser_snapshot() output (e.g. 3 for [3]).
    selector: CSS selector as fallback (e.g. '#submit-btn').
    Provide one of ref or selector.
    """
    from .browser import click

    try:
        result = click(ref=ref, selector=selector)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_click failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_type(
    text: str,
    ref: int | None = None,
    selector: str | None = None,
    clear: bool = True,
) -> str:
    """Type text into an input field.

    text: The text to type.
    ref: Element number from browser_snapshot() (e.g. 5 for [5]).
    selector: CSS selector as fallback.
    clear: If True (default), clears the field first. False to append.
    """
    from .browser import type_text

    try:
        result = type_text(text, ref=ref, selector=selector, clear=clear)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_type failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_press_key(key: str) -> str:
    """Press a keyboard key.

    Common keys: Enter, Tab, Escape, Backspace, ArrowDown, ArrowUp,
    Space, Delete, Home, End, PageDown, PageUp.
    Modifiers: Control+a, Shift+Tab, Alt+F4.
    """
    from .browser import press_key

    try:
        result = press_key(key)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_press_key failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_close() -> str:
    """Close the browser and release all resources."""
    from .browser import close_browser

    try:
        result = close_browser()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_close failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Browser Session & Advanced Tools (6)
# =============================================================================

@mcp.tool()
def browser_session_save(name: str) -> str:
    """Save the current browser session (cookies + localStorage) to a named file.

    Use this to persist login state so you can restore it later
    without re-authenticating.
    """
    from .browser import session_save

    try:
        result = session_save(name)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_session_save failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_session_load(
    name: str,
    headless: bool | None = None,
    url: str = "",
    stealth: bool | None = None,
) -> str:
    """Launch browser with a previously saved session (restores cookies + localStorage).

    name: Session name used in browser_session_save().
    headless: Override headless mode (None keeps previous setting).
    url: Optional URL to navigate to after loading.
    stealth: Use Patchright anti-bot mode (None keeps previous setting).
    """
    from .browser import session_load

    try:
        result = session_load(name, headless=headless, url=url, stealth=stealth)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_session_load failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_session_list() -> str:
    """List all saved browser sessions with cookie counts and sizes."""
    from .browser import session_list

    try:
        result = session_list()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_session_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_fill_from_bw(
    item_name: str,
    field: str = "password",
    ref: int | None = None,
    selector: str | None = None,
) -> str:
    """Securely fill a form field with a credential from Bitwarden CLI.

    Fetches the credential and types it in one atomic operation.
    The actual value never appears in the response or logs.

    item_name: Bitwarden item name (e.g. 'github.com').
    field: 'password', 'username', 'uri', or 'totp'.
    ref: Element number from browser_snapshot().
    selector: CSS selector as fallback.
    Requires: bw CLI installed and vault unlocked (BW_SESSION set).
    """
    from .browser import fill_from_bw

    try:
        result = fill_from_bw(item_name, field, ref=ref, selector=selector)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_fill_from_bw failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_select_option(
    ref: int | None = None,
    selector: str | None = None,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
) -> str:
    """Select an option from a dropdown (<select> element).

    ref/selector: Identify the dropdown.
    Then provide ONE of: value (option value attr), label (visible text), or index (0-based).
    """
    from .browser import select_option

    try:
        result = select_option(
            ref=ref, selector=selector,
            value=value, label=label, index=index,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_select_option failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_wait(
    selector: str | None = None,
    text: str | None = None,
    state: str = "visible",
    timeout: int = 10000,
) -> str:
    """Wait for an element or text to appear/disappear on the page.

    selector: CSS selector to wait for.
    text: Text content to wait for.
    state: 'visible' (default), 'hidden', 'attached', 'detached'.
    timeout: Max wait time in milliseconds (default 10000).
    """
    from .browser import wait_for

    try:
        result = wait_for(
            selector=selector, text=text,
            state=state, timeout=timeout,
        )
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_wait failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_hover(
    ref: int | None = None,
    selector: str | None = None,
) -> str:
    """Hover over an element (useful for revealing dropdown menus or tooltips).

    ref: Element number from browser_snapshot().
    selector: CSS selector as fallback.
    """
    from .browser import hover

    try:
        result = hover(ref=ref, selector=selector)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_hover failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# =============================================================================
# Browser Navigation, Tabs & JS Tools (7)
# =============================================================================

@mcp.tool()
def browser_evaluate(expression: str) -> str:
    """Evaluate a JavaScript expression in the page context.

    Returns the result as a string. Useful for reading page state,
    extracting data, or manipulating the DOM.
    """
    from .browser import evaluate_js

    try:
        result = evaluate_js(expression)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_evaluate failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_go_back() -> str:
    """Navigate back in browser history (like clicking the back button)."""
    from .browser import go_back

    try:
        result = go_back()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_go_back failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_go_forward() -> str:
    """Navigate forward in browser history."""
    from .browser import go_forward

    try:
        result = go_forward()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_go_forward failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_tab_list() -> str:
    """List all open browser tabs with URLs and titles.

    Shows which tab is currently active.
    """
    from .browser import tab_list

    try:
        result = tab_list()
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_tab_list failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_tab_new(url: str = "") -> str:
    """Open a new browser tab, optionally navigating to a URL.

    The new tab becomes the active tab.
    """
    from .browser import tab_new

    try:
        result = tab_new(url=url)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_tab_new failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_tab_switch(index: int) -> str:
    """Switch to a tab by index (use browser_tab_list to see indexes)."""
    from .browser import tab_switch

    try:
        result = tab_switch(index)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_tab_switch failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def browser_tab_close(index: int | None = None) -> str:
    """Close a tab by index, or close the current tab if no index given.

    Automatically switches to the last remaining tab after closing.
    """
    from .browser import tab_close

    try:
        result = tab_close(index=index)
        return json.dumps(result)
    except Exception as e:
        logger.error("browser_tab_close failed: %s", e, exc_info=True)
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
