"""Scratch pad — temporary file storage with 30-day auto-cleanup.

Usage: User says "scratch[title]" and Claude writes the content to
~/Documents/scratch/title_formatted.md with a creation timestamp.
The daemon sweeps files older than 30 days.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCRATCH_DIR = Path(os.path.expanduser("~/Documents/scratch"))
MAX_AGE_DAYS = 30
TIMESTAMP_PREFIX = "<!-- scratch_created: "


def ensure_scratch_dir() -> None:
    """Create the scratch directory if it doesn't exist."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def _parse_created_at(filepath: Path) -> datetime | None:
    """Read the scratch_created timestamp from a file's first line."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith(TIMESTAMP_PREFIX):
            ts_str = first_line[len(TIMESTAMP_PREFIX) :].rstrip(" ->")
            return datetime.fromisoformat(ts_str)
    except Exception:
        pass
    return None


def run_scratch_cleanup() -> dict:
    """Delete scratch files older than 30 days.

    Called by the daemon on a daily schedule.
    """
    ensure_scratch_dir()

    if not SCRATCH_DIR.exists():
        return {"swept": 0, "freed_bytes": 0, "message": "Scratch dir does not exist"}

    swept = 0
    freed = 0
    errors = 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    for filepath in SCRATCH_DIR.iterdir():
        if filepath.is_dir() or filepath.name.startswith("."):
            continue

        try:
            created_at = _parse_created_at(filepath)

            # Fallback: use file modification time if no timestamp header
            if created_at is None:
                mtime = filepath.stat().st_mtime
                created_at = datetime.fromtimestamp(mtime, tz=timezone.utc)

            if created_at <= cutoff:
                size = filepath.stat().st_size
                filepath.unlink()
                swept += 1
                freed += size
                logger.info("Scratch cleanup: deleted %s (age: %s days)",
                            filepath.name,
                            (now - created_at).days)
        except Exception as e:
            logger.error("Failed to clean scratch file %s: %s", filepath, e)
            errors += 1

    return {
        "swept": swept,
        "freed_bytes": freed,
        "errors": errors,
    }
