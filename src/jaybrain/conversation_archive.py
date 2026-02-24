"""Nightly conversation archive -- parse, summarize, and archive to Google Docs.

Discovers JSONL conversation files from ~/.claude/projects/, extracts turns,
summarizes via `claude -p` (no API cost under Max subscription), and creates
a dated Google Doc per archive run.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import (
    CLAUDE_PROJECTS_DIR,
    CONVERSATION_ARCHIVE_MAX_AGE_DAYS,
    DB_PATH,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Reuse parsing from pulse module
_MAX_TEXT_LEN = 2000


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _extract_user_text(obj: dict) -> Optional[str]:
    """Extract plain text from a user message."""
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
    """Extract visible text from an assistant message."""
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


def _extract_tool_calls(obj: dict) -> list[str]:
    """Extract tool names from an assistant message."""
    content = obj.get("message", {}).get("content")
    if not isinstance(content, list):
        return []
    tools = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            tools.append(item.get("name", "unknown"))
    return tools


def parse_conversation(path: Path) -> dict:
    """Parse a JSONL conversation file into structured data.

    Returns: {session_id, project_dir, turns, tool_calls, started_at, ended_at}
    """
    turns = []
    tool_calls = []
    seen_assistant_ids = set()
    started_at = None
    ended_at = None

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

                timestamp = obj.get("timestamp", "")
                if timestamp:
                    if not started_at:
                        started_at = timestamp
                    ended_at = timestamp

                msg_type = obj.get("type")
                if msg_type == "user":
                    text = _extract_user_text(obj)
                    if text:
                        turns.append({
                            "role": "user",
                            "text": text[:_MAX_TEXT_LEN],
                            "timestamp": timestamp,
                        })
                elif msg_type == "assistant":
                    text = _extract_assistant_text(obj)
                    tools = _extract_tool_calls(obj)
                    tool_calls.extend(tools)

                    if text:
                        req_id = obj.get("requestId", "")
                        if req_id and req_id in seen_assistant_ids:
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
                                "timestamp": timestamp,
                                "_req_id": req_id,
                            })
    except OSError as e:
        logger.error("Failed to read conversation %s: %s", path, e)
        return {"turns": [], "tool_calls": [], "error": str(e)}

    # Strip internal tracking field
    for t in turns:
        t.pop("_req_id", None)

    session_id = path.stem
    return {
        "session_id": session_id,
        "project_dir": str(path.parent),
        "jsonl_path": str(path),
        "turns": turns,
        "tool_calls": tool_calls,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def discover_conversations(
    max_age_days: int | None = None,
) -> list[Path]:
    """Find JSONL conversation files in Claude projects directory.

    Returns list of Paths, filtered to only include recent files.
    """
    if max_age_days is None:
        max_age_days = CONVERSATION_ARCHIVE_MAX_AGE_DAYS

    projects_dir = CLAUDE_PROJECTS_DIR
    if not projects_dir.exists():
        logger.info("Claude projects directory not found: %s", projects_dir)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    conversations = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(
                    jsonl_file.stat().st_mtime, tz=timezone.utc
                )
                if mtime >= cutoff:
                    conversations.append(jsonl_file)
            except OSError:
                continue

    return sorted(conversations, key=lambda p: p.stat().st_mtime, reverse=True)


def _get_archived_session_ids() -> set[str]:
    """Get session IDs that have already been archived."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT session_id FROM conversation_archive_sessions"
        ).fetchall()
        return {row["session_id"] for row in rows}
    except Exception:
        return set()
    finally:
        conn.close()


