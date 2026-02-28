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
        self._file_watcher = None

    def register_module(
        self,
        name: str,
        func: Callable,
        trigger: CronTrigger | IntervalTrigger,
        description: str = "",
        misfire_grace_time: int | None = 300,
    ) -> None:
        """Register a scheduled module with the daemon.

        Args:
            misfire_grace_time: Seconds after the scheduled time that a missed
                job is still allowed to run.  ``None`` means "always run, no
                matter how late" (use for user-facing notifications that should
                catch up after sleep/standby).  Default is 300 s (5 min).
        """
        # Wrap the function to log execution to daemon_execution_log
        wrapped = self._wrap_with_logging(name, func)
        self._modules[name] = {
            "func": wrapped,
            "trigger": trigger,
            "description": description,
        }
        self.scheduler.add_job(
            wrapped,
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=True,
            misfire_grace_time=misfire_grace_time,
            coalesce=True,
        )
        logger.info("Registered module: %s (%s)", name, description)

    def _wrap_with_logging(self, module_name: str, func: Callable) -> Callable:
        """Wrap a module function to log execution to daemon_execution_log."""
        def wrapper():
            start_time = datetime.now(timezone.utc)
            start_iso = start_time.isoformat()
            row_id = None
            try:
                conn = _get_raw_conn()
                cur = conn.execute(
                    """INSERT INTO daemon_execution_log
                    (module_name, started_at, status)
                    VALUES (?, ?, 'running')""",
                    (module_name, start_iso),
                )
                row_id = cur.lastrowid
                conn.commit()
                conn.close()
            except Exception:
                pass  # Logging failure must never prevent execution

            status = "success"
            error_msg = ""
            result = None
            try:
                result = func()
            except Exception as e:
                status = "error"
                error_msg = str(e)[:500]
                logger.error("Module %s failed: %s", module_name, e, exc_info=True)

            # Update the execution log with result
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            summary = ""
            telegram_sent = 0
            if isinstance(result, dict):
                summary = str(result)[:200]
                if result.get("status") == "sent" or result.get("telegram", {}).get("status") == "sent":
                    telegram_sent = 1

            if row_id is not None:
                try:
                    conn = _get_raw_conn()
                    conn.execute(
                        """UPDATE daemon_execution_log SET
                        finished_at=?, status=?, result_summary=?,
                        error_message=?, telegram_sent=?, duration_ms=?
                        WHERE id=?""",
                        (end_time.isoformat(), status, summary,
                         error_msg, telegram_sent, duration_ms, row_id),
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

        return wrapper

    def _log_lifecycle(self, event_type: str, error: str = "") -> None:
        """Log a daemon lifecycle event (start, stop, crash)."""
        try:
            conn = _get_raw_conn()
            conn.execute(
                """INSERT INTO daemon_lifecycle_log
                (event_type, pid, timestamp, modules_registered, trigger, error_message)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    self._pid,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(list(self._modules.keys())),
                    "task_scheduler" if sys.platform == "win32" else "manual",
                    error,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _write_heartbeat(self) -> None:
        """Update daemon_state with current heartbeat.

        Also checks for PID collision: if another daemon has overwritten
        daemon_state with a different PID, this instance shuts down to
        prevent dual-daemon conflicts.
        """
        now = datetime.now(timezone.utc).isoformat()
        module_names = json.dumps(list(self._modules.keys()))
        conn = _get_raw_conn()
        try:
            _ensure_daemon_table(conn)
            # Check for PID collision before writing
            row = conn.execute(
                "SELECT pid FROM daemon_state WHERE id = 1"
            ).fetchone()
            if row and row[0] and row[0] != self._pid:
                other_pid = row[0]
                # Verify the other PID is actually alive
                if _is_pid_alive(other_pid):
                    logger.error(
                        "PID COLLISION: daemon_state shows PID %d but we are PID %d. "
                        "Another daemon is running. Shutting down to prevent conflicts.",
                        other_pid, self._pid,
                    )
                    self._log_lifecycle("collision_shutdown",
                                        f"Detected rival PID {other_pid}")
                    self._handle_shutdown(None, None)
                    return

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
        # Stop file watcher thread
        if self._file_watcher:
            try:
                self._file_watcher.stop()
            except Exception:
                pass
        # Release sleep prevention so Windows can sleep normally after daemon stops
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS only = release
            except Exception:
                pass
        try:
            self._write_status("stopped")
        except Exception:
            pass
        self._log_lifecycle("stopped")
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

                # Prevent Windows from sleeping while the daemon is running.
                # ES_CONTINUOUS | ES_SYSTEM_REQUIRED tells Windows: "keep the
                # system awake as long as this process is alive." This works
                # with Modern Standby (S0 Low Power Idle) which ignores the
                # traditional "Sleep after = Never" power plan setting.
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                result = kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                )
                if result:
                    logger.info("SetThreadExecutionState: system sleep prevention active")
                else:
                    logger.warning("SetThreadExecutionState failed — system may sleep")

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

        # Pre-startup check: refuse to start if another daemon is alive in DB
        conn = _get_raw_conn()
        try:
            _ensure_daemon_table(conn)
            row = conn.execute(
                "SELECT pid FROM daemon_state WHERE id = 1"
            ).fetchone()
            if row and row[0] and row[0] != self._pid:
                if _is_pid_alive(row[0]):
                    logger.error(
                        "STARTUP REFUSED: daemon_state shows alive PID %d, "
                        "we are PID %d. Exiting.",
                        row[0], self._pid,
                    )
                    self._log_lifecycle(
                        "startup_refused",
                        f"Rival PID {row[0]} is alive"
                    )
                    conn.close()
                    return
        except Exception:
            logger.debug("Pre-startup PID check failed, proceeding anyway", exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
        self._log_lifecycle("started")
        logger.info(
            "Daemon started (pid=%d, modules=%s)",
            self._pid,
            list(self._modules.keys()),
        )

        # Initial heartbeat
        self._write_heartbeat()

        # Start file watcher thread (companion, not scheduled)
        try:
            from .file_watcher import FileWatcherThread
            self._file_watcher = FileWatcherThread()
            self._file_watcher.start()
        except Exception:
            logger.error("Failed to start file watcher", exc_info=True)

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
            misfire_grace_time=None,
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
            misfire_grace_time=None,
        )
        dm.register_module(
            "exam_countdown",
            check_exam_countdown,
            CronTrigger(hour=7, minute=15),
            "Daily Security+ exam countdown",
            misfire_grace_time=None,
        )
        dm.register_module(
            "stale_applications",
            check_stale_applications,
            CronTrigger(hour=9, minute=0),
            "Check for stale job applications",
            misfire_grace_time=None,
        )
        dm.register_module(
            "forge_study_evening",
            check_forge_study_evening,
            CronTrigger(hour=19, minute=0),
            "Evening forge study reminder",
            misfire_grace_time=None,
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

    # Phase 5: Job board auto-fetch (Wednesday 10 AM weekly)
    try:
        from .job_boards import auto_fetch_boards
        dm.register_module(
            "job_board_autofetch",
            auto_fetch_boards,
            CronTrigger(day_of_week="wed", hour=10, minute=0),
            "Weekly job board change detection",
        )
    except Exception:
        logger.error("Failed to register job_board_autofetch module", exc_info=True)

    # Phase 7: Obsidian vault sync (every 60 seconds)
    try:
        from .vault_sync import run_vault_sync
        from .config import VAULT_SYNC_INTERVAL_SECONDS
        dm.register_module(
            "vault_sync",
            run_vault_sync,
            IntervalTrigger(seconds=VAULT_SYNC_INTERVAL_SECONDS),
            "Sync JayBrain DB to Obsidian vault",
        )
    except Exception:
        logger.error("Failed to register vault_sync module", exc_info=True)

    # Phase 8: GitShadow -- working tree snapshots every 10 min
    try:
        from .git_shadow import run_git_shadow
        from .config import GIT_SHADOW_INTERVAL_SECONDS
        dm.register_module(
            "git_shadow",
            run_git_shadow,
            IntervalTrigger(seconds=GIT_SHADOW_INTERVAL_SECONDS),
            "Periodic git working tree snapshots",
        )
    except Exception:
        logger.error("Failed to register git_shadow module", exc_info=True)

    # Phase 6: Trash -- weekly auto-cleanup (Sunday 2 AM) + daily expiry sweep (3 AM)
    try:
        from .trash import run_auto_cleanup, sweep_expired
        dm.register_module(
            "trash_auto_cleanup",
            run_auto_cleanup,
            CronTrigger(day_of_week="sun", hour=2, minute=0),
            "Weekly auto-cleanup of gitignored garbage",
        )
        dm.register_module(
            "trash_sweep",
            sweep_expired,
            CronTrigger(hour=3, minute=0),
            "Daily sweep of expired trash entries",
        )
    except Exception:
        logger.error("Failed to register trash module", exc_info=True)

    # Phase: Feedly AI Feed monitor (every N minutes)
    try:
        from .feedly import run_feedly_monitor
        from .config import FEEDLY_POLL_INTERVAL_MINUTES

        dm.register_module(
            "feedly_monitor",
            run_feedly_monitor,
            IntervalTrigger(minutes=FEEDLY_POLL_INTERVAL_MINUTES),
            "Poll Feedly AI Feed for new articles",
        )
    except Exception:
        logger.error("Failed to register feedly_monitor module", exc_info=True)

    # Phase: News Feed multi-source poll (every N minutes)
    try:
        from .news_feeds import run_news_feed_poll
        from .config import NEWS_FEED_POLL_INTERVAL_MINUTES

        dm.register_module(
            "news_feed_poll",
            run_news_feed_poll,
            IntervalTrigger(minutes=NEWS_FEED_POLL_INTERVAL_MINUTES),
            "Poll all news feed sources for new articles",
        )
    except Exception:
        logger.error("Failed to register news_feed_poll module", exc_info=True)

    # Phase: SignalForge article fetching (every N minutes)
    try:
        from .signalforge import run_signalforge_fetch
        from .config import SIGNALFORGE_FETCH_INTERVAL_MINUTES

        dm.register_module(
            "signalforge_fetch",
            run_signalforge_fetch,
            IntervalTrigger(minutes=SIGNALFORGE_FETCH_INTERVAL_MINUTES),
            "Fetch full article text for SignalForge",
        )
    except Exception:
        logger.error("Failed to register signalforge_fetch module", exc_info=True)

    # Phase: SignalForge cleanup (daily at configured hour)
    try:
        from .signalforge import run_signalforge_cleanup
        from .config import SIGNALFORGE_CLEANUP_HOUR

        dm.register_module(
            "signalforge_cleanup",
            run_signalforge_cleanup,
            CronTrigger(hour=SIGNALFORGE_CLEANUP_HOUR, minute=0),
            "Clean up expired SignalForge article files",
        )
    except Exception:
        logger.error("Failed to register signalforge_cleanup module", exc_info=True)

    # Phase: SignalForge clustering (every N hours)
    try:
        from .signalforge import run_signalforge_clustering
        from .config import SIGNALFORGE_CLUSTER_INTERVAL_HOURS

        dm.register_module(
            "signalforge_clustering",
            run_signalforge_clustering,
            IntervalTrigger(hours=SIGNALFORGE_CLUSTER_INTERVAL_HOURS),
            "Cluster related SignalForge articles into stories",
        )
    except Exception:
        logger.error("Failed to register signalforge_clustering module", exc_info=True)

    # Post-registration audit: log how many modules registered and warn if low
    expected_modules = {
        "conversation_archive", "daily_briefing", "life_domains_sync",
        "life_domains_metrics", "session_crash_check", "forge_study_morning",
        "exam_countdown", "stale_applications", "forge_study_evening",
        "goal_staleness", "time_allocation_weekly", "network_decay",
        "event_discovery", "job_board_autofetch", "vault_sync",
        "trash_auto_cleanup", "trash_sweep", "git_shadow",
        "feedly_monitor", "news_feed_poll",
        "signalforge_fetch", "signalforge_cleanup", "signalforge_clustering",
    }
    registered = set(dm.modules)
    missing = expected_modules - registered
    if missing:
        logger.error(
            "MODULE REGISTRATION INCOMPLETE: %d/%d modules registered. "
            "Missing: %s",
            len(registered), len(expected_modules), sorted(missing),
        )
    else:
        logger.info(
            "All %d expected modules registered successfully.",
            len(registered),
        )

    return dm
