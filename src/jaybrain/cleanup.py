"""Auto-close active JayBrain session on Claude Code exit.

Called by Claude Code's Stop hook. Reads the active session file,
closes the session in the DB, and writes a handoff file.

Can be run standalone: python -m jaybrain.cleanup
"""

import json
import sys

from .config import ACTIVE_SESSION_FILE, ensure_data_dirs
from .db import get_connection, end_session, get_session


def cleanup_session() -> None:
    """Close the active session if one exists."""
    ensure_data_dirs()

    # Read hook input from stdin for context
    hook_input = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                hook_input = json.loads(raw)
    except Exception:
        pass

    # Don't recurse if we're already in a stop hook
    if hook_input.get("stop_hook_active"):
        return

    # Read active session from disk
    session_id = None
    try:
        if ACTIVE_SESSION_FILE.exists():
            session_id = ACTIVE_SESSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return

    if not session_id:
        return

    conn = get_connection()
    try:
        row = get_session(conn, session_id)
        if not row or row["ended_at"]:
            # Already closed or doesn't exist — clean up stale file
            try:
                ACTIVE_SESSION_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Close the session
        end_session(
            conn, session_id,
            summary="[Auto-closed by Stop hook] Session ended when Claude Code exited.",
            decisions_made=[],
            next_steps=["Review this session's conversation for any unsaved context"],
        )

        # Clean up the file
        try:
            ACTIVE_SESSION_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        print(f"JayBrain: Auto-closed session {session_id}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    cleanup_session()
