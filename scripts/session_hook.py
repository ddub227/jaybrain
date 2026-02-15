#!/usr/bin/env python3
"""Claude Code hook script for cross-session awareness (Pulse).

Reads hook event JSON from stdin and writes to JayBrain's shared SQLite DB.
Fires on SessionStart, PostToolUse, and SessionEnd events.

IMPORTANT: This script must be fast (<1s). No heavy imports (no ONNX, no embeddings).
Uses raw sqlite3 directly -- does NOT import jaybrain package.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# DB path computed relative to this script: scripts/ -> jaybrain/ -> data/
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jaybrain.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claude_sessions (
    session_id TEXT PRIMARY KEY,
    cwd TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT NOT NULL DEFAULT '',
    tool_count INTEGER NOT NULL DEFAULT 0,
    last_tool TEXT NOT NULL DEFAULT '',
    last_tool_input TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    tool_input_summary TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sal_session ON session_activity_log(session_id);
CREATE INDEX IF NOT EXISTS idx_sal_timestamp ON session_activity_log(timestamp);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    if not DB_PATH.parent.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def summarize_tool_input(tool_input, max_len=200):
    """Create a compact summary of tool input for the activity log."""
    if not tool_input or not isinstance(tool_input, dict):
        return ""
    parts = []
    # Extract the most informative fields first
    priority_keys = [
        "command", "query", "prompt", "file_path", "pattern",
        "url", "description", "task_id", "skill", "content",
    ]
    for key in priority_keys:
        if key in tool_input:
            val = str(tool_input[key])
            if len(val) > 100:
                val = val[:97] + "..."
            parts.append(f"{key}={val}")
            if len(", ".join(parts)) > max_len:
                break
    if not parts:
        # Fallback: show first few keys
        parts = [f"{k}=..." for k in list(tool_input.keys())[:4]]
    result = ", ".join(parts)
    return result[:max_len]


def prune_old_activity(conn, max_hours=48):
    """Remove activity log entries older than max_hours."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_hours)).isoformat()
    conn.execute(
        "DELETE FROM session_activity_log WHERE timestamp < ?",
        (cutoff,),
    )
    # Also mark very stale sessions as ended
    conn.execute(
        """UPDATE claude_sessions SET status = 'ended'
        WHERE status = 'active' AND last_heartbeat < ?""",
        (cutoff,),
    )
    conn.commit()


def handle_event(data):
    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd", "")
    event = data.get("hook_event_name", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    now = now_iso()

    conn = get_conn()
    try:
        ensure_tables(conn)

        if event == "SessionStart":
            conn.execute(
                """INSERT OR REPLACE INTO claude_sessions
                (session_id, cwd, started_at, last_heartbeat, status, description, tool_count, last_tool, last_tool_input)
                VALUES (?, ?, ?, ?, 'active', '', 0, '', '')""",
                (session_id, cwd, now, now),
            )
            conn.execute(
                """INSERT INTO session_activity_log
                (session_id, event_type, timestamp)
                VALUES (?, 'session_start', ?)""",
                (session_id, now),
            )

        elif event in ("PostToolUse", "PostToolUseFailure"):
            input_summary = summarize_tool_input(tool_input)
            event_type = "tool_use" if event == "PostToolUse" else "tool_failure"
            # Upsert session (handles case where we missed SessionStart)
            conn.execute(
                """INSERT INTO claude_sessions
                (session_id, cwd, started_at, last_heartbeat, status, tool_count, last_tool, last_tool_input)
                VALUES (?, ?, ?, ?, 'active', 1, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_heartbeat = excluded.last_heartbeat,
                    tool_count = tool_count + 1,
                    last_tool = excluded.last_tool,
                    last_tool_input = excluded.last_tool_input,
                    status = 'active'""",
                (session_id, cwd, now, now, tool_name, input_summary),
            )
            conn.execute(
                """INSERT INTO session_activity_log
                (session_id, event_type, tool_name, tool_input_summary, timestamp)
                VALUES (?, ?, ?, ?, ?)""",
                (session_id, event_type, tool_name, input_summary, now),
            )

        elif event == "SessionEnd":
            conn.execute(
                """UPDATE claude_sessions SET status = 'ended', last_heartbeat = ?
                WHERE session_id = ?""",
                (now, session_id),
            )
            conn.execute(
                """INSERT INTO session_activity_log
                (session_id, event_type, timestamp)
                VALUES (?, 'session_end', ?)""",
                (session_id, now),
            )

        elif event == "Stop":
            # Stop fires after every response. Use it as a heartbeat
            # but don't log it to the activity stream (too noisy).
            conn.execute(
                """UPDATE claude_sessions SET last_heartbeat = ?
                WHERE session_id = ?""",
                (now, session_id),
            )

        conn.commit()

        # Prune old data occasionally (1 in 50 calls)
        import random
        if random.randint(1, 50) == 1:
            prune_old_activity(conn)

    finally:
        conn.close()


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        handle_event(data)
    except Exception as e:
        # Hooks must not fail loudly or block Claude Code
        print(f"session_hook: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
