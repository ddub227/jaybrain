#!/usr/bin/env python3
"""Start the GramCracker Telegram bot.

Usage:
    Foreground:  python scripts/start_gramcracker.py
    Background:  python scripts/start_gramcracker.py --daemon

Foreground mode runs in the current terminal (Ctrl+C to stop).
Daemon mode detaches the process and writes a PID file + log to data/.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def run_foreground() -> None:
    """Run the bot in the foreground."""
    from jaybrain.telegram import main
    main()


def run_daemon() -> None:
    """Spawn the bot as a detached background process."""
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    pid_file = data_dir / "gramcracker.pid"
    log_file = data_dir / "gramcracker.log"

    # Check if already running
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)
            print(f"GramCracker already running (pid={old_pid}). Stop it first.")
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
    print(f"GramCracker started in background (pid={proc.pid})")
    print(f"  Log: {log_file}")
    print(f"  PID: {pid_file}")
    print(f"  Stop: kill {proc.pid}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start GramCracker Telegram bot")
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Run as a background daemon",
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_foreground()


if __name__ == "__main__":
    main()