def summarize_conversation(conversation: dict) -> str:
    """Summarize a parsed conversation using `claude -p`.

    Falls back to a basic tool-call summary if `claude -p` fails.
    """
    turns = conversation.get("turns", [])
    if not turns:
        return "(empty conversation)"

    # Build a transcript for claude -p
    transcript_parts = []
    for turn in turns[:50]:  # Limit to 50 turns
        role = turn["role"].upper()
        text = turn["text"][:500]  # Truncate long messages
        transcript_parts.append(f"{role}: {text}")

    transcript = "\n\n".join(transcript_parts)

    prompt = (
        "Summarize this Claude Code conversation in 2-3 sentences. "
        "Focus on what was accomplished, key decisions, and any unfinished work.\n\n"
        f"{transcript}"
    )

    claude_cmd = shutil.which("claude") or "claude"
    # Strip Claude Code env vars so subprocess doesn't think it's nested
    clean_env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("CLAUDECODE") and not k.startswith("CLAUDE_CODE")
    }
    try:
        result = subprocess.run(
            [claude_cmd, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
            env=clean_env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:1000]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("claude -p failed, using fallback summary: %s", e)

    # Fallback: basic summary from tool calls
    tool_calls = conversation.get("tool_calls", [])
    if tool_calls:
        unique_tools = list(dict.fromkeys(tool_calls))[:10]
        return f"Session used {len(tool_calls)} tool calls including: {', '.join(unique_tools)}"

    return f"Conversation with {len(turns)} turns."


def archive_to_gdoc(run_id: str, summaries: list[dict]) -> dict:
    """Create a dated Google Doc with conversation summaries.

    Returns: {gdoc_id, gdoc_url} or {error} if Docs unavailable.
    """
    if not summaries:
        return {"gdoc_id": "", "gdoc_url": "", "note": "No conversations to archive"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"JayBrain Conversation Archive - {today}"

    # Build markdown content
    lines = [f"# Conversation Archive - {today}\n"]
    lines.append(f"**Archived:** {len(summaries)} conversations\n")
    lines.append(f"**Run ID:** {run_id}\n")
    lines.append("---\n")

    for i, s in enumerate(summaries, 1):
        lines.append(f"## {i}. Session {s.get('session_id', 'unknown')}")
        if s.get("started_at"):
            lines.append(f"**Started:** {s['started_at']}")
        if s.get("project_dir"):
            lines.append(f"**Project:** {s['project_dir']}")
        lines.append(f"\n{s.get('summary', '(no summary)')}\n")
        lines.append("---\n")

    content = "\n".join(lines)

    try:
        from .gdocs import create_google_doc
        result = create_google_doc(title, content)
        return {
            "gdoc_id": result.get("doc_id", ""),
            "gdoc_url": result.get("doc_url", ""),
        }
    except Exception as e:
        logger.warning("Google Docs archive failed: %s", e)
        return {"gdoc_id": "", "gdoc_url": "", "error": str(e)}


def run_archive() -> dict:
    """Main archive workflow -- discover, parse, summarize, archive.

    Returns summary of the run.
    """
    ensure_data_dirs()
    run_id = _generate_id()
    now = now_iso()

    # Discover conversations
    conversations = discover_conversations()
    archived_ids = _get_archived_session_ids()

    # Filter out already-archived
    new_conversations = [
        c for c in conversations
        if c.stem not in archived_ids
    ]

    if not new_conversations:
        # Record empty run
        _record_run(run_id, now, len(conversations), 0, "", "", "")
        return {
            "run_id": run_id,
            "conversations_found": len(conversations),
            "conversations_archived": 0,
            "message": "No new conversations to archive",
        }

    # Parse and summarize
    summaries = []
    for path in new_conversations:
        parsed = parse_conversation(path)
        if not parsed.get("turns"):
            continue
        summary = summarize_conversation(parsed)
        summaries.append({
            "session_id": parsed["session_id"],
            "project_dir": parsed.get("project_dir", ""),
            "jsonl_path": str(path),
            "summary": summary,
            "started_at": parsed.get("started_at", ""),
        })

    # Archive to Google Doc
    gdoc_result = archive_to_gdoc(run_id, summaries)

    # Record run and sessions
    _record_run(
        run_id, now, len(conversations), len(summaries),
        gdoc_result.get("gdoc_id", ""),
        gdoc_result.get("gdoc_url", ""),
        gdoc_result.get("error", ""),
    )
    _record_sessions(run_id, summaries)

    return {
        "run_id": run_id,
        "conversations_found": len(conversations),
        "conversations_archived": len(summaries),
        "gdoc_url": gdoc_result.get("gdoc_url", ""),
    }


def _record_run(
    run_id: str, run_at: str, found: int, archived: int,
    gdoc_id: str, gdoc_url: str, error: str,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO conversation_archive_runs
            (id, run_at, conversations_found, conversations_archived,
             gdoc_id, gdoc_url, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, run_at, found, archived, gdoc_id, gdoc_url, error, run_at),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to record archive run: %s", e)
    finally:
        conn.close()


def _record_sessions(run_id: str, summaries: list[dict]) -> None:
    conn = get_connection()
    try:
        now = now_iso()
        for s in summaries:
            conn.execute(
                """INSERT OR IGNORE INTO conversation_archive_sessions
                (session_id, project_dir, jsonl_path, summary_preview,
                 archived_in_run, archived_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    s["session_id"],
                    s.get("project_dir", ""),
                    s.get("jsonl_path", ""),
                    s.get("summary", "")[:200],
                    run_id,
                    now,
                ),
            )
        conn.commit()
    except Exception as e:
        logger.error("Failed to record archive sessions: %s", e)
    finally:
        conn.close()


def get_archive_status() -> dict:
    """Get recent archive run stats."""
    conn = get_connection()
    try:
        runs = conn.execute(
            """SELECT * FROM conversation_archive_runs
            ORDER BY run_at DESC LIMIT 5"""
        ).fetchall()

        total_archived = conn.execute(
            "SELECT COUNT(*) FROM conversation_archive_sessions"
        ).fetchone()[0]

        return {
            "total_archived_sessions": total_archived,
            "recent_runs": [
                {
                    "id": r["id"],
                    "run_at": r["run_at"],
                    "found": r["conversations_found"],
                    "archived": r["conversations_archived"],
                    "gdoc_url": r["gdoc_url"],
                    "error": r["error"],
                }
                for r in runs
            ],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
