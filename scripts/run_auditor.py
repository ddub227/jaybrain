#!/usr/bin/env python3
"""Launch the adversarial security auditor -- batched multi-pass architecture.

Usage:
    python scripts/run_auditor.py [--output FILE] [--batch-lines N]

Architecture:
    The auditor can't hold 21,000+ lines of code in a single context window
    (~200K tokens). Instead, this script splits the work into batches:

    1. PLAN: Script measures all file sizes and groups them into batches
       that fit comfortably in one context window (~4,000 lines each).
    2. AUDIT: One fresh Claude session per batch. Each reads its assigned
       files, audits them, and outputs structured findings as JSON.
    3. CROSS-CUT: One session reads ALL findings and looks for issues that
       span multiple files (data flow, inconsistent patterns, etc.).
    4. SYNTHESIZE: One final session reads all findings and writes the
       complete structured report with scorecard.

    Each session gets a fresh context window. No hallucinated coverage --
    the script tracks which files were read, not the LLM.

Isolation:
    Runs from C:/jaybrain-auditor/ (outside any git repo) so Claude Code
    only sees the auditor's CLAUDE.md, not the JayBrain root CLAUDE.md.
    MCP servers are blocked via --strict-mcp-config with empty config.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODEBASE_DIR = PROJECT_ROOT / "src" / "jaybrain"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

AUDITOR_TEMPLATE = PROJECT_ROOT / "auditor" / "CLAUDE.md"
AUDITOR_RUNTIME_DIR = Path("C:/jaybrain-auditor")
NPM_GLOBAL_BIN = Path.home() / "AppData" / "Roaming" / "npm"

# Lines per batch -- conservative to leave room for analysis
DEFAULT_BATCH_LINES = 4000


def _find_claude() -> str:
    """Find the claude CLI, checking PATH first then the npm global bin."""
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.cmd", "claude"):
        candidate = NPM_GLOBAL_BIN / name
        if candidate.exists():
            return str(candidate)
    return "claude"


def _deploy_claude_md() -> Path:
    """Copy auditor CLAUDE.md outside the repo, rewriting relative paths."""
    AUDITOR_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    template = AUDITOR_TEMPLATE.read_text(encoding="utf-8")
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


def _measure_files() -> list[dict]:
    """Measure all .py files in the codebase, sorted largest first."""
    files = []
    for f in CODEBASE_DIR.glob("*.py"):
        content = f.read_text(encoding="utf-8")
        files.append({
            "name": f.name,
            "path": f.as_posix(),
            "lines": len(content.splitlines()),
            "bytes": len(content.encode("utf-8")),
        })
    files.sort(key=lambda x: x["lines"], reverse=True)
    return files


def _plan_batches(files: list[dict], max_lines: int) -> list[list[dict]]:
    """Group files into batches using first-fit decreasing bin packing."""
    batches: list[list[dict]] = []
    batch_sizes: list[int] = []

    for f in files:
        # If a single file exceeds max_lines, it gets its own batch
        placed = False
        for i, size in enumerate(batch_sizes):
            if size + f["lines"] <= max_lines:
                batches[i].append(f)
                batch_sizes[i] += f["lines"]
                placed = True
                break
        if not placed:
            batches.append([f])
            batch_sizes.append(f["lines"])

    return batches


def _run_claude(prompt: str, claude_bin: str, env: dict,
                empty_mcp: str, max_turns: int = 30) -> str:
    """Run a single headless Claude session and return stdout."""
    result = subprocess.run(
        [
            claude_bin,
            "--print",
            "-p", prompt,
            "--dangerously-skip-permissions",
            "--max-turns", str(max_turns),
            "--disallowedTools", "Edit,Write,NotebookEdit",
            "--mcp-config", empty_mcp,
            "--strict-mcp-config",
        ],
        cwd=str(AUDITOR_RUNTIME_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0 and result.stderr:
        print(f"  Warning: exit code {result.returncode}")
        print(f"  Stderr: {result.stderr[:300]}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the adversarial security auditor (batched)"
    )
    parser.add_argument(
        "--output", "-o", type=Path,
        default=(PROJECT_ROOT / "data"
                 / f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"),
    )
    parser.add_argument(
        "--batch-lines", type=int, default=DEFAULT_BATCH_LINES,
        help=f"Max lines per batch (default: {DEFAULT_BATCH_LINES})",
    )
    args = parser.parse_args()

    # --- Pre-flight checks ---
    if not AUDITOR_TEMPLATE.exists():
        print(f"Error: auditor template not found at {AUDITOR_TEMPLATE}")
        sys.exit(1)
    if not CODEBASE_DIR.exists():
        print(f"Error: codebase not found at {CODEBASE_DIR}")
        sys.exit(1)

    deployed_md = _deploy_claude_md()
    if not _verify_isolation():
        print(f"FATAL: {AUDITOR_RUNTIME_DIR} is inside a git repo!")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    claude_bin = _find_claude()
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    empty_mcp = json.dumps({"mcpServers": {}})

    # --- Phase 1: Plan batches ---
    print("=" * 60)
    print("ADVERSARIAL SECURITY AUDITOR -- BATCHED MULTI-PASS")
    print("=" * 60)
    print()
    print(f"  Runtime:   {AUDITOR_RUNTIME_DIR}")
    print(f"  Codebase:  {CODEBASE_DIR}")
    print(f"  Output:    {args.output}")
    print(f"  Isolation: VERIFIED")
    print()

    files = _measure_files()
    total_lines = sum(f["lines"] for f in files)
    print(f"Phase 1: PLANNING")
    print(f"  Files: {len(files)}")
    print(f"  Total lines: {total_lines:,}")
    print(f"  Batch limit: {args.batch_lines:,} lines per batch")

    batches = _plan_batches(files, args.batch_lines)
    print(f"  Batches: {len(batches)}")
    print()

    for i, batch in enumerate(batches):
        batch_lines = sum(f["lines"] for f in batch)
        file_names = ", ".join(f["name"] for f in batch)
        print(f"  Batch {i+1}: {batch_lines:,} lines -- {file_names}")
    print()

    # Also include pyproject.toml in the first batch prompt
    pyproject_abs = PYPROJECT.as_posix()

    # Work directory for this audit run
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = AUDITOR_RUNTIME_DIR / f"run_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    findings_file = work_dir / "findings.jsonl"

    # --- Phase 2: Audit batches ---
    print(f"Phase 2: AUDITING ({len(batches)} batches)")
    start_time = time.time()
    manifest = []

    for i, batch in enumerate(batches):
        batch_num = i + 1
        file_paths = [f["path"] for f in batch]
        file_names = [f["name"] for f in batch]
        batch_lines = sum(f["lines"] for f in batch)

        print(f"\n  Batch {batch_num}/{len(batches)}: "
              f"{', '.join(file_names)} ({batch_lines:,} lines)")

        # Build the per-batch prompt
        files_list = "\n".join(f"  - {p}" for p in file_paths)
        extra = ""
        if batch_num == 1:
            extra = f"\nAlso read {pyproject_abs} for dependency information.\n"

        prompt = f"""You are a security auditor. Read ONLY these files and audit them:
{files_list}
{extra}
For each file, look for:
- SECURITY: SQL injection, command injection, path traversal, credential exposure, SSRF, race conditions, insecure deserialization
- ARCHITECTURE: resource leaks, missing error boundaries, concurrency hazards
- COMPLEXITY: dead code, duplicated logic, over-abstraction
- TECHNICAL DEBT: missing types, bare except, magic numbers, TODO/FIXME

