"""Obsidian vault sync -- exports JayBrain DB data as browsable markdown.

Runs as a daemon module every 60 seconds. Only rewrites files whose
content has actually changed (SHA-256 diffing). Generates:
  - Individual notes for memories, knowledge, tasks, sessions, concepts, entities
  - Dashboard files with aggregated views
  - Wikilinks between related notes for Obsidian graph view
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import (
    CLAUDE_PROJECTS_DIR,
    DB_PATH,
    PROJECT_ROOT,
    VAULT_PATH,
    VAULT_SYNC_ENABLED,
    VAULT_MEMORY_FOLDERS,
    FORGE_MASTERY_LEVELS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', text)
    text = re.sub(r'\s+', '-', text)
    text = text.strip('-')
    if len(text) > max_len:
        text = text[:max_len].rstrip('-')
    return text or "untitled"


def _mastery_label(mastery: float) -> str:
    """Return the forge-themed mastery label for a score."""
    label = "Spark"
    for name, threshold in FORGE_MASTERY_LEVELS:
        if mastery >= threshold:
            label = name
    return label


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_json_loads(val: str, default=None):
    """Parse a JSON string, returning default on failure."""
    if not val:
        return default if default is not None else []
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def _write_if_changed(path: Path, content: str, sync_state: dict) -> bool:
    """Write file only if content hash differs. Returns True if written."""
    content_hash = _sha256(content)
    key = str(path)

    if sync_state.get(key) == content_hash:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sync_state[key] = content_hash
    return True


def _get_conn() -> sqlite3.Connection:
    """Get a plain sqlite3 connection (no sqlite-vec needed for reads)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# ---------------------------------------------------------------------------
# Sync state persistence
# ---------------------------------------------------------------------------

_SYNC_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS vault_sync_state (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    synced_at TEXT NOT NULL
)
"""

_SYNC_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS vault_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    files_written INTEGER NOT NULL DEFAULT 0,
    files_deleted INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0
)
"""


def _ensure_sync_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SYNC_STATE_TABLE + ";\n" + _SYNC_LOG_TABLE)
    conn.commit()


def _load_sync_state(conn: sqlite3.Connection) -> dict:
    """Load file_path -> content_hash mapping."""
    rows = conn.execute("SELECT file_path, content_hash FROM vault_sync_state").fetchall()
    return {r["file_path"]: r["content_hash"] for r in rows}


def _save_sync_state(conn: sqlite3.Connection, sync_state: dict) -> None:
    """Persist the sync state back to DB."""
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO vault_sync_state (file_path, content_hash, synced_at) VALUES (?, ?, ?)",
        [(k, v, now) for k, v in sync_state.items()],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Markdown converters
# ---------------------------------------------------------------------------

def _convert_memory(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a memory row to (relative_path, markdown_content)."""
    category = row["category"] or "semantic"
    folder = VAULT_MEMORY_FOLDERS.get(category, "Knowledge")
    tags = _safe_json_loads(row["tags"])
    date_str = row["created_at"][:10] if row["created_at"] else "unknown"
    content_preview = (row["content"] or "")[:50].replace("\n", " ")
    slug = _slugify(f"{date_str}--{content_preview}")

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"category: {category}\n"
        f"importance: {row['importance']}\n"
        f"tags: {json.dumps(tags)}\n"
        f"created: {date_str}\n"
        f"updated: {(row['updated_at'] or '')[:10]}\n"
        f"access_count: {row['access_count']}\n"
        f"jaybrain_type: memory\n"
        f"---\n\n"
    )
    body = row["content"] or ""

    rel_path = Path("Memories") / folder / f"{slug}.md"
    return rel_path, frontmatter + body + "\n"


def _convert_knowledge(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a knowledge row to (relative_path, markdown_content)."""
    category = row["category"] or "general"
    tags = _safe_json_loads(row["tags"])
    slug = _slugify(row["title"] or "untitled")

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"category: {category}\n"
        f"tags: {json.dumps(tags)}\n"
        f"source: {row['source'] or ''}\n"
        f"created: {(row['created_at'] or '')[:10]}\n"
        f"updated: {(row['updated_at'] or '')[:10]}\n"
        f"jaybrain_type: knowledge\n"
        f"---\n\n"
    )
    body = f"# {row['title']}\n\n{row['content'] or ''}\n"

    rel_path = Path("Knowledge Base") / category / f"{slug}.md"
    return rel_path, frontmatter + body


