"""File deletion watcher -- logs file deletions to SQLite via watchdog.

Runs as a background thread inside the daemon. Watches configured paths
and records deletion events to the file_deletion_log table.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import (
    DB_PATH,
    FILE_WATCHER_ENABLED,
    FILE_WATCHER_IGNORE_PATTERNS,
    FILE_WATCHER_PATHS,
)

logger = logging.getLogger(__name__)

# Default ignore patterns (noise that should never be logged)
_DEFAULT_IGNORE_PATTERNS = [
    "*/__pycache__/*",
    "*/__pycache__",
    "*.pyc",
    "*.pyo",
    "*/.pytest_cache/*",
    "*/.mypy_cache/*",
    "*/.ruff_cache/*",
    "*/.git/objects/*",
    "*/.git/refs/*",
    "*/.git/logs/*",
    "*/.git/index.lock",
    "*/node_modules/*",
    "*.tmp",
    "*.swp",
    "*.swo",
    "*~",
    "*/Thumbs.db",
    "*/.DS_Store",
]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _should_ignore(file_path: str, extra_patterns: list[str] | None = None) -> bool:
    """Check if a file path matches any ignore pattern."""
    all_patterns = _DEFAULT_IGNORE_PATTERNS + (extra_patterns or [])
    normalized = file_path.replace("\\", "/")
    for pattern in all_patterns:
        if fnmatch(normalized, pattern):
            return True
    return False


class DeletionHandler(FileSystemEventHandler):
    """Handles file/directory deletion events."""

    def __init__(self, extra_ignore_patterns: list[str] | None = None):
        super().__init__()
        self._extra_patterns = extra_ignore_patterns or []

    def on_deleted(self, event):
        file_path = event.src_path
        if _should_ignore(file_path, self._extra_patterns):
            return

        try:
            p = Path(file_path)
            self._log_deletion(
                file_path=str(p),
                filename=p.name,
                event_type="dir_deleted" if event.is_directory else "file_deleted",
            )
        except Exception:
            logger.debug("Failed to log deletion for %s", file_path, exc_info=True)

    def _log_deletion(
        self, file_path: str, filename: str, event_type: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = _get_conn()
            conn.execute(
                """INSERT INTO file_deletion_log
                (id, timestamp, file_path, filename, event_type, pid)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex[:12],
                    now,
                    file_path,
                    filename,
                    event_type,
                    os.getpid(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            logger.debug("Failed to write deletion log", exc_info=True)


class FileWatcherThread:
    """Manages the watchdog observer in a background thread."""

    def __init__(self):
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        if not FILE_WATCHER_ENABLED:
            logger.info("File watcher disabled via config")
            return

        handler = DeletionHandler(
            extra_ignore_patterns=FILE_WATCHER_IGNORE_PATTERNS
        )
        self._observer = Observer()

        for watch_path in FILE_WATCHER_PATHS:
            p = Path(watch_path)
            if p.exists() and p.is_dir():
                self._observer.schedule(handler, str(p), recursive=True)
                logger.info("File watcher watching: %s", p)
            else:
                logger.warning("File watcher path does not exist: %s", p)

        self._observer.daemon = True  # Die with main thread
        self._observer.start()
        logger.info("File watcher started")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("File watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()


def query_deletions(
    path: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query the file deletion log."""
    conn = _get_conn()
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT * FROM file_deletion_log WHERE 1=1"
        params: list = []
        if path:
            query += " AND file_path LIKE ?"
            params.append(f"%{path}%")
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
