#!/usr/bin/env python3
"""Claude Code PreCompact hook -- snapshot working state before context compression.

Reads hook event JSON from stdin and writes a session checkpoint to the sessions
table using the checkpoint columns added in migration 5.

IMPORTANT: Must complete in <5s. No heavy imports (no ONNX, no embeddings).
Uses raw sqlite3 directly -- does NOT import jaybrain package.
Pattern: scripts/session_hook.py
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# DB path computed relative to this script: scripts/ -> jaybrain/ -> data/
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jaybrain.db"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    if not DB_PATH.parent.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def handle_precompact(data):
    """Snapshot current session state to checkpoint columns.

    The PreCompact hook receives the session_id and transcript_summary from
    Claude Code. We write this to the sessions table checkpoint columns.
    """
    session_id = data.get("session_id", "")
    if not session_id:
        return

    now = now_iso()

    # Extract what we can from the hook data
    # PreCompact provides: session_id, cwd, hook_event_name
    # We build a checkpoint summary from the session's activity log
    cwd = data.get("cwd", "")

    conn = get_conn()
    try:
        # Build checkpoint from recent activity
        summary_parts = [f"PreCompact triggered at {now}"]
        if cwd:
            summary_parts.append(f"Working directory: {cwd}")

        # Pull recent tool activity for context
        try:
            rows = conn.execute(
                """SELECT tool_name, tool_input_summary, timestamp
                FROM session_activity_log
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT 10""",
                (session_id,),
            ).fetchall()
            if rows:
                tools_used = [r["tool_name"] for r in rows if r["tool_name"]]
                if tools_used:
                    summary_parts.append(f"Recent tools: {', '.join(tools_used[:5])}")
        except sqlite3.OperationalError:
            pass  # Table may not exist yet

        checkpoint_summary = ". ".join(summary_parts)

        # Check if session exists
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE sessions SET
                    checkpoint_summary = ?,
                    checkpoint_at = ?
                WHERE id = ?""",
                (checkpoint_summary, now, session_id),
            )
        else:
            # Create a minimal session record for the checkpoint
            conn.execute(
                """INSERT OR IGNORE INTO sessions
                (id, title, started_at, checkpoint_summary, checkpoint_at)
                VALUES (?, 'auto-checkpoint', ?, ?, ?)""",
                (session_id, now, checkpoint_summary, now),
            )

        conn.commit()
    finally:
        conn.close()


def main():
    start = time.monotonic()
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)

        # Only handle PreCompact events
        event = data.get("hook_event_name", "")
        if event != "PreCompact":
            return

        # Retry with exponential backoff on database lock errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                handle_precompact(data)
                return
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

    except Exception as e:
        # Hooks must not fail loudly or block Claude Code
        print(f"precompact_hook: {e}", file=sys.stderr)
    finally:
        elapsed = time.monotonic() - start
        if elapsed > 4.0:
            print(f"precompact_hook: WARNING took {elapsed:.1f}s (>4s)", file=sys.stderr)


if __name__ == "__main__":
    main()
