"""Homelab domain - file-based lab journal, tools inventory, and infrastructure.

All data lives in the homelab project directory (~/projects/homelab/).
MCP tools are thin wrappers around file I/O. No SQLite storage -- the
files ARE the source of truth, compatible with Obsidian.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


def get_status() -> dict:
    """Parse JOURNAL_INDEX.md for quick stats, skills, readiness, recent entries."""
    if not config.HOMELAB_JOURNAL_INDEX.exists():
        return {"error": f"Journal index not found: {config.HOMELAB_JOURNAL_INDEX}"}

    content = config.HOMELAB_JOURNAL_INDEX.read_text(encoding="utf-8")

    # Parse Quick Stats table
    stats = {}
    stats_match = re.search(
        r"## Quick Stats\s*\n(.*?)(?=\n---|\n## )", content, re.DOTALL
    )
    if stats_match:
        for m in re.finditer(
            r"\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|", stats_match.group(1)
        ):
            stats[m.group(1).strip()] = m.group(2).strip()

    # Parse Skills Progression
    skills: dict[str, list[str]] = {"mastered": [], "in_progress": [], "planned": []}
    skills_match = re.search(
        r"## Skills Progression\s*\n(.*?)(?=\n---|\n## (?!#))", content, re.DOTALL
    )
    if skills_match:
        current_section = None
        for line in skills_match.group(1).split("\n"):
            if "### Mastered" in line:
                current_section = "mastered"
            elif "### In Progress" in line:
                current_section = "in_progress"
            elif "### Planned" in line:
                current_section = "planned"
            elif current_section and line.strip().startswith("- ["):
                item = re.sub(r"^-\s*\[[ x]\]\s*", "", line.strip())
                if item:
                    skills[current_section].append(item)

    # Parse SOC Readiness
    readiness: dict = {"completed": 0, "total": 0, "items": []}
    readiness_match = re.search(
        r"## SOC Analyst Readiness.*?\n(.*?)(?=\n---|\n## |\Z)", content, re.DOTALL
    )
    if readiness_match:
        for m in re.finditer(r"-\s*\[([ x])\]\s*(.+)", readiness_match.group(1)):
            checked = m.group(1) == "x"
            readiness["total"] += 1
            if checked:
                readiness["completed"] += 1
            readiness["items"].append({"item": m.group(2).strip(), "done": checked})

    # Parse recent journal entries
    entries = _parse_journal_entries(content)

    return {
        "quick_stats": stats,
        "skills": skills,
        "soc_readiness": readiness,
        "recent_entries": entries[:10],
        "total_entries": len(entries),
    }


def create_journal_entry(date: str, content: str) -> dict:
    """Write a journal entry file and update JOURNAL_INDEX.md.

    Args:
        date: ISO date string (YYYY-MM-DD).
        content: Full pre-formatted markdown content (Claude composes this
                 after reading the Codex).
    """
    try:
        entry_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Invalid date format: {date}. Expected YYYY-MM-DD."}

    month_dir = config.HOMELAB_JOURNAL_DIR / entry_date.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    filename = config.HOMELAB_JOURNAL_FILENAME.format(date=date)
    filepath = month_dir / filename

    if filepath.exists():
        return {
            "status": "exists",
            "path": str(filepath),
            "message": f"Entry already exists for {date}.",
        }

    filepath.write_text(content, encoding="utf-8")
    logger.info("Created journal entry: %s", filepath)

    result: dict = {
        "status": "created",
        "path": str(filepath),
        "filename": filename,
        "date": date,
    }

    # Extract title from first H1
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else filename

    # Extract focus from header table
    focus_match = re.search(r"\*\*Focus\*\*\s*\|\s*(.+?)\s*\|", content)
    focus = focus_match.group(1).strip() if focus_match else ""

    try:
        _update_journal_index(date, title, focus, entry_date)
        result["index_updated"] = True
    except Exception as e:
        logger.error("Failed to update JOURNAL_INDEX.md: %s", e)
        result["index_updated"] = False
        result["index_error"] = str(e)

    return result


def _update_journal_index(
    date: str, title: str, focus: str, entry_date: datetime
) -> None:
    """Update JOURNAL_INDEX.md with a new entry row and bump stats."""
    if not config.HOMELAB_JOURNAL_INDEX.exists():
        raise FileNotFoundError(
            f"Journal index not found: {config.HOMELAB_JOURNAL_INDEX}"
        )

    content = config.HOMELAB_JOURNAL_INDEX.read_text(encoding="utf-8")

    # 1. Increment Total Lab Sessions
    def _bump_sessions(m: re.Match) -> str:
        num = re.search(r"\d+", m.group(0))
        if num:
            new_count = int(num.group()) + 1
            return m.group(1) + str(new_count) + m.group(2)
        return m.group(0)

    content = re.sub(
        r"(\|\s*\*\*Total Lab Sessions\*\*\s*\|\s*)\d+(\s*\|)",
        _bump_sessions,
        content,
    )

    # 2. Update Latest Entry date
    content = re.sub(
        r"(\|\s*\*\*Latest Entry\*\*\s*\|\s*)\S+(\s*\|)",
        rf"\g<1>{date}\2",
        content,
    )

    # 3. Add entry row to Journal Entries section
    month_key = entry_date.strftime("%Y-%m")
    month_header = f"### {month_key}"

    link_target = config.HOMELAB_JOURNAL_FILENAME.format(date=date).removesuffix(".md")
    new_row = f"| [[{link_target}|{date}]] | {title} | {focus} |"

    if month_header in content:
        # Insert after the table header row of the existing month section
        pattern = (
            rf"({re.escape(month_header)}\s*\n\s*\|[^\n]+\|\s*\n\s*\|[-| ]+\|)"
        )
        content = re.sub(pattern, rf"\1\n{new_row}", content)
    else:
        # Create new month section after "## Journal Entries" heading
        new_section = (
            f"\n{month_header}\n\n"
            f"| Date | Title | Focus |\n"
            f"|------|-------|-------|\n"
            f"{new_row}\n"
        )
        content = re.sub(
            r"(## Journal Entries\s*\n)",
            rf"\1{new_section}",
            content,
        )

    # 4. Update Last Updated footer
    content = re.sub(
        r"\*Last Updated: \S+\*",
        f"*Last Updated: {date}*",
        content,
    )

    config.HOMELAB_JOURNAL_INDEX.write_text(content, encoding="utf-8")
    logger.info("Updated JOURNAL_INDEX.md for %s", date)


def list_journal_entries(limit: int = 10) -> dict:
    """List recent journal entries from JOURNAL_INDEX.md."""
    if not config.HOMELAB_JOURNAL_INDEX.exists():
        return {"error": f"Journal index not found: {config.HOMELAB_JOURNAL_INDEX}"}

    content = config.HOMELAB_JOURNAL_INDEX.read_text(encoding="utf-8")
    entries = _parse_journal_entries(content)

    return {
        "count": len(entries[:limit]),
        "total": len(entries),
        "entries": entries[:limit],
    }


def _parse_journal_entries(content: str) -> list[dict]:
    """Parse Obsidian wikilink journal entry rows from markdown content."""
    entries = []
    for m in re.finditer(
        r"\|\s*\[\[(.+?)\|(.+?)\]\]\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|",
        content,
    ):
        entries.append(
            {
                "link": m.group(1).strip(),
                "date": m.group(2).strip(),
                "title": m.group(3).strip(),
                "focus": m.group(4).strip(),
            }
        )
    return entries


def list_tools(status: Optional[str] = None) -> dict:
    """Read HOMELAB_TOOLS_INVENTORY.csv, optionally filtered by status."""
    if not config.HOMELAB_TOOLS_CSV.exists():
        return {"error": f"Tools CSV not found: {config.HOMELAB_TOOLS_CSV}"}

    text = config.HOMELAB_TOOLS_CSV.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))

    tools = []
    for row in reader:
        if status and row.get("Status", "").strip().lower() != status.lower():
            continue
        tools.append(
            {
                "tool": row.get("Tool", "").strip(),
                "creator": row.get("Creator", "").strip(),
                "purpose": row.get("Purpose", "").strip(),
                "status": row.get("Status", "").strip(),
            }
        )

    return {
        "count": len(tools),
        "tools": tools,
        "csv_path": str(config.HOMELAB_TOOLS_CSV),
    }


def add_tool(
    tool: str,
    creator: str,
    purpose: str,
    status: str = "Deployed",
) -> dict:
    """Add a new tool to HOMELAB_TOOLS_INVENTORY.csv."""
    if not config.HOMELAB_TOOLS_CSV.exists():
        return {"error": f"Tools CSV not found: {config.HOMELAB_TOOLS_CSV}"}

    existing = list_tools()
    if "tools" in existing:
        for t in existing["tools"]:
            if t["tool"].lower() == tool.lower():
                return {
                    "status": "duplicate",
                    "message": f"Tool '{tool}' already exists in inventory.",
                    "existing": t,
                }

    with open(config.HOMELAB_TOOLS_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([tool, creator, purpose, status])

    logger.info("Added tool to inventory: %s", tool)
    return {
        "status": "added",
        "tool": tool,
        "creator": creator,
        "purpose": purpose,
        "tool_status": status,
        "csv_path": str(config.HOMELAB_TOOLS_CSV),
    }


def read_nexus() -> dict:
    """Read the full LAB_NEXUS.md infrastructure overview."""
    if not config.HOMELAB_NEXUS_PATH.exists():
        return {"error": f"LAB_NEXUS.md not found: {config.HOMELAB_NEXUS_PATH}"}

    content = config.HOMELAB_NEXUS_PATH.read_text(encoding="utf-8")
    return {
        "status": "ok",
        "path": str(config.HOMELAB_NEXUS_PATH),
        "content": content,
        "length": len(content),
    }


def read_codex() -> dict:
    """Read the LABSCRIBE_CODEX.md formatting rules."""
    if not config.HOMELAB_CODEX_PATH.exists():
        return {"error": f"LABSCRIBE_CODEX.md not found: {config.HOMELAB_CODEX_PATH}"}

    content = config.HOMELAB_CODEX_PATH.read_text(encoding="utf-8")
    return {
        "status": "ok",
        "path": str(config.HOMELAB_CODEX_PATH),
        "content": content,
        "length": len(content),
    }
