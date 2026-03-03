#!/usr/bin/env python3
"""JayBrain Daemon Watchdog -- monitors and auto-restarts the daemon.

Checks daemon health via the daemon_state table:
  1. Is the PID alive?
  2. Is the heartbeat fresh (< STALE_THRESHOLD seconds old)?

If either check fails, the daemon is restarted automatically.
Logs all events to the watchdog_log table and optionally notifies via Telegram.

Designed to run as a Windows Task Scheduler job every 5 minutes.

Usage:
    Check & restart:   python scripts/daemon_watchdog.py
    Install task:      python scripts/daemon_watchdog.py --install
    Uninstall task:    python scripts/daemon_watchdog.py --uninstall
    Show log:          python scripts/daemon_watchdog.py --log
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "jaybrain.db"
START_DAEMON_SCRIPT = PROJECT_ROOT / "scripts" / "start_daemon.py"

# If daemon heartbeat is older than this, consider it frozen
STALE_THRESHOLD_SECONDS = 300  # 5 minutes (heartbeat writes every 60s)

# Task Scheduler config
TASK_NAME = "JayBrainWatchdog"
CHECK_INTERVAL_MINUTES = 5


def _get_conn() -> sqlite3.Connection:
    """Lightweight DB connection."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_watchdog_table(conn: sqlite3.Connection) -> None:
    """Create the watchdog_log table if it doesn't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS watchdog_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            daemon_pid INTEGER,
            heartbeat_age_seconds REAL,
            action_taken TEXT NOT NULL DEFAULT '',
            restart_pid INTEGER,
            error_message TEXT NOT NULL DEFAULT '',
            telegram_sent INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_watchdog_log_ts
            ON watchdog_log(timestamp);
    """)
    conn.commit()


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is running. Windows-compatible."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
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


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO timestamp string to datetime (UTC)."""
    # Handle both with and without timezone info
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _send_telegram(message: str) -> bool:
    """Send a Telegram notification via JayBrain's telegram_send_log pattern.

    Uses the Telegram bot token from environment to send directly.
    Returns True if sent successfully, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_AUTHORIZED_USER", "")
    if not token or not chat_id:
        return False

    try:
        import urllib.request
        import urllib.parse

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def _load_env() -> None:
    """Load .env from project root if present."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not os.environ.get(key):
                os.environ[key] = value


def _log_event(
    conn: sqlite3.Connection,
    event_type: str,
    daemon_pid: int | None = None,
    heartbeat_age: float | None = None,
    action: str = "",
    restart_pid: int | None = None,
    error: str = "",
    telegram_sent: bool = False,
) -> None:
    """Write an event to the watchdog_log table."""
    conn.execute(
        """INSERT INTO watchdog_log
        (timestamp, event_type, daemon_pid, heartbeat_age_seconds,
         action_taken, restart_pid, error_message, telegram_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            event_type,
            daemon_pid,
            heartbeat_age,
            action,
            restart_pid,
            error,
            1 if telegram_sent else 0,
        ),
    )
    conn.commit()


def _restart_daemon() -> int | None:
    """Restart the daemon via start_daemon.py. Returns new PID or None."""
    try:
        # First, try to stop any zombie process cleanly
        subprocess.run(
            [sys.executable, str(START_DAEMON_SCRIPT), "--stop"],
            capture_output=True, text=True, timeout=10,
        )
        time.sleep(2)

        # Start fresh in daemon mode
        result = subprocess.run(
            [sys.executable, str(START_DAEMON_SCRIPT), "--daemon"],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            return None

        # Wait for PID file to appear
        pid_file = DATA_DIR / "daemon.pid"
        for _ in range(10):
            time.sleep(1)
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    if _is_pid_alive(pid):
                        return pid
                except (ValueError, FileNotFoundError):
                    pass

        # Fallback: check daemon_state
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT pid FROM daemon_state WHERE id = 1 AND status = 'running'"
            ).fetchone()
            conn.close()
            if row and row["pid"]:
                pid = int(row["pid"])
                if _is_pid_alive(pid):
                    return pid
        except Exception:
            pass

        return None
    except Exception:
        return None


