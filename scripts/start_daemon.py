#!/usr/bin/env python3
"""Start the JayBrain daemon.

Usage:
    Foreground:  python scripts/start_daemon.py
    Background:  python scripts/start_daemon.py --daemon
    Stop:        python scripts/start_daemon.py --stop

Foreground mode runs in the current terminal (Ctrl+C to stop).
Daemon mode detaches the process and writes a PID file + log to data/.
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is running. Works on Windows Store Python."""
    if sys.platform == "win32":
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


def _load_env() -> None:
    """Load .env file from project root if it exists."""
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


def _acquire_lock(lock_path: Path):
    """Acquire an exclusive file lock to prevent dual-daemon startup.

    Returns the open file handle (must stay open for lock to persist)
    or None if another daemon holds the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(lock_path, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except (OSError, IOError):
        return None


def _check_db_for_alive_daemon(data_dir: Path) -> int | None:
    """Check if daemon_state in the DB has an alive PID.

    Returns the alive PID if found, None otherwise.
    """
    import sqlite3

    db_path = data_dir / "jaybrain.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        row = conn.execute(
            "SELECT pid FROM daemon_state WHERE id = 1 AND status = 'running'"
        ).fetchone()
        conn.close()
        if row and row[0]:
            pid = int(row[0])
            if _is_pid_alive(pid):
                return pid
    except Exception:
        pass
    return None


def _log_startup_refused(data_dir: Path, rival_pid: int) -> None:
    """Best-effort log of startup_refused to daemon_lifecycle_log."""
    import sqlite3
    from datetime import datetime, timezone

    db_path = data_dir / "jaybrain.db"
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute(
            """INSERT INTO daemon_lifecycle_log
            (event_type, pid, timestamp, trigger, error_message)
            VALUES (?, ?, ?, ?, ?)""",
            (
                "startup_refused",
                os.getpid(),
                datetime.now(timezone.utc).isoformat(),
                "manual",
                f"Rival PID {rival_pid} is alive in daemon_state",
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def run_foreground() -> None:
    """Run the daemon in the foreground."""
    _load_env()
    data_dir = PROJECT_ROOT / "data"
    log_file = data_dir / "daemon.log"
    lock_file = data_dir / "daemon.lock"

    # Clean stale lock file if the PID inside it is dead
    if lock_file.exists():
        try:
            stale_pid_text = lock_file.read_text().strip()
            if stale_pid_text and stale_pid_text.isdigit():
                stale_pid = int(stale_pid_text)
                if not _is_pid_alive(stale_pid):
                    lock_file.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    # Prevent dual-daemon startup via exclusive file lock
    lock_handle = _acquire_lock(lock_file)
    if lock_handle is None:
        print("Another daemon instance holds the lock. Exiting.")
        sys.exit(1)

    # After acquiring lock, verify no alive daemon registered in DB
    alive_pid = _check_db_for_alive_daemon(data_dir)
    if alive_pid is not None:
        print(f"Another daemon is running (pid={alive_pid} in daemon_state). Exiting.")
        _log_startup_refused(data_dir, alive_pid)
        lock_handle.close()
        sys.exit(1)

    # On Windows background mode, stdout/stderr may be invalid handles.
    # Always log to file; also log to stderr if available.
    handlers = [logging.FileHandler(str(log_file))]
    try:
        sys.stderr.write("")  # Test if stderr is usable
        handlers.append(logging.StreamHandler(sys.stderr))
    except (OSError, ValueError, AttributeError):
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=handlers,
    )
    try:
        from jaybrain.daemon import build_daemon
        dm = build_daemon()
        dm.start()
    except Exception:
        logging.exception("Daemon crashed with unhandled exception")
    finally:
        lock_handle.close()


def run_daemon() -> None:
    """Spawn the daemon as a background process.

    On Linux/macOS: uses start_new_session to detach from the terminal.
    On Windows: uses Task Scheduler for reliable background operation.
    Fallback: Popen with DETACHED_PROCESS (may not survive console close).
    """
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    pid_file = data_dir / "daemon.pid"
    log_file = data_dir / "daemon.log"

    # Check if already running
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            if _is_pid_alive(old_pid):
                print(f"Daemon already running (pid={old_pid}). Stop it first.")
                sys.exit(1)
            else:
                pid_file.unlink(missing_ok=True)
        except (ValueError, FileNotFoundError):
            pid_file.unlink(missing_ok=True)

    if sys.platform == "win32":
        _run_daemon_windows(pid_file, log_file)
    else:
        _run_daemon_posix(pid_file, log_file)


def _ensure_autostart_on_logon() -> None:
    """Register JayBrain daemon to auto-start on user logon.

    Uses HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run which
    does not require admin privileges. The entry runs start_daemon.py
    in foreground mode (Task Scheduler handles the current session,
    this handles future logons).
    """
    if sys.platform != "win32":
        return
    try:
        script_path = str(Path(__file__).resolve())
        cmd = f'"{sys.executable}" "{script_path}"'
        result = subprocess.run(
            [
                "reg", "add",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v", "JayBrainDaemon",
                "/t", "REG_SZ",
                "/d", cmd,
                "/f",
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print("  Auto-start on logon: registered")
        else:
            print(f"  Warning: could not register auto-start: {result.stderr.strip()}")
    except Exception as e:
        print(f"  Warning: could not register auto-start: {e}")


def _fix_task_power_settings(task_name: str) -> None:
    """Harden the scheduled task: no battery kill, no time limit, auto-restart.

    By default, Task Scheduler sets StopIfGoingOnBatteries=True which
    silently kills the daemon when the laptop unplugs. Also adds restart-
    on-failure (up to 3 retries at 1-minute intervals) so the daemon
    recovers from crashes automatically. Fix via COM API.
    """
    try:
        import ctypes.wintypes  # noqa: F401 -- ensures COM is importable

        script = (
            "$ts = New-Object -ComObject Schedule.Service; "
            "$ts.Connect(); "
            f"$t = $ts.GetFolder('\\').GetTask('{task_name}'); "
            "$d = $t.Definition; "
            # Prevent battery/power kills
            "$d.Settings.DisallowStartIfOnBatteries = $false; "
            "$d.Settings.StopIfGoingOnBatteries = $false; "
            "$d.Settings.ExecutionTimeLimit = 'PT0S'; "
            # Auto-restart on failure (up to 3 times, 1 min apart)
            "$d.Settings.RestartCount = 3; "
            "$d.Settings.RestartInterval = 'PT1M'; "
            f"$ts.GetFolder('\\').RegisterTaskDefinition('{task_name}', $d, 6, $null, $null, 3) | Out-Null"
        )
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            print("  Power settings: battery stop disabled, no time limit, restart-on-failure enabled")
        else:
            print(f"  Warning: could not fix power settings: {result.stderr.strip()}")
    except Exception as e:
        print(f"  Warning: could not fix power settings: {e}")


def _run_daemon_windows(pid_file: Path, log_file: Path) -> None:
    """Launch daemon via Windows Task Scheduler for reliable background operation."""
    script_path = str(Path(__file__).resolve())
    task_name = "JayBrainDaemon"

    # Create a scheduled task that runs once (immediately) and stays running
    try:
        # Delete existing task if any
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True,
        )
        # Create task to run the daemon in foreground mode (task scheduler handles backgrounding)
        result = subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", task_name,
                "/TR", f'"{sys.executable}" "{script_path}"',
                "/SC", "ONCE",
                "/ST", "00:00",
                "/F",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Failed to create scheduled task: {result.stderr}")
            print("Falling back to Popen (may not survive console close)...")
            _run_daemon_popen(pid_file, log_file)
            return

        # Fix default power settings that kill daemon on battery
        _fix_task_power_settings(task_name)

        # Ensure daemon auto-starts on future logons (no admin needed)
        _ensure_autostart_on_logon()

        # Run it now
        result = subprocess.run(
            ["schtasks", "/Run", "/TN", task_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Failed to run scheduled task: {result.stderr}")
            _run_daemon_popen(pid_file, log_file)
            return

        # Wait for PID file to appear
        import time
        for _ in range(10):
            time.sleep(1)
            if pid_file.exists():
                pid = pid_file.read_text().strip()
                print(f"JayBrain daemon started via Task Scheduler (pid={pid})")
                print(f"  Log: {log_file}")
                print(f"  PID: {pid_file}")
                print(f"  Stop: python {Path(__file__).name} --stop")
                return

        print("Daemon started but PID file not found yet. Check the log.")
        print(f"  Log: {log_file}")

    except FileNotFoundError:
        print("schtasks not available. Falling back to Popen...")
        _run_daemon_popen(pid_file, log_file)


def _run_daemon_popen(pid_file: Path, log_file: Path) -> None:
    """Fallback: launch via Popen (unreliable on Windows)."""
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve())],
        **popen_kwargs,
    )
    pid_file.write_text(str(proc.pid))
    print(f"JayBrain daemon started in background (pid={proc.pid})")
    print(f"  Log: {log_file}")
    print(f"  PID: {pid_file}")
    print(f"  Stop: python {Path(__file__).name} --stop")


def _run_daemon_posix(pid_file: Path, log_file: Path) -> None:
    """Launch via Popen with start_new_session (reliable on Linux/macOS)."""
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve())],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    print(f"JayBrain daemon started in background (pid={proc.pid})")
    print(f"  Log: {log_file}")
    print(f"  PID: {pid_file}")
    print(f"  Stop: python {Path(__file__).name} --stop")


def stop_daemon() -> None:
    """Stop the daemon by reading PID file and sending SIGTERM."""
    import signal

    data_dir = PROJECT_ROOT / "data"
    pid_file = data_dir / "daemon.pid"

    if not pid_file.exists():
        print("Daemon is not running (no PID file).")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, FileNotFoundError):
        print("Invalid PID file.")
        pid_file.unlink(missing_ok=True)
        return

    if not _is_pid_alive(pid):
        print(f"Daemon process {pid} is not running. Cleaning up PID file.")
        pid_file.unlink(missing_ok=True)
        return

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            # Also clean up the scheduled task if it exists
            subprocess.run(
                ["schtasks", "/Delete", "/TN", "JayBrainDaemon", "/F"],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"Stopped daemon (pid={pid}).")
        pid_file.unlink(missing_ok=True)
    except (OSError, ProcessLookupError) as e:
        print(f"Failed to stop daemon: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start/stop the JayBrain daemon")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Run as a background daemon",
    )
    group.add_argument(
        "--stop", "-s",
        action="store_true",
        help="Stop the running daemon",
    )
    args = parser.parse_args()

    if args.stop:
        stop_daemon()
    elif args.daemon:
        run_daemon()
    else:
        run_foreground()


if __name__ == "__main__":
    main()