Output your findings as a JSON array. Each finding must have:
{{"category": "SECURITY|ARCHITECTURE|COMPLEXITY|TECHNICAL_DEBT", "severity": "critical|high|medium|low", "title": "short title", "file": "filename.py", "line": 123, "code": "the relevant code snippet (keep short)", "issue": "what is wrong and why it matters", "recommendation": "how to fix it in plain English"}}

IMPORTANT:
- Only report findings for files you ACTUALLY read. Do not guess or infer.
- Include the exact line number and code snippet for every finding.
- If a file has no issues, still confirm you read it by outputting: {{"file": "filename.py", "status": "clean", "lines_read": N}}
- Output ONLY the JSON array, no other text."""

        output = _run_claude(prompt, claude_bin, env, empty_mcp, max_turns=30)

        # Extract JSON from the output (may have markdown fences)
        json_text = output.strip()
        if "```json" in json_text:
            json_text = json_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        # Try to parse and save findings
        try:
            findings = json.loads(json_text)
            if not isinstance(findings, list):
                findings = [findings]
        except json.JSONDecodeError:
            print(f"    WARNING: Could not parse JSON output, saving raw text")
            findings = [{"batch": batch_num, "raw_output": output[:5000],
                         "parse_error": True}]

        # Append to findings file
        with open(findings_file, "a", encoding="utf-8") as fout:
            for finding in findings:
                finding["_batch"] = batch_num
                fout.write(json.dumps(finding) + "\n")

        # Track manifest
        for f in batch:
            covered = any(
                (fd.get("file") == f["name"] or fd.get("file", "").endswith(f["name"]))
                for fd in findings if isinstance(fd, dict)
            )
            manifest.append({"file": f["name"], "batch": batch_num, "covered": covered})

        finding_count = len([f for f in findings if isinstance(f, dict)
                            and f.get("category")])
        clean_count = len([f for f in findings if isinstance(f, dict)
                          and f.get("status") == "clean"])
        print(f"    Findings: {finding_count}, Clean files: {clean_count}")

    elapsed_audit = time.time() - start_time
    print(f"\n  Audit phase complete in {elapsed_audit/60:.1f} minutes")

    # --- Phase 3: Cross-cutting analysis ---
    print(f"\nPhase 3: CROSS-CUTTING ANALYSIS")

    all_findings = findings_file.read_text(encoding="utf-8")
    finding_count = len(all_findings.strip().splitlines())

    cross_prompt = f"""You are a security auditor performing cross-file analysis.
