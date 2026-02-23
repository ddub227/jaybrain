"""JayBrain daemon -- long-running APScheduler process for proactive tasks.

Manages scheduled modules (conversation archive, heartbeat checks, life domain
sync, event discovery) via APScheduler 3.x. Writes health state to the
daemon_state single-row table so MCP tools can report status.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import (
    DAEMON_HEARTBEAT_INTERVAL,
    DAEMON_PID_FILE,
    DB_PATH,
    ensure_data_dirs,
)

logger = logging.getLogger(__name__)


def _get_raw_conn() -> sqlite3.Connection:
    """Lightweight connection without sqlite-vec (daemon doesn't need vectors)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_daemon_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daemon_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            pid INTEGER,
            started_at TEXT,
            last_heartbeat TEXT,
            modules TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'stopped'
        );
    """)
    conn.commit()


class DaemonManager:
    """Manages the JayBrain daemon lifecycle and scheduled modules."""

    def __init__(self) -> None:
        self.scheduler = BlockingScheduler()
        self._modules: dict[str, dict] = {}
        self._running = False
        self._pid = os.getpid()

    def register_module(
        self,
        name: str,
        func: Callable,
        trigger: CronTrigger | IntervalTrigger,
        description: str = "",
    ) -> None:
        """Register a scheduled module with the daemon."""
        self._modules[name] = {
            "func": func,
            "trigger": trigger,
            "description": description,
        }
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Registered module: %s (%s)", name, description)

    def _write_heartbeat(self) -> None:
        """Update daemon_state with current heartbeat."""
        now = datetime.now(timezone.utc).isoformat()
        module_names = json.dumps(list(self._modules.keys()))
        conn = _get_raw_conn()
        try:
            _ensure_daemon_table(conn)
            conn.execute(
                """INSERT INTO daemon_state (id, pid, started_at, last_heartbeat, modules, status)
                VALUES (1, ?, ?, ?, ?, 'running')
                ON CONFLICT(id) DO UPDATE SET
                    last_heartbeat = excluded.last_heartbeat,
                    modules = excluded.modules,
                    status = 'running'""",
                (self._pid, now, now, module_names),
            )
            conn.commit()
        except Exception as e:
            logger.error("Heartbeat write failed: %s", e)
        finally:
            conn.close()

    def _write_status(self, status: str) -> None:
        """Update daemon_state status field."""
        now = datetime.now(timezone.utc).isoformat()
        module_names = json.dumps(list(self._modules.keys()))
        conn = _get_raw_conn()
        try:
            _ensure_daemon_table(conn)
            conn.execute(
                """INSERT INTO daemon_state (id, pid, started_at, last_heartbeat, modules, status)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    pid = excluded.pid,
                    started_at = excluded.started_at,
                    last_heartbeat = excluded.last_heartbeat,
                    modules = excluded.modules,
                    status = excluded.status""",
                (self._pid, now, now, module_names, status),
            )
            conn.commit()
        except Exception as e:
            logger.error("Status write failed: %s", e)
        finally:
            conn.close()

    def _handle_shutdown(self, signum: int, frame) -> None:
        """Graceful shutdown on SIGTERM/SIGINT."""
        logger.info("Received signal %s, shutting down...", signum)
        self._running = False
        self.scheduler.shutdown(wait=False)
        self._write_status("stopped")
        DAEMON_PID_FILE.unlink(missing_ok=True)
        logger.info("Daemon stopped.")

    def start(self) -> None:
        """Start the daemon: write PID, register heartbeat, start scheduler."""
        ensure_data_dirs()

        # Write PID file
        DAEMON_PID_FILE.write_text(str(self._pid))

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        # Register heartbeat job
        self.scheduler.add_job(
            self._write_heartbeat,
            trigger=IntervalTrigger(seconds=DAEMON_HEARTBEAT_INTERVAL),
            id="_heartbeat",
            name="Daemon heartbeat",
            replace_existing=True,
        )

        self._running = True
        self._write_status("running")
        logger.info(
            "Daemon started (pid=%d, modules=%s)",
            self._pid,
            list(self._modules.keys()),
        )

        # Initial heartbeat
        self._write_heartbeat()

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._write_status("stopped")
            DAEMON_PID_FILE.unlink(missing_ok=True)
            logger.info("Daemon exited.")

    @property
    def modules(self) -> list[str]:
        return list(self._modules.keys())


def get_daemon_status() -> dict:
    """Read current daemon status from the DB. Used by MCP tools."""
    conn = _get_raw_conn()
    try:
        _ensure_daemon_table(conn)
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
        if not row:
            return {
                "status": "stopped",
                "pid": None,
                "started_at": None,
                "last_heartbeat": None,
                "modules": [],
            }
        # Check if PID is still alive
        pid = row["pid"]
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except (OSError, ProcessLookupError):
                pass

        status = row["status"] if alive else "stopped"
        return {
            "status": status,
            "pid": pid,
            "started_at": row["started_at"],
            "last_heartbeat": row["last_heartbeat"],
            "modules": json.loads(row["modules"]) if row["modules"] else [],
            "process_alive": alive,
        }
    finally:
        conn.close()


def daemon_control(action: str) -> dict:
    """Control the daemon. Actions: stop, restart (stop handled via PID signal)."""
    import subprocess

    if action == "stop":
        status = get_daemon_status()
        pid = status.get("pid")
        if not pid or not status.get("process_alive"):
            return {"status": "not_running", "message": "Daemon is not running"}
        try:
            os.kill(pid, signal.SIGTERM)
            return {"status": "stopping", "message": f"Sent SIGTERM to pid {pid}"}
        except (OSError, ProcessLookupError) as e:
            return {"status": "error", "message": str(e)}

    elif action == "start":
        status = get_daemon_status()
        if status.get("process_alive"):
            return {
                "status": "already_running",
                "message": f"Daemon already running (pid={status['pid']})",
            }
        # Launch via start_daemon.py --daemon
        script = Path(__file__).parent.parent.parent / "scripts" / "start_daemon.py"
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script), "--daemon"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"status": "starting", "message": f"Launcher spawned (pid={proc.pid})"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    else:
        return {"status": "error", "message": f"Unknown action: {action}"}


def build_daemon() -> DaemonManager:
    """Build a DaemonManager with all registered modules.

    Imports are deferred so modules only load when the daemon actually runs.
    """
    dm = DaemonManager()

    # Phase 1: Conversation archive at 2 AM daily
    try:
        from .conversation_archive import run_archive
        dm.register_module(
            "conversation_archive",
            run_archive,
            CronTrigger(hour=2, minute=0),
            "Nightly conversation archive to Google Docs",
        )
    except ImportError:
        logger.debug("conversation_archive module not available, skipping")

    # Phase 2: Life domains weekly sync (Sunday 3 AM) + daily metrics (6:30 AM)
    try:
        from .life_domains import sync_from_gdoc, collect_auto_metrics
        dm.register_module(
            "life_domains_sync",
            sync_from_gdoc,
            CronTrigger(day_of_week="sun", hour=3, minute=0),
            "Weekly Life Domains Google Doc sync",
        )
        dm.register_module(
            "life_domains_metrics",
            collect_auto_metrics,
            CronTrigger(hour=6, minute=30),
            "Daily auto-metric collection for goals",
        )
    except ImportError:
        logger.debug("life_domains module not available, skipping")

    # Phase 3: Heartbeat checks
    try:
        from .heartbeat import (
            check_forge_study_morning,
            check_forge_study_evening,
            check_exam_countdown,
            check_stale_applications,
            check_session_crash,
            check_goal_staleness,
        )
        dm.register_module(
            "session_crash_check",
            check_session_crash,
            IntervalTrigger(minutes=30),
            "Detect stalled Claude Code sessions",
        )
        dm.register_module(
            "forge_study_morning",
            check_forge_study_morning,
            CronTrigger(hour=7, minute=0),
            "Morning forge study reminder",
        )
        dm.register_module(
            "exam_countdown",
            check_exam_countdown,
            CronTrigger(hour=7, minute=15),
            "Daily Security+ exam countdown",
        )
        dm.register_module(
            "stale_applications",
            check_stale_applications,
            CronTrigger(hour=9, minute=0),
            "Check for stale job applications",
        )
        dm.register_module(
            "forge_study_evening",
            check_forge_study_evening,
            CronTrigger(hour=19, minute=0),
            "Evening forge study reminder",
        )
        dm.register_module(
            "goal_staleness",
            check_goal_staleness,
            CronTrigger(day_of_week="sun", hour=20, minute=0),
            "Weekly goal staleness check",
        )
    except ImportError:
        logger.debug("heartbeat module not available, skipping")

    # Phase 4: Event discovery (Monday 8 AM)
    try:
        from .event_discovery import run_event_discovery
        dm.register_module(
            "event_discovery",
            run_event_discovery,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            "Weekly local event discovery",
        )
    except ImportError:
        logger.debug("event_discovery module not available, skipping")

    return dm
