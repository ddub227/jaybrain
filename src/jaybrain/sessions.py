"""Session lifecycle and handoff management.

Resilient session tracking:
- Session ID is persisted to disk (survives MCP process restarts)
- Orphaned sessions (started but never ended) are auto-closed on next startup
- get_current_session_id() falls back to disk file and DB lookup
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import SESSIONS_DIR, ACTIVE_SESSION_FILE, ensure_data_dirs
from .db import (
    get_connection, insert_session, end_session,
    get_latest_session, get_session, get_open_sessions,
    update_session_checkpoint, get_memories_for_session,
)
from .models import Session

logger = logging.getLogger(__name__)

# Module-level current session tracker (backed by disk file)
_current_session_id: Optional[str] = None


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _persist_session_id(session_id: Optional[str]) -> None:
    """Write the active session ID to disk so it survives process restarts."""
    try:
        if session_id:
            ACTIVE_SESSION_FILE.write_text(session_id, encoding="utf-8")
        elif ACTIVE_SESSION_FILE.exists():
            ACTIVE_SESSION_FILE.unlink()
    except Exception as e:
        logger.warning("Failed to persist session ID to disk: %s", e)


def _load_session_id_from_disk() -> Optional[str]:
    """Read the active session ID from disk."""
    try:
        if ACTIVE_SESSION_FILE.exists():
            sid = ACTIVE_SESSION_FILE.read_text(encoding="utf-8").strip()
            return sid if sid else None
    except Exception as e:
        logger.warning("Failed to read session ID from disk: %s", e)
    return None


def _parse_session_row(row) -> Session:
    """Convert a database row to a Session model."""
    return Session(
        id=row["id"],
        title=row["title"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=(
            datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None
        ),
        summary=row["summary"],
        decisions_made=json.loads(row["decisions_made"]),
        next_steps=json.loads(row["next_steps"]),
    )


def _write_handoff_markdown(session: Session) -> None:
    """Write a session handoff file for human-readable context transfer."""
    ensure_data_dirs()
    date_str = session.started_at.strftime("%Y-%m-%d")
    filename = f"handoff_{session.id}_{date_str}.md"
    filepath = SESSIONS_DIR / filename

    decisions_text = ""
    if session.decisions_made:
        decisions_text = "\n## Decisions Made\n"
        for d in session.decisions_made:
            decisions_text += f"- {d}\n"

    next_steps_text = ""
    if session.next_steps:
        next_steps_text = "\n## Next Steps\n"
        for n in session.next_steps:
            next_steps_text += f"- [ ] {n}\n"

    content = (
        f"# Session Handoff: {session.title or 'Untitled'}\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| **Session ID** | {session.id} |\n"
        f"| **Started** | {session.started_at.isoformat()} |\n"
        f"| **Ended** | {session.ended_at.isoformat() if session.ended_at else 'N/A'} |\n"
        f"\n## Summary\n{session.summary}\n"
        f"{decisions_text}"
        f"{next_steps_text}"
    )

    filepath.write_text(content, encoding="utf-8")


def _build_recovery_summary(conn, session_id: str, started_at: str) -> tuple[str, list[str], list[str]]:
    """Build the best possible summary for an orphaned session.

    Uses data sources in priority order:
    1. Checkpoint data (highest quality - saved by Claude mid-session)
    2. Pulse activity log + memories (medium quality)
    3. Generic fallback (lowest quality)

    Returns (summary, decisions_made, next_steps).
    """
    summary_parts = []
    decisions = []
    next_steps = []

    # Source 1: Checkpoint data (best quality)
    try:
        row = get_session(conn, session_id)
        if row:
            cp_summary = row["checkpoint_summary"] if "checkpoint_summary" in row.keys() else ""
            cp_decisions = row["checkpoint_decisions"] if "checkpoint_decisions" in row.keys() else "[]"
            cp_next_steps = row["checkpoint_next_steps"] if "checkpoint_next_steps" in row.keys() else "[]"
            cp_at = row["checkpoint_at"] if "checkpoint_at" in row.keys() else None

            if cp_summary:
                summary_parts.append(f"Last checkpoint: {cp_summary}")
                decisions = json.loads(cp_decisions) if cp_decisions else []
                next_steps = json.loads(cp_next_steps) if cp_next_steps else []
                if cp_at:
                    summary_parts.append(f"Checkpoint saved at {cp_at}.")
    except Exception as e:
        logger.debug("Checkpoint recovery failed for %s: %s", session_id, e)

    # Source 2: Pulse activity log (tool usage timeline)
    try:
        pulse_rows = conn.execute(
            """SELECT tool_count, last_tool, last_heartbeat, status, cwd
            FROM claude_sessions WHERE session_id LIKE ?
            ORDER BY last_heartbeat DESC LIMIT 1""",
            (f"%{session_id[:8]}%",),
        ).fetchone()
        if pulse_rows:
            tool_count = pulse_rows["tool_count"] or 0
            last_tool = pulse_rows["last_tool"] or "unknown"
            if tool_count > 0:
                summary_parts.append(
                    f"{tool_count} tool calls. Last tool: {last_tool}."
                )
    except Exception as e:
        logger.debug("Pulse recovery failed for %s: %s", session_id, e)

    # Source 3: Memories created during this session
    try:
        memories = get_memories_for_session(conn, session_id, limit=10)
        if memories:
            mem_categories = {}
            for m in memories:
                cat = m["category"]
                mem_categories[cat] = mem_categories.get(cat, 0) + 1
            cat_summary = ", ".join(f"{v} {k}" for k, v in mem_categories.items())
            summary_parts.append(f"Memories saved: {cat_summary}.")
    except Exception as e:
        logger.debug("Memory recovery failed for %s: %s", session_id, e)

    # Compose final summary
    if summary_parts:
        tag = "[Auto-recovered]"
        summary = f"{tag} Session started at {started_at}. " + " ".join(summary_parts)
    else:
        tag = "[Auto-closed]"
        summary = f"{tag} Session terminated unexpectedly. Started at {started_at}."

    if not next_steps:
        next_steps = ["Review what was discussed in this session"]

    return summary, decisions, next_steps


def _close_orphaned_sessions(conn) -> list[str]:
    """Find and auto-close any sessions that were started but never ended.

    Uses smart recovery to build meaningful summaries from checkpoints,
    Pulse activity, and memories rather than generic messages.

    Returns list of closed session IDs.
    """
    orphans = get_open_sessions(conn)
    closed = []
    for row in orphans:
        sid = row["id"]
        started = row["started_at"]

        summary, decisions, next_steps = _build_recovery_summary(conn, sid, started)

        end_session(
            conn, sid,
            summary=summary,
            decisions_made=decisions,
            next_steps=next_steps,
        )
        closed.append(sid)
        logger.info("Auto-closed orphaned session: %s (started %s)", sid, started)

        # Write handoff for the orphan
        try:
            closed_row = get_session(conn, sid)
            if closed_row:
                _write_handoff_markdown(_parse_session_row(closed_row))
        except Exception as e:
            logger.warning("Failed to write handoff for orphaned session %s: %s", sid, e)

    return closed


def start_session(title: str = "") -> dict:
    """Start a new session. Auto-closes orphans. Returns previous session handoff."""
    global _current_session_id

    conn = get_connection()
    try:
        # Auto-close any orphaned sessions first
        closed_orphans = _close_orphaned_sessions(conn)

        # Get previous session for context (most recent completed one)
        previous = get_latest_session(conn)
        previous_context = None
        if previous and previous["ended_at"]:
            prev_session = _parse_session_row(previous)
            previous_context = {
                "id": prev_session.id,
                "title": prev_session.title,
                "summary": prev_session.summary,
                "decisions_made": prev_session.decisions_made,
                "next_steps": prev_session.next_steps,
                "ended_at": prev_session.ended_at.isoformat() if prev_session.ended_at else None,
            }

        # Create new session
        session_id = _generate_id()
        insert_session(conn, session_id, title)

        # Persist to memory AND disk
        _current_session_id = session_id
        _persist_session_id(session_id)

        result = {
            "session_id": session_id,
            "title": title,
            "previous_session": previous_context,
        }
        if closed_orphans:
            result["closed_orphans"] = closed_orphans
        return result
    finally:
        conn.close()


def end_current_session(
    summary: str,
    decisions_made: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
) -> Optional[Session]:
    """End the current session with a summary and create a handoff file."""
    global _current_session_id

    decisions_made = decisions_made or []
    next_steps = next_steps or []

    conn = get_connection()
    try:
        # Find current session: memory -> disk -> DB fallback
        session_id = _current_session_id
        if not session_id:
            session_id = _load_session_id_from_disk()
        if not session_id:
            # Last resort: find the latest open session
            latest = get_latest_session(conn)
            if latest and not latest["ended_at"]:
                session_id = latest["id"]
            else:
                return None

        end_session(conn, session_id, summary, decisions_made, next_steps)
        row = get_session(conn, session_id)
        if not row:
            return None

        session = _parse_session_row(row)

        # Clear from memory AND disk
        _current_session_id = None
        _persist_session_id(None)

        # Write handoff markdown
        try:
            _write_handoff_markdown(session)
        except Exception as e:
            logger.warning("Failed to write handoff file: %s", e)

        return session
    finally:
        conn.close()


def get_handoff() -> Optional[dict]:
    """Get the last completed session's context for handoff."""
    conn = get_connection()
    try:
        latest = get_latest_session(conn)
        if not latest:
            return None

        session = _parse_session_row(latest)
        return {
            "id": session.id,
            "title": session.title,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "summary": session.summary,
            "decisions_made": session.decisions_made,
            "next_steps": session.next_steps,
            "is_active": session.ended_at is None,
        }
    finally:
        conn.close()