Below are findings from individual file audits of a Python codebase.
Your job is to find issues that SPAN MULTIPLE FILES -- things like:
- Data flows where user input enters in one file and reaches a sink in another
- Inconsistent validation (one module validates, another doesn't)
- Privilege escalation chains across module boundaries
- Shared state that multiple modules access without coordination

Here are the per-file findings ({finding_count} entries):

{all_findings}

Output ONLY new cross-cutting findings as a JSON array using the same format:
{{"category": "...", "severity": "...", "title": "...", "file": "multiple: X.py, Y.py", "line": 0, "code": "relevant snippets from both files", "issue": "...", "recommendation": "..."}}

If there are no cross-cutting issues, output an empty array: []"""

    cross_output = _run_claude(cross_prompt, claude_bin, env, empty_mcp, max_turns=15)

    # Parse cross-cutting findings
    cross_text = cross_output.strip()
    if "```json" in cross_text:
        cross_text = cross_text.split("```json")[-1].split("```")[0].strip()
    elif "```" in cross_text:
        cross_text = cross_text.split("```")[1].split("```")[0].strip()

    try:
        cross_findings = json.loads(cross_text)
        if not isinstance(cross_findings, list):
            cross_findings = [cross_findings]
    except json.JSONDecodeError:
        print(f"  WARNING: Could not parse cross-cutting JSON")
        cross_findings = []

    # Append cross-cutting findings
    with open(findings_file, "a", encoding="utf-8") as fout:
        for finding in cross_findings:
            finding["_batch"] = "cross-cutting"
            fout.write(json.dumps(finding) + "\n")

    print(f"  Cross-cutting findings: {len(cross_findings)}")

    # --- Phase 4: Synthesis ---
    print(f"\nPhase 4: SYNTHESIS")

    all_findings_final = findings_file.read_text(encoding="utf-8")
    total_findings = len(all_findings_final.strip().splitlines())

    # Check manifest for gaps
    covered_files = [m["file"] for m in manifest if m["covered"]]
    missing_files = [m["file"] for m in manifest if not m["covered"]]
    if missing_files:
        print(f"  WARNING: {len(missing_files)} files may not have been covered:")
        for f in missing_files:
            print(f"    - {f}")

    synthesis_prompt = f"""You are a security auditor writing the final report.
Below are ALL findings from a multi-pass audit of a Python codebase
({len(files)} files, {total_lines:,} lines of code). The findings come from
{len(batches)} separate batch audits plus a cross-cutting analysis pass.

MANIFEST -- files that were audited:
{json.dumps([m["file"] for m in manifest], indent=2)}

Files that may have gaps in coverage:
{json.dumps(missing_files) if missing_files else "None -- full coverage achieved."}

ALL FINDINGS ({total_findings} entries):

{all_findings_final}

Write the complete structured audit report. Group findings by category.
For each finding use this format:

### [CATEGORY-NUMBER] Title
**Severity:** Critical / High / Medium / Low
**File:** filename.py:line_number
**Code:**
```python
# the relevant code snippet
```
**Issue:** What is wrong and why it matters.
**Recommendation:** How to fix it in plain English.

End with a summary scorecard table:
| Category | Findings | Critical | High | Medium | Low |

And a prioritized action list of the top issues to fix first.

IMPORTANT: Only include findings from the data above. Do not invent findings.
If files had gaps in coverage, note this explicitly in the report."""

    print(f"  Synthesizing {total_findings} findings into final report...")
    report = _run_claude(synthesis_prompt, claude_bin, env, empty_mcp, max_turns=10)

    if report.strip():
        args.output.write_text(report, encoding="utf-8")
        print(f"\n  Report saved to: {args.output}")
        print(f"  Report length: {len(report):,} characters")
    else:
        print("  ERROR: Synthesis produced no output.")
        # Fall back to raw findings
        fallback = args.output.with_suffix(".findings.jsonl")
        shutil.copy2(findings_file, fallback)
        print(f"  Raw findings saved to: {fallback}")

    # --- Summary ---
    total_time = time.time() - start_time
    print()
    print("=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)
    print(f"  Files: {len(files)}")
    print(f"  Lines: {total_lines:,}")
    print(f"  Batches: {len(batches)}")
    print(f"  Findings: {total_findings}")
    print(f"  Coverage: {len(covered_files)}/{len(files)} files")
    if missing_files:
        print(f"  Gaps: {', '.join(missing_files)}")
    print(f"  Time: {total_time/60:.1f} minutes")
    print(f"  Report: {args.output}")

    # Save manifest for dashboard
    manifest_file = work_dir / "manifest.json"
    manifest_file.write_text(json.dumps({
        "run_id": run_id,
        "files": len(files),
        "lines": total_lines,
        "batches": len(batches),
        "findings": total_findings,
        "covered": len(covered_files),
        "missing": missing_files,
        "duration_sec": round(total_time),
        "manifest": manifest,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
