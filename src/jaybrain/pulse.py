"""Cross-session awareness system (Pulse).

Provides real-time visibility into what other Claude Code sessions
are doing by querying the shared activity log populated by hooks.

The hook script (scripts/session_hook.py) writes to claude_sessions
and session_activity_log tables on every SessionStart, PostToolUse,
and SessionEnd event. This module reads that data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .db import get_connection

logger = logging.getLogger(__name__)


def _minutes_since(iso_timestamp: str) -> float:
    """Calculate minutes since a given ISO timestamp."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return round(delta.total_seconds() / 60, 1)
    except (ValueError, TypeError):
        return -1


def _has_pulse_tables(conn) -> bool:
    """Check if the Pulse tables exist (created by the hook script)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='claude_sessions'"
    ).fetchone()
    return row is not None


def get_active_sessions(stale_minutes: int = 60) -> dict:
    """List all sessions with recent activity.

    stale_minutes: sessions with no heartbeat in this many minutes
    are considered stale (but still shown with a warning).
    """
    conn = get_connection()
    try:
        if not _has_pulse_tables(conn):
            return {
                "status": "no_data",
                "message": "Pulse tables not yet created. Hooks haven't fired yet.",
                "sessions": [],
            }

        # Get all sessions (not just active ones, so user can see ended ones too)
        rows = conn.execute(
            """SELECT * FROM claude_sessions
            ORDER BY last_heartbeat DESC
            LIMIT 20"""
        ).fetchall()

        active = []
        ended = []
        for r in rows:
            mins = _minutes_since(r["last_heartbeat"])
            entry = {
                "session_id": r["session_id"],
                "cwd": r["cwd"],
                "started_at": r["started_at"],
                "last_heartbeat": r["last_heartbeat"],
                "status": r["status"],
                "description": r["description"],
                "tool_count": r["tool_count"],
                "last_tool": r["last_tool"],
                "last_tool_input": r["last_tool_input"],
                "minutes_since_active": mins,
            }

            if r["status"] == "active":
                if mins > stale_minutes:
                    entry["warning"] = f"No activity in {mins:.0f} min -- likely stuck or idle"
                active.append(entry)
            else:
                ended.append(entry)

        return {
            "status": "ok",
            "active_count": len(active),
            "active_sessions": active,
            "recently_ended": ended[:5],
        }
    finally:
        conn.close()


def get_session_activity(
    session_id: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Get recent activity log entries across all or a specific session."""
    conn = get_connection()
    try:
        if not _has_pulse_tables(conn):
            return {
                "status": "no_data",
                "message": "Pulse tables not yet created.",
                "activities": [],
            }

        if session_id:
            rows = conn.execute(
                """SELECT * FROM session_activity_log
                WHERE session_id = ?
                ORDER BY timestamp DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM session_activity_log
                ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        activities = []
        for r in rows:
            activities.append({
                "session_id": r["session_id"],
                "event_type": r["event_type"],
                "tool_name": r["tool_name"],
                "tool_input_summary": r["tool_input_summary"],
                "timestamp": r["timestamp"],
                "minutes_ago": _minutes_since(r["timestamp"]),
            })

        return {
            "status": "ok",
            "count": len(activities),
            "activities": activities,
        }
    finally:
        conn.close()


def query_session(session_id: str) -> dict:
    """Get full details on a specific session including tool usage breakdown."""
    conn = get_connection()
    try:
        if not _has_pulse_tables(conn):
            return {"status": "no_data", "message": "Pulse tables not yet created."}

        row = conn.execute(
            "SELECT * FROM claude_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not row:
            # Try partial match
            rows = conn.execute(
                "SELECT * FROM claude_sessions WHERE session_id LIKE ?",
                (f"%{session_id}%",),
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
            elif len(rows) > 1:
                return {
                    "status": "ambiguous",
                    "message": f"Multiple sessions match '{session_id}'",
                    "matches": [r["session_id"] for r in rows],
                }
            else:
                return {"status": "not_found", "session_id": session_id}

        # Get activity for this session
        activities = conn.execute(
            """SELECT * FROM session_activity_log
            WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT 30""",
            (row["session_id"],),
        ).fetchall()

        # Build tool usage summary
        tool_counts = {}
        for a in activities:
            t = a["tool_name"]
            if t:
                tool_counts[t] = tool_counts.get(t, 0) + 1

        # Sort by usage count
        tool_counts = dict(sorted(tool_counts.items(), key=lambda x: -x[1]))

        return {
            "status": "ok",
            "session": {
                "session_id": row["session_id"],
                "cwd": row["cwd"],
                "started_at": row["started_at"],
                "last_heartbeat": row["last_heartbeat"],
                "status": row["status"],
                "description": row["description"],
                "tool_count": row["tool_count"],
                "last_tool": row["last_tool"],
                "last_tool_input": row["last_tool_input"],
                "minutes_since_active": _minutes_since(row["last_heartbeat"]),
            },
            "tool_usage": tool_counts,
            "recent_activity": [
                {
                    "event_type": a["event_type"],
                    "tool_name": a["tool_name"],
                    "tool_input_summary": a["tool_input_summary"],
                    "timestamp": a["timestamp"],
                    "minutes_ago": _minutes_since(a["timestamp"]),
                }
                for a in activities[:15]
            ],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# X-Ray: cross-session transcript reader
# ---------------------------------------------------------------------------

_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_MAX_TEXT_LEN = 800  # truncate individual messages to keep output manageable


def _find_jsonl(session_id: str) -> Optional[Path]:
    """Locate the JSONL transcript file for a session across all projects."""
    if not _CLAUDE_PROJECTS_DIR.exists():
        return None
    for project_dir in _CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _extract_user_text(obj: dict) -> Optional[str]:
    """Extract plain text from a user message (skip tool_result entries)."""
    content = obj.get("message", {}).get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        text = " ".join(parts).strip()
        return text if text else None
    return None


def _extract_assistant_text(obj: dict) -> Optional[str]:
    """Extract visible text from an assistant message (skip thinking/tool_use)."""
    content = obj.get("message", {}).get("content")
    if not isinstance(content, list):
        return None
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text", "").strip()
            if text:
                parts.append(text)
    text = "\n".join(parts).strip()
    return text if text else None


def _parse_transcript(path: Path) -> list[dict]:
    """Parse a JSONL transcript into a list of conversation turns.

    Returns a list of {role, text, timestamp} dicts, containing only
    user prompts and assistant text responses.
    """
    turns = []
    seen_assistant_ids = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type")
                if msg_type == "user":
                    text = _extract_user_text(obj)
                    if text:
                        turns.append({
                            "role": "user",
                            "text": text[:_MAX_TEXT_LEN],
                            "timestamp": obj.get("timestamp", ""),
                        })
                elif msg_type == "assistant":
                    # Assistant messages stream as multiple JSONL lines
                    # with the same requestId. Only keep the one with text.
                    text = _extract_assistant_text(obj)
                    if text:
                        req_id = obj.get("requestId", "")
                        if req_id and req_id in seen_assistant_ids:
                            # Update existing turn with more complete text
                            for t in reversed(turns):
                                if t.get("_req_id") == req_id:
                                    if len(text) > len(t["text"]):
                                        t["text"] = text[:_MAX_TEXT_LEN]
                                    break
                        else:
                            if req_id:
                                seen_assistant_ids.add(req_id)
                            turns.append({
                                "role": "assistant",
                                "text": text[:_MAX_TEXT_LEN],
                                "timestamp": obj.get("timestamp", ""),
                                "_req_id": req_id,
                            })
    except OSError as e:
        logger.error("Failed to read transcript %s: %s", path, e)
        return []

    # Strip internal tracking field
    for t in turns:
        t.pop("_req_id", None)
    return turns


def get_session_context(
    session_id: str,
    snippet: Optional[str] = None,
    last_n: int = 30,
    context_window: int = 10,
) -> dict:
    """Read another session's JSONL transcript and return conversation context.

    Codename: X-Ray

    Args:
        session_id: Full or partial session ID. Partial match is tried
            across all project directories.
        snippet: If provided, search the transcript for this text and
            return turns surrounding the match. If omitted, returns
            the last `last_n` turns.
        last_n: Number of recent turns to return when no snippet is given.
        context_window: Number of turns before and after a snippet match.

    Returns:
        A dict with status, session_id, turns (list of role/text/timestamp),
        and metadata about the transcript.
    """
    # Resolve partial session IDs
    jsonl_path = _find_jsonl(session_id)
    if not jsonl_path:
        # Try partial match
        matches = []
        if _CLAUDE_PROJECTS_DIR.exists():
            for project_dir in _CLAUDE_PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                for f in project_dir.iterdir():
                    if (
                        f.suffix == ".jsonl"
                        and session_id in f.stem
                        and "subagent" not in str(f)
                    ):
                        matches.append(f)
        if len(matches) == 1:
            jsonl_path = matches[0]
        elif len(matches) > 1:
            return {
                "status": "ambiguous",
                "message": f"Multiple sessions match '{session_id}'",
                "matches": [m.stem for m in matches],
            }
        else:
            return {
                "status": "not_found",
                "message": f"No transcript found for session '{session_id}'",
            }

    resolved_id = jsonl_path.stem
    turns = _parse_transcript(jsonl_path)

    if not turns:
        return {
            "status": "empty",
            "session_id": resolved_id,
            "message": "Transcript parsed but no conversation turns found.",
        }

    if snippet:
        snippet_lower = snippet.lower()
        match_idx = None
        for i, turn in enumerate(turns):
            if snippet_lower in turn["text"].lower():
                match_idx = i
                break

        if match_idx is None:
            # Snippet not found; return last_n turns as fallback
            return {
                "status": "snippet_not_found",
                "session_id": resolved_id,
                "message": f"Snippet not found in transcript. Returning last {last_n} turns instead.",
                "total_turns": len(turns),
                "turns": turns[-last_n:],
            }

        start = max(0, match_idx - context_window)
        end = min(len(turns), match_idx + context_window + 1)
        return {
            "status": "ok",
            "session_id": resolved_id,
            "mode": "snippet",
            "match_turn": match_idx,
            "total_turns": len(turns),
            "window": f"turns {start}-{end - 1} of {len(turns)}",
            "turns": turns[start:end],
        }

    # No snippet -- return last N turns plus the first few for session plan
    first_turns = turns[:3] if len(turns) > last_n + 3 else []
    recent_turns = turns[-last_n:]

    result = {
        "status": "ok",
        "session_id": resolved_id,
        "mode": "recent",
        "total_turns": len(turns),
        "turns": recent_turns,
    }
    if first_turns:
        result["session_opening"] = first_turns

    return result