def _convert_task(row: sqlite3.Row) -> tuple[str, dict]:
    """Convert a task row to a dict for aggregated task files."""
    tags = _safe_json_loads(row["tags"])
    return row["status"], {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"] or "",
        "status": row["status"],
        "priority": row["priority"],
        "project": row["project"] or "",
        "tags": tags,
        "due_date": row["due_date"] or "",
        "created": (row["created_at"] or "")[:10],
    }


def _convert_session(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a session row to (relative_path, markdown_content)."""
    started = row["started_at"] or ""
    ended = row["ended_at"] or ""
    date_str = started[:10] if started else "unknown"
    month_str = started[:7] if started else "unknown"
    title = row["title"] or "Untitled"
    slug = _slugify(f"{date_str}--{title}")
    decisions = _safe_json_loads(row["decisions_made"])
    next_steps = _safe_json_loads(row["next_steps"])

    # Calculate duration
    duration_str = ""
    if started and ended:
        try:
            s = datetime.fromisoformat(started)
            e = datetime.fromisoformat(ended)
            mins = int((e - s).total_seconds() / 60)
            duration_str = f"{mins} min"
        except (ValueError, TypeError):
            pass

    frontmatter = (
        f"---\n"
        f"session_id: {row['id']}\n"
        f"started: {started}\n"
        f"ended: {ended}\n"
        f"duration: {duration_str}\n"
        f"jaybrain_type: session\n"
        f"---\n\n"
    )

    body = f"# {title}\n\n"
    if row["summary"]:
        body += f"## Summary\n{row['summary']}\n\n"
    if decisions:
        body += "## Decisions Made\n"
        for d in decisions:
            body += f"- {d}\n"
        body += "\n"
    if next_steps:
        body += "## Next Steps\n"
        for n in next_steps:
            body += f"- [ ] {n}\n"
        body += "\n"

    rel_path = Path("Sessions") / month_str / f"{slug}.md"
    return rel_path, frontmatter + body


def _convert_concept(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a forge concept to (relative_path, markdown_content)."""
    category = row["category"] or "general"
    mastery = row["mastery_level"] or 0.0
    label = _mastery_label(mastery)
    tags = _safe_json_loads(row["tags"])
    slug = _slugify(row["term"] or "untitled")

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"term: {row['term']}\n"
        f"category: {category}\n"
        f"difficulty: {row['difficulty'] or 'beginner'}\n"
        f"mastery: {mastery:.2f}\n"
        f"mastery_label: {label}\n"
        f"bloom_level: {row['bloom_level'] or 'remember'}\n"
        f"subject_id: {row['subject_id'] or ''}\n"
        f"next_review: {(row['next_review'] or '')[:10]}\n"
        f"review_count: {row['review_count'] or 0}\n"
        f"correct_count: {row['correct_count'] or 0}\n"
        f"tags: {json.dumps(tags)}\n"
        f"jaybrain_type: forge_concept\n"
        f"---\n\n"
    )

    body = f"# {row['term']}\n\n{row['definition'] or ''}\n"
    if row["notes"]:
        body += f"\n## Notes\n{row['notes']}\n"
    if row["related_jaybrain_component"]:
        body += f"\n**Related JayBrain component:** {row['related_jaybrain_component']}\n"

    rel_path = Path("Learning") / "Concepts" / category / f"{slug}.md"
    return rel_path, frontmatter + body


