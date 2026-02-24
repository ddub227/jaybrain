#!/usr/bin/env python3
"""Launch the adversarial security auditor session.

Usage:
    python scripts/run_auditor.py [--output FILE]

Spawns a Claude Code session with AUDITOR_CLAUDE.md as its project
instructions. The auditor reads the entire codebase and produces a
structured security/architecture report.

The auditor session is read-only -- it never modifies files.
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDITOR_MD = PROJECT_ROOT / "AUDITOR_CLAUDE.md"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the adversarial security auditor"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output file for the audit report (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    if not AUDITOR_MD.exists():
        print(f"Error: {AUDITOR_MD} not found.")
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    prompt = (
        "You are the adversarial security auditor. Follow AUDITOR_CLAUDE.md exactly. "
        "Read every Python file in src/jaybrain/ and produce the full structured report. "
        "Start by listing all .py files in src/jaybrain/, then read and audit each one. "
        f"Write the final report to {args.output}."
    )

    print(f"Launching auditor session...")
    print(f"  Instructions: {AUDITOR_MD}")
    print(f"  Output: {args.output}")
    print()

    try:
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--max-turns", "50",
                prompt,
            ],
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            print(f"\nAudit complete. Report: {args.output}")
        else:
            print(f"\nAudit session exited with code {result.returncode}")
            sys.exit(result.returncode)
    except FileNotFoundError:
        print("Error: 'claude' CLI not found. Is Claude Code installed?")
        sys.exit(1)


if __name__ == "__main__":
    main()
