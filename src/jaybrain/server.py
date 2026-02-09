"""MCP server entry point - all 18 tools for JayBrain."""

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

        return json.dumps({
            "profile": profile,
            "last_session": handoff,
            "active_tasks": tasks_output,
            "recent_decisions": recent_decisions,
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
# Server entry point
# =============================================================================

def main():
    """Run the MCP server."""
    logger.info("JayBrain MCP server starting...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