def _convert_entity(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a graph entity to (relative_path, markdown_content)."""
    entity_type = row["entity_type"] or "concept"
    aliases = _safe_json_loads(row["aliases"])
    properties = _safe_json_loads(row["properties"], default={})
    slug = _slugify(row["name"] or "untitled")

    # Route to appropriate folder
    type_folders = {
        "person": "Network/Contacts",
        "project": "Network/Projects",
        "tool": "Network/Tools",
        "skill": "Network/Tools",
        "company": "Network/Contacts",
        "concept": "Network/Tools",
        "location": "Network/Tools",
        "organization": "Network/Contacts",
    }
    folder = type_folders.get(entity_type, "Network/Tools")

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"name: {row['name']}\n"
        f"entity_type: {entity_type}\n"
        f"aliases: {json.dumps(aliases)}\n"
        f"jaybrain_type: graph_entity\n"
        f"---\n\n"
    )

    body = f"# {row['name']}\n\n"
    body += f"**Type:** {entity_type}\n\n"
    if row["description"]:
        body += f"{row['description']}\n\n"
    if aliases:
        body += f"**Aliases:** {', '.join(aliases)}\n\n"
    if properties:
        body += "## Properties\n"
        for k, v in properties.items():
            body += f"- **{k}:** {v}\n"
        body += "\n"

    rel_path = Path(folder) / f"{slug}.md"
    return rel_path, frontmatter + body


def _convert_goal(row: sqlite3.Row, domain_name: str) -> tuple[Path, str]:
    """Convert a life goal to (relative_path, markdown_content)."""
    slug = _slugify(row["title"] or "untitled")
    domain_slug = _slugify(domain_name or "general")
    progress = row["progress"] or 0.0
    progress_pct = int(progress * 100)

    # Progress bar
    filled = int(progress_pct / 5)
    bar = "[" + "#" * filled + "-" * (20 - filled) + f"] {progress_pct}%"

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"domain: {domain_name}\n"
        f"status: {row['status'] or 'active'}\n"
        f"progress: {progress:.2f}\n"
        f"target_date: {row['target_date'] or ''}\n"
        f"jaybrain_type: life_goal\n"
        f"---\n\n"
    )

    body = f"# {row['title']}\n\n"
    body += f"**Domain:** {domain_name}  \n"
    body += f"**Progress:** {bar}  \n"
    body += f"**Status:** {row['status'] or 'active'}  \n"
    if row["target_date"]:
        body += f"**Target:** {row['target_date']}  \n"
    body += "\n"
    if row["description"]:
        body += f"{row['description']}\n"

    rel_path = Path("Goals") / domain_slug / f"{slug}.md"
    return rel_path, frontmatter + body


def _convert_application(row: sqlite3.Row) -> tuple[Path, str]:
    """Convert a job application to (relative_path, markdown_content)."""
    company = row["company"] or "Unknown"
    title = row["title"] or "Unknown Role"
    slug = _slugify(f"{company}--{title}")
    status = row["status"] or "discovered"
    tags = _safe_json_loads(row["app_tags"] if "app_tags" in row.keys() else "[]")

    frontmatter = (
        f"---\n"
        f"id: {row['id']}\n"
        f"job_id: {row['job_id']}\n"
        f"company: {company}\n"
        f"role: {title}\n"
        f"status: {status}\n"
        f"work_mode: {row['work_mode'] or ''}\n"
        f"applied_date: {row['applied_date'] or ''}\n"
        f"tags: {json.dumps(tags)}\n"
        f"jaybrain_type: application\n"
        f"---\n\n"
    )

    body = f"# {company} -- {title}\n\n"
    body += f"**Status:** {status}  \n"
    body += f"**Work mode:** {row['work_mode'] or 'N/A'}  \n"
    if row["applied_date"]:
        body += f"**Applied:** {row['applied_date']}  \n"
    body += "\n"
    if row["notes"]:
        body += f"## Notes\n{row['notes']}\n"

    rel_path = Path("Jobs") / "Applications" / f"{slug}.md"
    return rel_path, frontmatter + body


# ---------------------------------------------------------------------------
# Dashboard generators
# ---------------------------------------------------------------------------

def _generate_dashboard(conn: sqlite3.Connection) -> str:
    """Generate the main Dashboard.md content."""
    now = datetime.now(timezone.utc).isoformat()[:16]

    # Task counts
    task_counts = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"):
        task_counts[row["status"]] = row["cnt"]

    # Memory count
    mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    # Concept stats
    concept_row = conn.execute(
        "SELECT COUNT(*) as total, AVG(mastery_level) as avg_mastery FROM forge_concepts"
    ).fetchone()
    concept_total = concept_row["total"] or 0
    avg_mastery = concept_row["avg_mastery"] or 0.0

    # Due concepts
    due_count = conn.execute(
        "SELECT COUNT(*) FROM forge_concepts WHERE next_review <= datetime('now')"
    ).fetchone()[0]

    # Active applications
    app_counts = {}
    try:
        for row in conn.execute("SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"):
            app_counts[row["status"]] = row["cnt"]
    except sqlite3.OperationalError:
        pass

    # Session count
    session_count = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL"
    ).fetchone()[0]

    content = (
        f"---\n"
        f"updated: {now}\n"
        f"jaybrain_type: dashboard\n"
        f"---\n\n"
        f"# JayBrain Dashboard\n\n"
        f"*Last synced: {now} UTC*\n\n"
        f"## Quick Stats\n\n"
        f"| Metric | Count |\n"
        f"|--------|-------|\n"
        f"| Memories | {mem_count} |\n"
        f"| Sessions logged | {session_count} |\n"
        f"| Forge concepts | {concept_total} |\n"
        f"| Avg mastery | {avg_mastery:.0%} ({_mastery_label(avg_mastery)}) |\n"
        f"| Due for review | {due_count} |\n"
        f"\n"
        f"## Tasks\n\n"
        f"| Status | Count |\n"
        f"|--------|-------|\n"
    )
    for status in ["todo", "in_progress", "blocked", "done", "cancelled"]:
        cnt = task_counts.get(status, 0)
        if cnt > 0:
            content += f"| {status} | {cnt} |\n"

    if app_counts:
        content += (
            f"\n## Job Pipeline\n\n"
            f"| Stage | Count |\n"
            f"|-------|-------|\n"
        )
        for status in ["discovered", "preparing", "ready", "applied",
                        "interviewing", "offered", "rejected", "withdrawn"]:
            cnt = app_counts.get(status, 0)
            if cnt > 0:
                content += f"| {status} | {cnt} |\n"

    content += (
        f"\n## Quick Links\n\n"
        f"- [[Tasks/Active]]\n"
        f"- [[Learning/Study Progress]]\n"
        f"- [[Jobs/Pipeline]]\n"
        f"- [[Mistakes/MISTAKES_LOG]]\n"
    )

    return content


def _generate_active_tasks(conn: sqlite3.Connection) -> str:
    """Generate Tasks/Active.md with all non-done tasks."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status NOT IN ('done', 'cancelled') ORDER BY priority DESC, created_at DESC"
    ).fetchall()

    content = (
        f"---\njaybrain_type: task_list\n---\n\n"
        f"# Active Tasks\n\n"
    )

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for row in rows:
        tags = _safe_json_loads(row["tags"])
        tag_str = f" `{'` `'.join(tags)}`" if tags else ""
        check = "x" if row["status"] == "done" else " "
        priority_marker = ""
        if row["priority"] in ("critical", "high"):
            priority_marker = f" **[{row['priority'].upper()}]**"
        due = f" (due: {row['due_date']})" if row["due_date"] else ""
        project = f" *{row['project']}*" if row["project"] else ""

        content += f"- [{check}] {row['title']}{priority_marker}{project}{due}{tag_str}\n"
        if row["description"]:
            # Indent description under the task
            for line in row["description"].split("\n")[:3]:
                content += f"  {line}\n"

    if not rows:
        content += "*No active tasks.*\n"

    return content


