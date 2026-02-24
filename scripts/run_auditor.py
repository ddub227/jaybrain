#!/usr/bin/env python3
"""Launch the adversarial security auditor session.

Usage:
    python scripts/run_auditor.py [--output FILE]

Runs a Claude Code session from the auditor/ directory, which has its own
CLAUDE.md with adversarial instructions and ZERO JayBrain context. The
session is strictly read-only -- it can only use Read, Glob, Grep, and
Bash tools. Edit/Write are explicitly blocked.

The auditor's report is captured from stdout and saved to a file.
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDITOR_DIR = PROJECT_ROOT / "auditor"
AUDITOR_MD = AUDITOR_DIR / "CLAUDE.md"
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
        print(f"Expected at: {AUDITOR_DIR}")
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    prompt = (
        "Read every .py file in ../src/jaybrain/ and ../pyproject.toml. "
        "Produce the full structured audit report as described in your CLAUDE.md. "
        "Start by listing all .py files, then read and audit each one systematically. "
        "Output the complete report as your response text."
    )

    print("Launching adversarial security auditor...")
    print(f"  Instructions: {AUDITOR_MD}")
    print(f"  Codebase:     {PROJECT_ROOT / 'src' / 'jaybrain'}")
    print(f"  Output:        {args.output}")
    print(f"  Mode:          READ-ONLY (Edit/Write blocked)")
    print()

    try:
        # Run from auditor/ so it picks up auditor/CLAUDE.md, NOT the root CLAUDE.md.
        # --print: non-interactive, report goes to stdout.
        # --disallowedTools: block all write tools as a hard safety layer.
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--max-turns", "50",
                "--disallowedTools", "Edit,Write,NotebookEdit",
                prompt,
            ],
            cwd=str(AUDITOR_DIR),
            capture_output=True,
            text=True,
        )

        report = result.stdout

        if report.strip():
            args.output.write_text(report, encoding="utf-8")
            print(f"Audit complete. Report saved to: {args.output}")
            print(f"Report length: {len(report):,} characters")
        else:
            print("Warning: auditor produced no output.")
            if result.stderr:
                print(f"Stderr: {result.stderr[:500]}")
            sys.exit(1)

        if result.returncode != 0:
            print(f"Auditor exited with code {result.returncode}")
            if result.stderr:
                print(f"Stderr: {result.stderr[:500]}")

    except FileNotFoundError:
        print("Error: 'claude' CLI not found. Is Claude Code installed?")
        sys.exit(1)


if __name__ == "__main__":
    main()