def check_and_restart() -> dict:
    """Main watchdog logic. Returns a status dict."""
    _load_env()

    if not DB_PATH.exists():
        return {"status": "no_db", "message": "Database not found. Daemon never started."}

    conn = _get_conn()
    _ensure_watchdog_table(conn)

    # Read daemon state
    try:
        row = conn.execute("SELECT * FROM daemon_state WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        # daemon_state table doesn't exist yet
        conn.close()
        return {"status": "no_table", "message": "daemon_state table missing."}

    if not row:
        # No daemon has ever started — start it
        print("[watchdog] No daemon state found. Starting daemon...")
        new_pid = _restart_daemon()
        if new_pid:
            _log_event(conn, "first_start", action="started daemon", restart_pid=new_pid)
            msg = f"[watchdog] Daemon started for the first time (pid={new_pid})"
            print(msg)
            conn.close()
            return {"status": "started", "pid": new_pid, "reason": "first_start"}
        else:
            _log_event(conn, "start_failed", action="attempted first start",
                       error="Could not start daemon")
            print("[watchdog] ERROR: Failed to start daemon.")
            conn.close()
            return {"status": "error", "message": "Failed to start daemon"}

    daemon_pid = row["pid"]
    status = row["status"]
    last_heartbeat = row["last_heartbeat"]

    # Check 1: Is the process alive? Retry up to 3 times (1s apart) to guard
    # against transient WMI failures on Windows that produce false negatives.
    pid_alive = False
    if daemon_pid:
        for _attempt in range(3):
            if _is_pid_alive(daemon_pid):
                pid_alive = True
                break
            if _attempt < 2:
                time.sleep(1)

    # Check 2: Is the heartbeat fresh?
    heartbeat_age = None
    heartbeat_stale = False
    if last_heartbeat:
        hb_time = _parse_iso(last_heartbeat)
        now = datetime.now(timezone.utc)
        heartbeat_age = (now - hb_time).total_seconds()
        heartbeat_stale = heartbeat_age > STALE_THRESHOLD_SECONDS

    # Decision logic
    needs_restart = False
    reason = ""

    if not pid_alive:
        needs_restart = True
        reason = f"pid_dead (pid={daemon_pid} not running)"
    elif heartbeat_stale:
        needs_restart = True
        reason = f"heartbeat_stale ({heartbeat_age:.0f}s old, threshold={STALE_THRESHOLD_SECONDS}s)"
    elif status == "stopped":
        needs_restart = True
        reason = "status_stopped (daemon_state shows stopped)"

    if not needs_restart:
        # Daemon is healthy
        _log_event(conn, "check_ok", daemon_pid=daemon_pid,
                   heartbeat_age=heartbeat_age, action="no action needed")
        msg = f"[watchdog] Daemon healthy (pid={daemon_pid}, heartbeat={heartbeat_age:.0f}s ago)"
        print(msg)
        conn.close()
        return {
            "status": "healthy",
            "pid": daemon_pid,
            "heartbeat_age_seconds": heartbeat_age,
        }

    # Restart needed
    print(f"[watchdog] Daemon unhealthy: {reason}")
    print("[watchdog] Attempting restart...")

    new_pid = _restart_daemon()

    if new_pid:
        telegram_msg = (
            f"*JayBrain Watchdog* 🔄\n\n"
            f"Daemon restarted automatically.\n"
            f"Reason: `{reason}`\n"
            f"Old PID: `{daemon_pid}`\n"
            f"New PID: `{new_pid}`"
        )
        telegram_ok = _send_telegram(telegram_msg)

        _log_event(conn, "restart_success", daemon_pid=daemon_pid,
                   heartbeat_age=heartbeat_age,
                   action=f"restarted: {reason}",
                   restart_pid=new_pid,
                   telegram_sent=telegram_ok)

        msg = f"[watchdog] Daemon restarted successfully (new pid={new_pid})"
        print(msg)
        conn.close()
        return {
            "status": "restarted",
            "old_pid": daemon_pid,
            "new_pid": new_pid,
            "reason": reason,
            "telegram_sent": telegram_ok,
        }
    else:
        telegram_msg = (
            f"*JayBrain Watchdog* ⚠️\n\n"
            f"Daemon restart FAILED.\n"
            f"Reason: `{reason}`\n"
            f"Manual intervention needed."
        )
        telegram_ok = _send_telegram(telegram_msg)

        _log_event(conn, "restart_failed", daemon_pid=daemon_pid,
                   heartbeat_age=heartbeat_age,
                   action=f"restart failed: {reason}",
                   error="start_daemon.py did not produce alive PID",
                   telegram_sent=telegram_ok)

        print("[watchdog] ERROR: Restart failed! Manual intervention needed.")
        conn.close()
        return {
            "status": "restart_failed",
            "old_pid": daemon_pid,
            "reason": reason,
            "telegram_sent": telegram_ok,
        }


def install_scheduled_task() -> None:
    """Register the watchdog as a Windows Task Scheduler job."""
    if sys.platform != "win32":
        print("Task Scheduler installation is Windows-only.")
        print("On Linux/macOS, add a cron job instead:")
        print(f"  */5 * * * * {sys.executable} {Path(__file__).resolve()}")
        return

    script_path = str(Path(__file__).resolve())
    # Use pythonw.exe (no console window) if available
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    python_path = str(pythonw) if pythonw.exists() else sys.executable

    # Delete existing task if any
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
    )

    # Create a task that runs every N minutes (no window popup)
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", f'"{python_path}" "{script_path}"',
            "/SC", "MINUTE",
            "/MO", str(CHECK_INTERVAL_MINUTES),
            "/F",
        ],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"Failed to create scheduled task: {result.stderr}")
        return

    # Fix power settings so it runs on battery too
    try:
        ps_script = (
            "$ts = New-Object -ComObject Schedule.Service; "
            "$ts.Connect(); "
            f"$t = $ts.GetFolder('\\').GetTask('{TASK_NAME}'); "
            "$d = $t.Definition; "
            "$d.Settings.DisallowStartIfOnBatteries = $false; "
            "$d.Settings.StopIfGoingOnBatteries = $false; "
            "$d.Settings.ExecutionTimeLimit = 'PT2M'; "  # Max 2 min runtime per check
            "$d.Settings.StartWhenAvailable = $true; "  # Run ASAP if a check was missed
            f"$ts.GetFolder('\\').RegisterTaskDefinition('{TASK_NAME}', $d, 6, $null, $null, 3) | Out-Null"
        )
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass

    print(f"Watchdog scheduled task '{TASK_NAME}' installed successfully!")
    print(f"  Runs every {CHECK_INTERVAL_MINUTES} minutes")
    print(f"  Script: {script_path}")
    print(f"  Uninstall: python {Path(__file__).name} --uninstall")