def _generate_study_progress(conn: sqlite3.Connection) -> str:
    """Generate Learning/Study Progress.md."""
    # Mastery distribution
    distribution = {}
    for name, threshold in FORGE_MASTERY_LEVELS:
        distribution[name] = 0

    rows = conn.execute("SELECT mastery_level FROM forge_concepts").fetchall()
    for row in rows:
        label = _mastery_label(row["mastery_level"] or 0.0)
        distribution[label] = distribution.get(label, 0) + 1

    # Streak info
    streak_rows = conn.execute(
        "SELECT * FROM forge_streaks ORDER BY date DESC LIMIT 7"
    ).fetchall()

    # Subject readiness
    subject_rows = conn.execute(
        """SELECT s.short_name, s.pass_score,
                  COUNT(c.id) as concepts,
                  AVG(c.mastery_level) as avg_mastery
           FROM forge_subjects s
           LEFT JOIN forge_concepts c ON c.subject_id = s.id
           GROUP BY s.id"""
    ).fetchall()

    content = (
        f"---\njaybrain_type: study_progress\n---\n\n"
        f"# Study Progress\n\n"
        f"## Mastery Distribution\n\n"
        f"| Level | Count |\n"
        f"|-------|-------|\n"
    )
    for name, _ in FORGE_MASTERY_LEVELS:
        cnt = distribution.get(name, 0)
        if cnt > 0:
            content += f"| {name} | {cnt} |\n"

    if subject_rows:
        content += "\n## Subjects\n\n"
        for sr in subject_rows:
            avg = sr["avg_mastery"] or 0.0
            content += (
                f"### {sr['short_name']}\n"
                f"- Concepts: {sr['concepts']}\n"
                f"- Avg mastery: {avg:.0%} ({_mastery_label(avg)})\n"
                f"- Pass score: {sr['pass_score']:.0%}\n\n"
            )

    if streak_rows:
        content += "## Recent Study Activity\n\n"
        content += "| Date | Reviewed | Added |\n"
        content += "|------|----------|-------|\n"
        for sr in streak_rows:
            content += f"| {sr['date']} | {sr['concepts_reviewed']} | {sr['concepts_added']} |\n"

    return content


