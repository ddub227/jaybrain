"""Session lifecycle and handoff management."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import SESSIONS_DIR, ensure_data_dirs
from .db import get_connection, insert_session, end_session, get_latest_session, get_session
from .models import Session

logger = logging.getLogger(__name__)

# Module-level current session tracker
_current_session_id: Optional[str] = None


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


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


def start_session(title: str = "") -> dict:
    """Start a new session. Returns previous session handoff if available."""
    global _current_session_id

    conn = get_connection()
    try:
        # Get previous session for context
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
        _current_session_id = session_id

        return {
            "session_id": session_id,
            "title": title,
            "previous_session": previous_context,
        }
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
        # Find current session
        session_id = _current_session_id
        if not session_id:
            # Try to find the last open session
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
        _current_session_id = None

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


def get_current_session_id() -> Optional[str]:
    """Get the current active session ID."""
    return _current_session_id