def uninstall_scheduled_task() -> None:
    """Remove the watchdog scheduled task."""
    if sys.platform != "win32":
        print("Remove the cron job manually.")
        return

    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"Watchdog task '{TASK_NAME}' removed.")
    else:
        print(f"Could not remove task (may not exist): {result.stderr.strip()}")


def show_log(limit: int = 20) -> None:
    """Print recent watchdog log entries."""
    if not DB_PATH.exists():
        print("No database found.")
        return

    conn = _get_conn()
    _ensure_watchdog_table(conn)

    rows = conn.execute(
        "SELECT * FROM watchdog_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    if not rows:
        print("No watchdog events logged yet.")
        return

    print(f"{'Time':<28} {'Event':<18} {'PID':>6} {'HB Age':>8} {'Action'}")
    print("-" * 90)
    for r in rows:
        ts = r["timestamp"][:19].replace("T", " ")
        hb = f"{r['heartbeat_age_seconds']:.0f}s" if r["heartbeat_age_seconds"] else "-"
        pid = str(r["daemon_pid"]) if r["daemon_pid"] else "-"
        action = r["action_taken"][:40] if r["action_taken"] else ""
        tg = " [TG]" if r["telegram_sent"] else ""
        print(f"{ts:<28} {r['event_type']:<18} {pid:>6} {hb:>8} {action}{tg}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JayBrain Daemon Watchdog")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--install", action="store_true",
        help="Install as a Windows Task Scheduler job",
    )
    group.add_argument(
        "--uninstall", action="store_true",
        help="Remove the scheduled task",
    )
    group.add_argument(
        "--log", action="store_true",
        help="Show recent watchdog log entries",
    )
    parser.add_argument(
        "--log-limit", type=int, default=20,
        help="Number of log entries to show (default: 20)",
    )
    args = parser.parse_args()

    if args.install:
        install_scheduled_task()
    elif args.uninstall:
        uninstall_scheduled_task()
    elif args.log:
        show_log(args.log_limit)
    else:
        check_and_restart()


if __name__ == "__main__":
    main()