def _generate_pipeline(conn: sqlite3.Connection) -> str:
    """Generate Jobs/Pipeline.md."""
    try:
        rows = conn.execute(
            """SELECT a.*, j.title, j.company, j.work_mode
               FROM applications a
               JOIN job_postings j ON j.id = a.job_id
               ORDER BY a.updated_at DESC"""
        ).fetchall()
    except sqlite3.OperationalError:
        return "---\njaybrain_type: pipeline\n---\n\n# Job Pipeline\n\n*No applications yet.*\n"

    content = (
        f"---\njaybrain_type: pipeline\n---\n\n"
        f"# Job Pipeline\n\n"
    )

    stages = ["discovered", "preparing", "ready", "applied",
              "interviewing", "offered", "rejected", "withdrawn"]
    for stage in stages:
        stage_rows = [r for r in rows if r["status"] == stage]
        if not stage_rows:
            continue
        content += f"## {stage.title()} ({len(stage_rows)})\n\n"
        for r in stage_rows:
            company = r["company"] or "Unknown"
            title = r["title"] or "Unknown"
            slug = _slugify(f"{company}--{title}")
            content += f"- [[Applications/{slug}|{company} -- {title}]]\n"
        content += "\n"

    if not rows:
        content += "*No applications tracked yet.*\n"

    return content


# ---------------------------------------------------------------------------
# Wiki-link injection
# ---------------------------------------------------------------------------

_ENTITY_TYPE_FOLDERS = {
    "person": "Network/Contacts",
    "project": "Network/Projects",
    "tool": "Network/Tools",
    "skill": "Network/Tools",
    "company": "Network/Contacts",
    "concept": "Network/Tools",
    "location": "Network/Tools",
    "organization": "Network/Contacts",
}


def _build_entity_index(conn: sqlite3.Connection) -> dict[str, str]:
    """Build a mapping of entity_name -> vault relative path for wikilinks."""
    index = {}
    try:
        rows = conn.execute(
            "SELECT name, entity_type FROM graph_entities"
        ).fetchall()
        for row in rows:
            name = row["name"]
            entity_type = row["entity_type"] or "concept"
            folder = _ENTITY_TYPE_FOLDERS.get(entity_type, "Network/Tools")
            slug = _slugify(name)
            index[name] = f"{folder}/{slug}"
    except sqlite3.OperationalError:
        pass  # table may not exist yet
    return index


def _inject_wikilinks(
    body: str,
    entity_index: dict[str, str],
    self_name: str = "",
) -> str:
    """Replace known entity names in body text with [[wiki-links]].

    Skips names already inside [[]], names shorter than 3 chars,
    self-references, and content inside code blocks.
    """
    if not entity_index or not body:
        return body

    # Sort by length descending to match longer names first
    sorted_names = sorted(entity_index.keys(), key=len, reverse=True)

    for name in sorted_names:
        if name == self_name or len(name) < 3:
            continue
        # Word-boundary match, skip if already inside [[]]
        pattern = re.compile(r"(?<!\[\[)\b" + re.escape(name) + r"\b(?!\]\])")
        body = pattern.sub(f"[[{name}]]", body, count=3)

    return body


