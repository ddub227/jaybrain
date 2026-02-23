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


def run_foreground() -> None:
    """Run the daemon in the foreground."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    from jaybrain.daemon import build_daemon
    dm = build_daemon()
    dm.start()


def run_daemon() -> None:
    """Spawn the daemon as a detached background process."""
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    pid_file = data_dir / "daemon.pid"
    log_file = data_dir / "daemon.log"

    # Check if already running
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)
            print(f"Daemon already running (pid={old_pid}). Stop it first.")
            sys.exit(1)
        except (OSError, ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)

    # Launch detached process
    log_fh = open(log_file, "a")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve())],
        stdout=log_fh,
        stderr=log_fh,
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

    try:
        os.kill(pid, 0)  # Check if alive
    except (OSError, ProcessLookupError):
        print(f"Daemon process {pid} is not running. Cleaning up PID file.")
        pid_file.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (pid={pid}).")
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
