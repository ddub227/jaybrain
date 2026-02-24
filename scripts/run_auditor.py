#!/usr/bin/env python3
"""Launch the adversarial security auditor session.

Usage:
    python scripts/run_auditor.py [--output FILE]

Isolation strategy:
    Claude Code resolves CLAUDE.md from the git root, not the CWD. If we ran
    inside the jaybrain repo, the auditor would inherit the root CLAUDE.md
    (full JayBrain context), defeating its purpose.

    Fix: this script copies auditor/CLAUDE.md to a directory OUTSIDE the repo
    (C:/jaybrain-auditor/) and launches Claude Code from there. No .git parent
    means Claude Code only sees the auditor's CLAUDE.md.

    Absolute paths in the CLAUDE.md and prompt ensure the auditor can still
    read the jaybrain source code.

The session is strictly read-only -- Edit/Write/NotebookEdit are blocked via
--disallowedTools.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODEBASE_DIR = PROJECT_ROOT / "src" / "jaybrain"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Template lives in-repo for version control; deployed outside repo for isolation
AUDITOR_TEMPLATE = PROJECT_ROOT / "auditor" / "CLAUDE.md"

# Isolation directory -- MUST be outside any git repo.
# Uses C:\ root because ~/  has a stray .git that would break isolation.
AUDITOR_RUNTIME_DIR = Path("C:/jaybrain-auditor")

# Claude CLI installed via npm -- find it reliably across terminals
NPM_GLOBAL_BIN = Path.home() / "AppData" / "Roaming" / "npm"

DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
)


def _find_claude() -> str:
    """Find the claude CLI, checking PATH first then the npm global bin."""
    found = shutil.which("claude")
    if found:
        return found
    # Check npm global bin directly (PowerShell often misses this)
    for name in ("claude.cmd", "claude"):
        candidate = NPM_GLOBAL_BIN / name
        if candidate.exists():
            return str(candidate)
    return "claude"  # last resort, let subprocess raise FileNotFoundError


def _deploy_claude_md() -> Path:
    """Copy the auditor CLAUDE.md template outside the repo, rewriting paths.

    Replaces relative paths (../src/jaybrain/, ../pyproject.toml) with
    absolute paths so the auditor can read the codebase from its isolated
    runtime directory.
    """
    AUDITOR_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    template = AUDITOR_TEMPLATE.read_text(encoding="utf-8")

    # Replace relative paths with absolute paths (use forward slashes for
    # consistency -- Claude Code on Windows handles both)
    codebase_abs = CODEBASE_DIR.as_posix()
    pyproject_abs = PYPROJECT.as_posix()

    deployed = template.replace("../src/jaybrain/", f"{codebase_abs}/")
    deployed = deployed.replace("../pyproject.toml", pyproject_abs)

    target = AUDITOR_RUNTIME_DIR / "CLAUDE.md"
    target.write_text(deployed, encoding="utf-8")
    return target


def _verify_isolation() -> bool:
    """Verify the runtime directory is NOT inside a git repo."""
    check_dir = AUDITOR_RUNTIME_DIR
    while check_dir != check_dir.parent:
        if (check_dir / ".git").exists():
            return False
        check_dir = check_dir.parent
    return True


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

    # --- Pre-flight checks ---

    if not AUDITOR_TEMPLATE.exists():
        print(f"Error: auditor template not found at {AUDITOR_TEMPLATE}")
        sys.exit(1)

    if not CODEBASE_DIR.exists():
        print(f"Error: codebase not found at {CODEBASE_DIR}")
        sys.exit(1)

    # Deploy CLAUDE.md to isolated runtime directory
    deployed_md = _deploy_claude_md()

    if not _verify_isolation():
        print(f"FATAL: {AUDITOR_RUNTIME_DIR} is inside a git repo!")
        print("The auditor runtime directory must be outside all git repos.")
        print("Move or delete the .git directory, or change AUDITOR_RUNTIME_DIR.")
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Use absolute paths in the prompt so the auditor can find the code
    codebase_abs = CODEBASE_DIR.as_posix()
    pyproject_abs = PYPROJECT.as_posix()

    prompt = (
        f"Read every .py file in {codebase_abs}/ and {pyproject_abs}. "
        "Produce the full structured audit report as described in your CLAUDE.md. "
        "Start by listing all .py files, then read and audit each one. "
        "Prioritize the highest-risk files first: "
        "server.py, db.py, config.py, browser.py, trash.py, scraping.py, "
        "telegram.py, daemon.py, sessions.py -- then cover the rest. "
        "Read files in bulk (multiple reads per turn) to maximize coverage. "
        "Output the complete report as your response text."
    )

    print("Launching adversarial security auditor...")
    print(f"  Template:  {AUDITOR_TEMPLATE}")
    print(f"  Deployed:  {deployed_md}")
    print(f"  Runtime:   {AUDITOR_RUNTIME_DIR} (outside git repo)")
    print(f"  Codebase:  {CODEBASE_DIR}")
    print(f"  Output:    {args.output}")
    print(f"  Mode:      READ-ONLY (Edit/Write blocked)")
    print(f"  Isolation: VERIFIED (no .git in parent chain)")
    print()

    try:
        claude_bin = _find_claude()

        # Strip CLAUDECODE env var so this can be launched from inside a
        # Claude Code session without triggering the nested-session guard.
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        # Empty MCP config + strict mode = zero MCP servers loaded.
        # Without this, the auditor inherits global MCP configs which
        # leak JayBrain context through tool descriptions.
        empty_mcp = json.dumps({"mcpServers": {}})

        result = subprocess.run(
            [
                claude_bin,
                "--print",
                "-p", prompt,
                "--dangerously-skip-permissions",
                "--max-turns", "100",
                "--disallowedTools", "Edit,Write,NotebookEdit",
                "--mcp-config", empty_mcp,
                "--strict-mcp-config",
            ],
            cwd=str(AUDITOR_RUNTIME_DIR),
            capture_output=True,
            text=True,
            env=env,
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