def _build_backlinks(
    all_notes: list[tuple[str, str, str]],
) -> dict[str, list[str]]:
    """Build a mapping of linked_name -> list of source note titles.

    all_notes: [(note_title, rel_path_str, body), ...]
    Returns: {"JayBrain": ["Memory note about...", "Session 2026-02..."]}
    """
    backlinks: dict[str, list[str]] = {}
    link_pattern = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")

    for note_title, _rel_path, body in all_notes:
        links = link_pattern.findall(body)
        for link_target in links:
            if link_target not in backlinks:
                backlinks[link_target] = []
            if note_title not in backlinks[link_target]:
                backlinks[link_target].append(note_title)

    return backlinks


def _append_backlinks(body: str, title: str, backlinks: dict[str, list[str]]) -> str:
    """Append a Backlinks section to body if any notes link to this title."""
    refs = backlinks.get(title, [])
    if not refs:
        return body
    section = "\n\n## Backlinks\n"
    for ref in sorted(refs)[:20]:  # Cap at 20 to avoid massive sections
        section += f"- [[{ref}]]\n"
    return body + section


# ---------------------------------------------------------------------------
# Verbatim conversation archiving
# ---------------------------------------------------------------------------

def _convert_conversation_verbatim(jsonl_path: Path) -> Optional[tuple[Path, str]]:
    """Convert a JSONL conversation file to full verbatim markdown.

    Returns (relative_path, content) or None if parsing fails.
    """
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    if not lines:
        return None

    session_id = jsonl_path.stem
    turns = []
    first_ts = ""
    last_ts = ""
    tool_calls = []

    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type", "")
        timestamp = obj.get("timestamp", "")

        if not first_ts and timestamp:
            first_ts = timestamp
        if timestamp:
            last_ts = timestamp

        message = obj.get("message", {})
        content = message.get("content", "")

        if msg_type == "user":
            text = content if isinstance(content, str) else ""
            if isinstance(content, list):
                text = "\n".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            if text.strip():
                turns.append({"role": "user", "text": text.strip(), "ts": timestamp})

        elif msg_type == "assistant":
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            turns.append({
                                "role": "assistant",
                                "text": block["text"].strip(),
                                "ts": timestamp,
                            })
                        elif block.get("type") == "tool_use":
                            tool_calls.append(block.get("name", "unknown"))

    if not turns:
        return None

    # Build markdown
    month_str = first_ts[:7] if len(first_ts) >= 7 else "unknown"
    date_str = first_ts[:10] if len(first_ts) >= 10 else "unknown"

    frontmatter = (
        f"---\n"
        f"session_id: {session_id}\n"
        f"started: {first_ts}\n"
        f"ended: {last_ts}\n"
        f"tool_count: {len(tool_calls)}\n"
        f"turn_count: {len(turns)}\n"
        f"jaybrain_type: conversation\n"
        f"---\n\n"
    )

    body = f"# Conversation {date_str}\n\n"
    body += f"**Session:** `{session_id}`\n\n---\n\n"

    for turn in turns:
        role = turn["role"]
        ts = turn["ts"]
        time_str = ts[11:19] if len(ts) > 19 else ""
        text = turn["text"]
        # Truncate extremely long turns for vault readability
        if len(text) > 5000:
            text = text[:5000] + "\n\n*[truncated]*"

        if role == "user":
            body += f"### User {time_str}\n\n{text}\n\n"
        else:
            body += f"### Assistant {time_str}\n\n{text}\n\n"

    # Tool usage summary
    if tool_calls:
        from collections import Counter
        tool_counts = Counter(tool_calls)
        body += "---\n\n## Tool Usage\n\n"
        for tool, count in tool_counts.most_common():
            body += f"- `{tool}`: {count}\n"

    rel_path = Path("Conversations") / month_str / f"{session_id}.md"
    return rel_path, frontmatter + body


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------