def checkpoint_session(
    summary: str,
    decisions_made: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
) -> Optional[dict]:
    """Save a rolling checkpoint for the current session without closing it.

    Updates checkpoint columns in-place (not append-only).
    Returns checkpoint info or None if no active session.
    """
    decisions_made = decisions_made or []
    next_steps = next_steps or []

    conn = get_connection()
    try:
        # Find current session: memory -> disk -> DB fallback
        session_id = _current_session_id
        if not session_id:
            session_id = _load_session_id_from_disk()
        if not session_id:
            latest = get_latest_session(conn)
            if latest and not latest["ended_at"]:
                session_id = latest["id"]
            else:
                return None

        updated = update_session_checkpoint(
            conn, session_id, summary, decisions_made, next_steps,
        )
        if updated:
            return {
                "session_id": session_id,
                "checkpoint_summary": summary,
                "checkpoint_decisions": decisions_made,
                "checkpoint_next_steps": next_steps,
            }
        return None
    finally:
        conn.close()


def get_current_session_id() -> Optional[str]:
    """Get the current active session ID.

    Falls back to disk file if the in-memory value is None (e.g. after
    MCP process restart mid-session).
    """
    global _current_session_id

    if _current_session_id:
        return _current_session_id

    # Fallback 1: check disk
    disk_id = _load_session_id_from_disk()
    if disk_id:
        # Validate it's actually still open in the DB
        conn = get_connection()
        try:
            row = get_session(conn, disk_id)
            if row and not row["ended_at"]:
                _current_session_id = disk_id
                return disk_id
            else:
                # Stale file — clean up
                _persist_session_id(None)
        finally:
            conn.close()

    # Fallback 2: find the latest open session in DB
    conn = get_connection()
    try:
        open_sessions = get_open_sessions(conn)
        if open_sessions:
            sid = open_sessions[0]["id"]
            _current_session_id = sid
            _persist_session_id(sid)
            return sid
    finally:
        conn.close()

    return None
