"""GitShadow -- periodic working tree snapshots via git stash create.

Creates stash objects without modifying the working tree or stash list.
Logs each snapshot hash + changed files to git_shadow_log for later recovery.
Runs as a daemon module via IntervalTrigger.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    DB_PATH,
    GIT_SHADOW_ENABLED,
    GIT_SHADOW_REPO_PATHS,
)

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _git_cmd(args: list[str], cwd: str) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        return result.returncode, result.stdout.strip()
    except Exception as e:
        return -1, str(e)


def _snapshot_repo(repo_path: str) -> dict:
    """Create a stash snapshot for one repo. Returns result dict.

    Uses `git stash create` which captures tracked changes (staged + unstaged)
    without modifying the working tree or stash list. Untracked files are listed
    in the log but not included in the stash object (they're on disk and not at
    risk of being lost between commits).
    """
    # Check for tracked changes (staged + unstaged)
    rc, diff_stat = _git_cmd(["diff", "--stat"], repo_path)
    rc2, diff_staged = _git_cmd(["diff", "--cached", "--stat"], repo_path)
    rc3, untracked = _git_cmd(
        ["ls-files", "--others", "--exclude-standard"], repo_path
    )

    has_tracked_changes = bool(diff_stat or diff_staged)
    has_any_changes = has_tracked_changes or bool(untracked)

    if not has_any_changes:
        return {"repo": repo_path, "status": "clean", "skipped": True}

    if not has_tracked_changes:
        # Only untracked files exist — git stash create won't produce a hash.
        # Log the untracked files for awareness but skip stash creation.
        untracked_files = [f for f in untracked.split("\n") if f.strip()]
        return {
            "repo": repo_path,
            "status": "untracked_only",
            "skipped": True,
            "untracked_files": len(untracked_files),
        }

    # Get current branch
    _, branch = _git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)

    # Create stash object (does NOT modify working tree or stash list)
    rc, stash_hash = _git_cmd(["stash", "create"], repo_path)

    if rc != 0 or not stash_hash:
        return {"repo": repo_path, "status": "no_stash", "skipped": True}

    # Get changed tracked files list
    _, changed_output = _git_cmd(["diff", "--name-only", "HEAD"], repo_path)
    changed_files = [f for f in changed_output.split("\n") if f.strip()]

    # Include staged changes
    _, staged_output = _git_cmd(["diff", "--cached", "--name-only"], repo_path)
    staged_files = [f for f in staged_output.split("\n") if f.strip()]
    changed_files.extend(staged_files)

    # Note untracked files in the log (not in stash, but useful for context)
    if untracked:
        changed_files.extend(
            [f"[untracked] {f}" for f in untracked.split("\n") if f.strip()]
        )

    # Deduplicate
    changed_files = sorted(set(changed_files))

    # Log to DB
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO git_shadow_log
            (id, timestamp, stash_hash, changed_files, repo_path, branch)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex[:12],
                now,
                stash_hash,
                json.dumps(changed_files),
                repo_path,
                branch or "unknown",
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug("Failed to log git shadow", exc_info=True)

    return {
        "repo": repo_path,
        "status": "snapshot",
        "stash_hash": stash_hash[:12],
        "branch": branch,
        "changed_files": len(changed_files),
    }


def run_git_shadow() -> dict:
    """Daemon entry point: snapshot all configured repos."""
    if not GIT_SHADOW_ENABLED:
        return {"status": "disabled"}

    results = []
    for repo_path in GIT_SHADOW_REPO_PATHS:
        p = Path(repo_path)
        if not (p / ".git").exists():
            results.append(
                {"repo": repo_path, "status": "not_a_repo", "skipped": True}
            )
            continue
        result = _snapshot_repo(str(p))
        results.append(result)

    snapshots = sum(1 for r in results if r.get("status") == "snapshot")
    return {
        "status": "ok",
        "repos_checked": len(results),
        "snapshots_created": snapshots,
        "details": results,
    }


def query_shadow_history(
    repo: str | None = None,
    file: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query git shadow log."""
    conn = _get_conn()
    try:
        query = "SELECT * FROM git_shadow_log WHERE 1=1"
        params: list = []
        if repo:
            query += " AND repo_path LIKE ?"
            params.append(f"%{repo}%")
        if file:
            query += " AND changed_files LIKE ?"
            params.append(f"%{file}%")
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def restore_file(shadow_id: str, file_path: str) -> dict:
    """Extract a specific file from a git shadow stash.

    Returns the file content as a string.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM git_shadow_log WHERE id = ?", (shadow_id,)
        ).fetchone()
        if not row:
            return {"error": f"Shadow ID {shadow_id} not found"}

        stash_hash = row["stash_hash"]
        repo_path = row["repo_path"]

        rc, content = _git_cmd(
            ["show", f"{stash_hash}:{file_path}"], repo_path
        )
        if rc != 0:
            return {"error": f"Could not extract {file_path}: {content}"}

        return {
            "shadow_id": shadow_id,
            "file_path": file_path,
            "stash_hash": stash_hash,
            "content": content,
        }
    finally:
        conn.close()
