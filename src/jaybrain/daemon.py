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
    DAILY_BRIEFING_HOUR,
    DAILY_BRIEFING_MINUTE,
    DB_PATH,
    NETWORK_DECAY_NUDGE_DAY,
    NETWORK_DECAY_NUDGE_HOUR,
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

    def _cleanup(self) -> None:
        """Ensure stopped state is written on exit."""
        if not self._running:
            return
        self._running = False
        try:
            self._write_status("stopped")
        except Exception:
            pass
        try:
            DAEMON_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("Daemon cleanup complete.")

    def start(self) -> None:
        """Start the daemon: write PID, register heartbeat, start scheduler."""
        import atexit

        ensure_data_dirs()

        # Write PID file
        DAEMON_PID_FILE.write_text(str(self._pid))

        # Register cleanup via atexit (works on Windows when process exits normally)
        atexit.register(self._cleanup)

        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, self._handle_shutdown)

        # On Windows, use SetConsoleCtrlHandler for CTRL_CLOSE/CTRL_SHUTDOWN events
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32

                @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
                def _win_handler(ctrl_type):
                    # 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE, 5=CTRL_LOGOFF, 6=CTRL_SHUTDOWN
                    logger.info("Windows control event %d, shutting down...", ctrl_type)
                    self._handle_shutdown(ctrl_type, None)
                    return 1  # Handled

                self._win_handler_ref = _win_handler  # prevent GC
                kernel32.SetConsoleCtrlHandler(_win_handler, 1)
            except Exception as e:
                logger.debug("Could not set Windows ctrl handler: %s", e)

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
            logger.info("Scheduler stopped by interrupt/exit.")
        except Exception as e:
            logger.error("Scheduler crashed: %s", e, exc_info=True)
        finally:
            self._cleanup()

    @property
    def modules(self) -> list[str]:
        return list(self._modules.keys())


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is still running. Works on Windows Store Python."""
    if sys.platform == "win32":
        # os.kill(pid, 0) doesn't work reliably on Windows Store Python
        # due to app container permissions. Use tasklist instead.
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


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
        alive = _is_pid_alive(pid) if pid else False

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
            if sys.platform == "win32":
                # On Windows, SIGTERM doesn't work for background processes.
                # Use taskkill which triggers atexit/ctrl handlers.
                import subprocess as _sp
                _sp.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            # Give it a moment then update DB if process didn't clean up
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                # Process is gone -- ensure DB reflects stopped state
                conn = _get_raw_conn()
                try:
                    _ensure_daemon_table(conn)
                    conn.execute(
                        "UPDATE daemon_state SET status = 'stopped' WHERE id = 1"
                    )
                    conn.commit()
                finally:
                    conn.close()
            return {"status": "stopped", "message": f"Daemon pid {pid} stopped"}
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
    except Exception:
        logger.error("Failed to register conversation_archive module", exc_info=True)

    # Phase 1b: Daily Telegram briefing
    try:
        from .daily_briefing import run_telegram_briefing
        dm.register_module(
            "daily_briefing",
            run_telegram_briefing,
            CronTrigger(hour=DAILY_BRIEFING_HOUR, minute=DAILY_BRIEFING_MINUTE),
            "Morning Telegram briefing digest",
        )
    except Exception:
        logger.error("Failed to register daily_briefing module", exc_info=True)

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
    except Exception:
        logger.error("Failed to register life_domains module", exc_info=True)

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
    except Exception:
        logger.error("Failed to register heartbeat module", exc_info=True)

    # Phase 3b: Time allocation weekly check (Sunday 8:30 PM)
    try:
        from .time_allocation import check_time_allocation
        dm.register_module(
            "time_allocation_weekly",
            check_time_allocation,
            CronTrigger(day_of_week="sun", hour=20, minute=30),
            "Weekly time allocation vs targets report",
        )
    except Exception:
        logger.error("Failed to register time_allocation module", exc_info=True)

    # Phase 3c: Network decay midweek check
    try:
        from .network_decay import check_network_decay
        dm.register_module(
            "network_decay",
            check_network_decay,
            CronTrigger(
                day_of_week=NETWORK_DECAY_NUDGE_DAY,
                hour=NETWORK_DECAY_NUDGE_HOUR,
                minute=0,
            ),
            "Midweek network relationship check",
        )
    except Exception:
        logger.error("Failed to register network_decay module", exc_info=True)

    # Phase 4: Event discovery (Monday 8 AM)
    try:
        from .event_discovery import run_event_discovery
        dm.register_module(
            "event_discovery",
            run_event_discovery,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            "Weekly local event discovery",
        )
    except Exception:
        logger.error("Failed to register event_discovery module", exc_info=True)

    return dm
