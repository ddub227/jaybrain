"""Soft-delete recycle bin -- scan, trash, restore, and sweep files.

Moves files to a staging area (data/trash/) with metadata tracking in SQLite.
Files remain recoverable for a configurable retention period before permanent
deletion by the daemon sweep job.

Safety rules:
- Never auto-delete git-tracked files.
- Never delete protected patterns (.git, .env, pyproject.toml, etc.).
- Auto-trash only gitignored garbage (bytecode, caches, build artifacts).
- Everything else gets flagged for manual review.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

from .config import (
    TRASH_AUTO_PATTERNS,
    TRASH_DEFAULT_RETENTION_DAYS,
    TRASH_DIR,
    TRASH_PROTECTED_PATTERNS,
    TRASH_RETENTION_BY_CATEGORY,
    TRASH_SCAN_DIRS,
    TRASH_SUSPECT_PATTERNS,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file. Returns empty string for directories."""
    if path.is_dir():
        return ""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def _file_size(path: Path) -> int:
    """Get size in bytes. For directories, sum all contents."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except (OSError, PermissionError):
        pass
    return total


def _find_git_root(path: Path) -> Optional[Path]:
    """Walk up from path to find the nearest .git directory."""
    current = path if path.is_dir() else path.parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _is_git_tracked(filepath: Path, git_root: Path) -> bool:
    """Check if a file is tracked by git."""
    try:
        rel = filepath.relative_to(git_root)
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(rel)],
            capture_output=True, cwd=str(git_root), timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_git_ignored(filepath: Path, git_root: Path) -> bool:
    """Check if a file is in .gitignore."""
    try:
        rel = filepath.relative_to(git_root)
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            capture_output=True, cwd=str(git_root), timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _matches_any_pattern(path: Path, patterns: list[str], base_dir: Path) -> bool:
    """Check if a path matches any glob-style pattern relative to base_dir."""
    try:
        rel = str(path.relative_to(base_dir)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")

    name = path.name
    for pattern in patterns:
        # Match against the full relative path
        if fnmatch(rel, pattern):
            return True
        # Also match just the filename for simple patterns
        if "/" not in pattern and fnmatch(name, pattern):
            return True
    return False


def _categorize_file(path: Path) -> str:
    """Determine the trash category for a file/directory."""
    name = path.name.lower()
    suffix = path.suffix.lower()

    if name == "__pycache__" or suffix in (".pyc", ".pyo"):
        return "bytecode"
    if name in ("dist", "build") or name.endswith(".egg-info"):
        return "build_artifact"
    if name in (".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "htmlcov"):
        return "cache"
    if name == ".coverage" or name.startswith(".coverage."):
        return "cache"
    if suffix == ".log":
        return "log"
    if name in ("null", "thumbs.db", ".ds_store") or suffix in (".tmp", ".bak", ".orig", ".swp"):
        return "temp"
    if suffix == ".py":
        return "source"
    return "general"


def _retention_days(category: str) -> int:
    """Get retention days for a category."""
    return TRASH_RETENTION_BY_CATEGORY.get(category, TRASH_DEFAULT_RETENTION_DAYS)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def scan_files(
    scan_dirs: Optional[list[Path]] = None,
    include_auto: bool = True,
    include_suspect: bool = True,
) -> dict:
    """Scan project directories for trashable files.

    Returns a dict with 'auto' (safe to auto-trash) and 'review' (need
    confirmation) lists. Each entry has path, category, size, reason, and
    git status.
    """
    ensure_data_dirs()
    dirs = scan_dirs or [Path(d) for d in TRASH_SCAN_DIRS]

    auto_items: list[dict] = []
    review_items: list[dict] = []

    for scan_dir in dirs:
        if not scan_dir.exists():
            continue

        git_root = _find_git_root(scan_dir)

        # Walk the directory tree
        for dirpath, dirnames, filenames in os.walk(str(scan_dir)):
            current = Path(dirpath)

            # Skip .git directories entirely
            if ".git" in current.parts:
                dirnames.clear()
                continue

            # Skip the trash directory itself
            if str(current).startswith(str(TRASH_DIR)):
                dirnames.clear()
                continue

            # Check if this directory itself is a trashable item
            if include_auto and _matches_any_pattern(current, TRASH_AUTO_PATTERNS, scan_dir):
                if not _matches_any_pattern(current, TRASH_PROTECTED_PATTERNS, scan_dir):
                    is_tracked = _is_git_tracked(current, git_root) if git_root else False
                    if not is_tracked:
                        is_ignored = _is_git_ignored(current, git_root) if git_root else True
                        if is_ignored:
                            category = _categorize_file(current)
                            auto_items.append({
                                "path": str(current),
                                "category": category,
                                "size": _file_size(current),
                                "reason": f"Matches auto-trash pattern, git-ignored",
                                "git_tracked": False,
                                "git_ignored": True,
                                "is_dir": True,
                            })
                            # Don't descend into trashable directories
                            dirnames.clear()
                            continue

            # Check individual files
            for fname in filenames:
                fpath = current / fname

                # Skip protected files
                if _matches_any_pattern(fpath, TRASH_PROTECTED_PATTERNS, scan_dir):
                    continue

                is_tracked = _is_git_tracked(fpath, git_root) if git_root else False
                if is_tracked:
                    continue  # never touch tracked files

                is_ignored = _is_git_ignored(fpath, git_root) if git_root else False

                # Auto-trash: matches pattern + git-ignored
                if include_auto and is_ignored:
                    if _matches_any_pattern(fpath, TRASH_AUTO_PATTERNS, scan_dir):
                        category = _categorize_file(fpath)
                        auto_items.append({
                            "path": str(fpath),
                            "category": category,
                            "size": fpath.stat().st_size if fpath.exists() else 0,
                            "reason": "Matches auto-trash pattern, git-ignored",
                            "git_tracked": False,
                            "git_ignored": True,
                            "is_dir": False,
                        })
                        continue

                # Suspect files: flagged for review
                if include_suspect:
                    if _matches_any_pattern(fpath, TRASH_SUSPECT_PATTERNS, scan_dir):
                        category = _categorize_file(fpath)
                        review_items.append({
                            "path": str(fpath),
                            "category": category,
                            "size": fpath.stat().st_size if fpath.exists() else 0,
                            "reason": "Matches suspect pattern, needs review",
                            "git_tracked": False,
                            "git_ignored": is_ignored,
                            "is_dir": False,
                        })

    return {
        "auto": auto_items,
        "review": review_items,
        "auto_count": len(auto_items),
        "review_count": len(review_items),
        "auto_total_size": sum(i["size"] for i in auto_items),
        "review_total_size": sum(i["size"] for i in review_items),
        "dirs_scanned": [str(d) for d in dirs],
    }


def trash_file(
    filepath: str,
    reason: str = "",
    category: Optional[str] = None,
    auto: bool = False,
) -> dict:
    """Move a file or directory to the trash with metadata tracking.

    Returns a dict with the trash entry details, or an error.
    """
    ensure_data_dirs()
    path = Path(filepath).resolve()

    if not path.exists():
        return {"error": f"Path does not exist: {filepath}"}

    # Safety: check protected patterns
    for scan_dir in TRASH_SCAN_DIRS:
        scan_dir = Path(scan_dir)
        if str(path).startswith(str(scan_dir)):
            if _matches_any_pattern(path, TRASH_PROTECTED_PATTERNS, scan_dir):
                return {"error": f"Protected file, cannot trash: {filepath}"}
            break

    # Safety: check git tracked
    git_root = _find_git_root(path)
    if git_root and _is_git_tracked(path, git_root):
        return {"error": f"Git-tracked file, cannot trash: {filepath}"}

    # Determine category and retention
    cat = category or _categorize_file(path)
    retention = _retention_days(cat)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=retention)

    # Generate unique trash path
    entry_id = uuid.uuid4().hex[:12]
    trash_name = f"{entry_id}_{path.name}"
    trash_path = TRASH_DIR / trash_name

    # Compute hash (files only)
    file_hash = _sha256(path)
    size = _file_size(path)
    is_dir = path.is_dir()

    # Move to trash
    try:
        shutil.move(str(path), str(trash_path))
    except (OSError, PermissionError) as e:
        return {"error": f"Failed to move to trash: {e}"}

    # Record in manifest
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO trash_manifest
            (id, original_path, trash_path, deleted_at, expires_at,
             reason, category, size_bytes, sha256, is_dir, auto_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                str(path),
                str(trash_path),
                now.isoformat(),
                expires.isoformat(),
                reason,
                cat,
                size,
                file_hash,
                int(is_dir),
                int(auto),
            ),
        )
        conn.commit()
    except Exception as e:
        # Try to restore on DB failure
        try:
            shutil.move(str(trash_path), str(path))
        except Exception:
            pass
        return {"error": f"Failed to record trash entry: {e}"}
    finally:
        conn.close()

    logger.info("Trashed: %s -> %s (category=%s, expires=%s)", path, trash_path, cat, expires.date())

    return {
        "id": entry_id,
        "original_path": str(path),
        "trash_path": str(trash_path),
        "category": cat,
        "size_bytes": size,
        "retention_days": retention,
        "expires_at": expires.isoformat(),
        "is_dir": is_dir,
        "auto": auto,
    }


def trash_batch(items: list[dict], auto: bool = False) -> dict:
    """Trash multiple files. Each item needs at least 'path'.

    Returns summary with counts and any errors.
    """
    trashed = 0
    errors = []
    total_size = 0

    for item in items:
        path = item.get("path", "")
        reason = item.get("reason", "batch cleanup")
        category = item.get("category")

        result = trash_file(path, reason=reason, category=category, auto=auto)
        if "error" in result:
            errors.append({"path": path, "error": result["error"]})
        else:
            trashed += 1
            total_size += result.get("size_bytes", 0)

    return {
        "trashed": trashed,
        "errors": len(errors),
        "error_details": errors[:10],  # cap to avoid huge responses
        "total_size": total_size,
    }


def restore_file(entry_id: str) -> dict:
    """Restore a trashed file to its original location.

    Verifies SHA-256 hash matches if available.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM trash_manifest WHERE id = ?", (entry_id,)
        ).fetchone()

        if not row:
            return {"error": f"Trash entry not found: {entry_id}"}

        trash_path = Path(row["trash_path"])
        original_path = Path(row["original_path"])

        if not trash_path.exists():
            conn.execute("DELETE FROM trash_manifest WHERE id = ?", (entry_id,))
            conn.commit()
            return {"error": "File no longer exists in trash (already swept?)"}

        # Ensure parent directory exists
        original_path.parent.mkdir(parents=True, exist_ok=True)

        # Check for collision at original path
        if original_path.exists():
            return {
                "error": f"Original path already occupied: {original_path}. "
                         f"Remove it first or manually move from {trash_path}."
            }

        # Verify hash if available (files only)
        if row["sha256"] and not row["is_dir"]:
            current_hash = _sha256(trash_path)
            if current_hash != row["sha256"]:
                return {
                    "error": "Hash mismatch -- file may have been corrupted in trash",
                    "expected": row["sha256"],
                    "actual": current_hash,
                }

        # Move back
        try:
            shutil.move(str(trash_path), str(original_path))
        except (OSError, PermissionError) as e:
            return {"error": f"Failed to restore: {e}"}

        # Remove manifest entry
        conn.execute("DELETE FROM trash_manifest WHERE id = ?", (entry_id,))
        conn.commit()

        logger.info("Restored: %s -> %s", trash_path, original_path)

        return {
            "restored": True,
            "original_path": str(original_path),
            "category": row["category"],
            "size_bytes": row["size_bytes"],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def list_trash(
    category: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """List current trash contents with metadata."""
    conn = get_connection()
    try:
        if category:
            rows = conn.execute(
                """SELECT * FROM trash_manifest
                WHERE category = ?
                ORDER BY deleted_at DESC LIMIT ?""",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM trash_manifest
                ORDER BY deleted_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "original_path": r["original_path"],
                "category": r["category"],
                "size_bytes": r["size_bytes"],
                "deleted_at": r["deleted_at"],
                "expires_at": r["expires_at"],
                "reason": r["reason"],
                "is_dir": bool(r["is_dir"]),
                "auto_deleted": bool(r["auto_deleted"]),
                "exists_in_trash": Path(r["trash_path"]).exists(),
            })

        total_size = sum(i["size_bytes"] for i in items)

        return {
            "count": len(items),
            "total_size": total_size,
            "items": items,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def sweep_expired() -> dict:
    """Permanently delete trash entries past their expiry date.

    Called by the daemon on a daily schedule.
    """
    ensure_data_dirs()
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    try:
        expired = conn.execute(
            "SELECT * FROM trash_manifest WHERE expires_at <= ?",
            (now,),
        ).fetchall()

        if not expired:
            return {"swept": 0, "freed_bytes": 0}

        swept = 0
        freed = 0
        errors = 0

        for row in expired:
            trash_path = Path(row["trash_path"])
            try:
                if trash_path.exists():
                    if trash_path.is_dir():
                        shutil.rmtree(str(trash_path))
                    else:
                        trash_path.unlink()
                    freed += row["size_bytes"]

                conn.execute("DELETE FROM trash_manifest WHERE id = ?", (row["id"],))
                swept += 1
            except Exception as e:
                logger.error("Failed to sweep %s: %s", trash_path, e)
                errors += 1

        conn.commit()

        if swept:
            logger.info("Trash sweep: %d items permanently deleted, %d bytes freed", swept, freed)

        return {
            "swept": swept,
            "freed_bytes": freed,
            "errors": errors,
        }
    except Exception as e:
        logger.error("sweep_expired failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def run_auto_cleanup() -> dict:
    """Full auto-cleanup pipeline: scan + auto-trash safe files.

    Called by the daemon or manually. Only trashes files that are:
    1. Matched by auto-trash patterns
    2. Git-ignored (not tracked)
    3. Not protected

    Returns summary of what was trashed.
    """
    scan_result = scan_files(include_auto=True, include_suspect=False)
    auto_items = scan_result.get("auto", [])

    if not auto_items:
        return {
            "scanned": True,
            "trashed": 0,
            "total_size": 0,
            "message": "No auto-trashable files found",
        }

    result = trash_batch(auto_items, auto=True)
    result["scanned"] = True
    return result