def run_vault_sync() -> dict:
    """Daemon entry point: sync JayBrain DB to Obsidian vault.

    Returns a summary dict with files_written and files_deleted counts.
    """
    if not VAULT_SYNC_ENABLED:
        return {"status": "disabled"}

    import time
    start = time.monotonic()

    vault = VAULT_PATH
    vault.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    try:
        _ensure_sync_tables(conn)
        sync_state = _load_sync_state(conn)
        files_written = 0
        tracked_files = set()

        # Build entity index for wiki-link injection
        entity_index = _build_entity_index(conn)

        # Collect all notes for backlinks computation (title, rel_path, body)
        all_notes: list[tuple[str, str, str]] = []

        # ---- Memories ----
        rows = conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC"
        ).fetchall()
        for row in rows:
            rel_path, content = _convert_memory(row)
            # Inject wiki-links into body (after frontmatter)
            if entity_index:
                parts = content.split("---\n\n", 2)
                if len(parts) >= 3:
                    body = _inject_wikilinks(parts[2], entity_index)
                    content = parts[0] + "---\n\n" + parts[1] + "---\n\n" + body
            title = (row["content"] or "")[:50].replace("\n", " ")
            all_notes.append((title, str(rel_path), content))
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Knowledge ----
        rows = conn.execute(
            "SELECT * FROM knowledge ORDER BY created_at DESC"
        ).fetchall()
        for row in rows:
            rel_path, content = _convert_knowledge(row)
            if entity_index:
                parts = content.split("---\n\n", 2)
                if len(parts) >= 3:
                    body = _inject_wikilinks(
                        parts[2], entity_index,
                        self_name=row["title"] or "",
                    )
                    content = parts[0] + "---\n\n" + parts[1] + "---\n\n" + body
            title = row["title"] or "untitled"
            all_notes.append((title, str(rel_path), content))
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Tasks (aggregated into Active.md) ----
        active_content = _generate_active_tasks(conn)
        active_path = vault / "Tasks" / "Active.md"
        tracked_files.add(str(active_path))
        if _write_if_changed(active_path, active_content, sync_state):
            files_written += 1

        # ---- Sessions ----
        rows = conn.execute(
            "SELECT * FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC"
        ).fetchall()
        for row in rows:
            rel_path, content = _convert_session(row)
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Forge Concepts ----
        rows = conn.execute(
            "SELECT * FROM forge_concepts ORDER BY category, term"
        ).fetchall()
        for row in rows:
            rel_path, content = _convert_concept(row)
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Graph Entities ----
        rows = conn.execute(
            "SELECT * FROM graph_entities ORDER BY entity_type, name"
        ).fetchall()
        for row in rows:
            rel_path, content = _convert_entity(row)
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Life Goals ----
        rows = conn.execute(
            """SELECT g.*, d.name as domain_name
               FROM life_goals g
               LEFT JOIN life_domains d ON d.id = g.domain_id
               ORDER BY d.priority, g.title"""
        ).fetchall()
        for row in rows:
            domain_name = row["domain_name"] or "General"
            rel_path, content = _convert_goal(row, domain_name)
            full_path = vault / rel_path
            tracked_files.add(str(full_path))
            if _write_if_changed(full_path, content, sync_state):
                files_written += 1

        # ---- Applications ----
        try:
            rows = conn.execute(
                """SELECT a.id, a.job_id, a.status, a.applied_date, a.notes,
                          a.tags as app_tags, a.created_at, a.updated_at,
                          j.title, j.company, j.work_mode
                   FROM applications a
                   JOIN job_postings j ON j.id = a.job_id
                   ORDER BY a.updated_at DESC"""
            ).fetchall()
            for row in rows:
                rel_path, content = _convert_application(row)
                full_path = vault / rel_path
                tracked_files.add(str(full_path))
                if _write_if_changed(full_path, content, sync_state):
                    files_written += 1
        except sqlite3.OperationalError:
            pass  # tables may not exist yet

        # ---- Audit Reports (from data/ folder) ----
        data_dir = Path(DB_PATH).parent
        for report_path in sorted(data_dir.glob("audit_report_*.md")):
            dest = vault / "Debugging" / report_path.name
            tracked_files.add(str(dest))
            try:
                content = report_path.read_text(encoding="utf-8")
                if _write_if_changed(dest, content, sync_state):
                    files_written += 1
            except Exception:
                pass

        # ---- CLAUDE.md (master + vault extras) ----
        try:
            master_claude = PROJECT_ROOT / "CLAUDE.md"
            vault_extras = vault / "CLAUDE_vault_extras.md"
            if master_claude.exists():
                warning = (
                    "<!-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! -->\n"
                    "<!-- DO NOT EDIT THIS FILE -- IT IS AUTO-GENERATED          -->\n"
                    "<!-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! -->\n"
                    "<!--                                                        -->\n"
                    "<!-- This file is rebuilt every 60 seconds by the daemon.   -->\n"
                    "<!-- Any changes you make here WILL BE OVERWRITTEN.         -->\n"
                    "<!--                                                        -->\n"
                    "<!-- To edit shared rules:  jaybrain/CLAUDE.md (the master) -->\n"
                    "<!-- To edit vault rules:   CLAUDE_vault_extras.md          -->\n"
                    "<!--                                                        -->\n"
                    "<!-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! -->\n\n"
                )
                parts = [warning + master_claude.read_text(encoding="utf-8")]
                if vault_extras.exists():
                    extras = vault_extras.read_text(encoding="utf-8")
                    # Strip the HTML comment header from extras
                    if extras.startswith("<!--"):
                        end = extras.find("-->")
                        if end != -1:
                            extras = extras[end + 3:].lstrip("\n")
                    parts.append(extras)
                combined = "\n\n".join(parts)
                claude_path = vault / "CLAUDE.md"
                if _write_if_changed(claude_path, combined, sync_state):
                    files_written += 1
        except Exception:
            logger.warning("Failed to rebuild vault CLAUDE.md", exc_info=True)

        # ---- Verbatim Conversations ----
        try:
            if CLAUDE_PROJECTS_DIR.exists():
                for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
                    if not project_dir.is_dir():
                        continue
                    for jsonl_file in sorted(project_dir.glob("*.jsonl")):
                        try:
                            result = _convert_conversation_verbatim(jsonl_file)
                            if result is None:
                                continue
                            rel_path, content = result
                            full_path = vault / rel_path
                            tracked_files.add(str(full_path))
                            if _write_if_changed(full_path, content, sync_state):
                                files_written += 1
                        except Exception:
                            pass
        except Exception:
            logger.debug("Conversation archive to vault failed", exc_info=True)

        # ---- Dashboard files ----
        dashboard_content = _generate_dashboard(conn)
        dash_path = vault / "Dashboard.md"
        tracked_files.add(str(dash_path))
        if _write_if_changed(dash_path, dashboard_content, sync_state):
            files_written += 1

        progress_content = _generate_study_progress(conn)
        progress_path = vault / "Learning" / "Study Progress.md"
        tracked_files.add(str(progress_path))
        if _write_if_changed(progress_path, progress_content, sync_state):
            files_written += 1

        pipeline_content = _generate_pipeline(conn)
        pipeline_path = vault / "Jobs" / "Pipeline.md"
        tracked_files.add(str(pipeline_path))
        if _write_if_changed(pipeline_path, pipeline_content, sync_state):
            files_written += 1

        # ---- Clean up deleted items ----
        files_deleted = 0
        stale_keys = []
        for file_path in list(sync_state.keys()):
            if file_path.startswith(str(vault)) and file_path not in tracked_files:
                p = Path(file_path)
                if p.exists() and p.suffix == ".md":
                    # Only delete files we created (have jaybrain_type in frontmatter)
                    try:
                        head = p.read_text(encoding="utf-8")[:200]
                        if "jaybrain_type:" in head:
                            p.unlink()
                            files_deleted += 1
                    except Exception:
                        pass
                stale_keys.append(file_path)

        for key in stale_keys:
            sync_state.pop(key, None)

        # ---- Persist state ----
        _save_sync_state(conn, sync_state)

        duration_ms = int((time.monotonic() - start) * 1000)
        conn.execute(
            "INSERT INTO vault_sync_log (run_at, files_written, files_deleted, duration_ms) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), files_written, files_deleted, duration_ms),
        )
        conn.commit()

        if files_written > 0 or files_deleted > 0:
            logger.info(
                "Vault sync: %d written, %d deleted in %dms",
                files_written, files_deleted, duration_ms,
            )

        return {
            "status": "ok",
            "files_written": files_written,
            "files_deleted": files_deleted,
            "duration_ms": duration_ms,
        }

    except Exception:
        logger.exception("Vault sync failed")
        return {"status": "error"}
    finally:
        conn.close()
