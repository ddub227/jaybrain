"""JayBrain Daily Briefing - sends a morning email digest at 7:00 AM.

Queries the JayBrain SQLite database for tasks, SynapseForge stats, and
job applications. Reads the networking tracker from Google Sheets. Composes
a clean HTML email and sends it via the Gmail API.

Run as:
    python -m jaybrain.daily_briefing

Or via Windows Task Scheduler at 7:00 AM daily.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, date, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "")
NETWORKING_SPREADSHEET_ID = os.environ.get("NETWORKING_SPREADSHEET_ID", "")
NETWORKING_SHEET = "Networking"
PIPELINE_SHEET = "Pipeline"

# Use centralized scopes from config
from .config import OAUTH_SCOPES

logger = logging.getLogger("jaybrain.daily_briefing")

# ---------------------------------------------------------------------------
# Google Auth (reuses the same OAuth token file as gdocs.py)
# ---------------------------------------------------------------------------


def _get_google_credentials():
    """Load OAuth credentials for all Google API access.

    Reuses the existing OAuth token from gdocs integration.
    Supports Sheets, Gmail, Docs, and Drive via centralized scopes.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        from .config import OAUTH_TOKEN_PATH

        if not OAUTH_TOKEN_PATH.exists():
            logger.warning("No OAuth token found at %s", OAUTH_TOKEN_PATH)
            return None

        creds = Credentials.from_authorized_user_file(
            str(OAUTH_TOKEN_PATH), OAUTH_SCOPES,
        )

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        return creds if creds and creds.valid else None
    except Exception as e:
        logger.error("Failed to load Google credentials: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Data Collectors
# ---------------------------------------------------------------------------


def _get_db_connection() -> Optional[sqlite3.Connection]:
    """Open a read-only connection to the JayBrain database.

    We intentionally avoid loading sqlite-vec here since we only need
    plain SQL reads -- no vector search. This keeps the briefing script
    lightweight and avoids import errors in environments where the
    extension binary is not available.
    """
    from .config import DB_PATH

    if not DB_PATH.exists():
        logger.warning("Database not found at %s", DB_PATH)
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error("Failed to open database: %s", e)
        return None


def collect_tasks(conn: sqlite3.Connection) -> dict:
    """Collect active tasks grouped by priority."""
    try:
        rows = conn.execute(
            """SELECT id, title, description, status, priority, project,
                      tags, due_date, created_at, updated_at
               FROM tasks
               WHERE status IN ('todo', 'in_progress', 'blocked')
               ORDER BY
                   CASE priority
                       WHEN 'critical' THEN 1
                       WHEN 'high' THEN 2
                       WHEN 'medium' THEN 3
                       WHEN 'low' THEN 4
                   END,
                   due_date ASC NULLS LAST"""
        ).fetchall()

        tasks = []
        for r in rows:
            tasks.append({
                "title": r["title"],
                "status": r["status"],
                "priority": r["priority"],
                "project": r["project"] or "",
                "due_date": r["due_date"] or "",
                "description": r["description"] or "",
            })

        # Count overdue
        today_str = date.today().isoformat()
        overdue = sum(
            1 for t in tasks
            if t["due_date"] and t["due_date"] < today_str
        )

        return {"tasks": tasks, "overdue_count": overdue}
    except Exception as e:
        logger.error("Failed to collect tasks: %s", e)
        return {"tasks": [], "overdue_count": 0, "error": str(e)}


def collect_job_pipeline(conn: sqlite3.Connection) -> dict:
    """Collect job application pipeline status."""
    try:
        # Pipeline counts
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
        ).fetchall()
        pipeline = {r["status"]: r["cnt"] for r in rows}

        # Active applications with job details
        apps = conn.execute(
            """SELECT a.id, a.status, a.applied_date, a.notes,
                      j.title, j.company, j.work_mode, j.url
               FROM applications a
               JOIN job_postings j ON j.id = a.job_id
               WHERE a.status NOT IN ('rejected', 'withdrawn')
               ORDER BY a.updated_at DESC
               LIMIT 20"""
        ).fetchall()

        active_apps = []
        for a in apps:
            active_apps.append({
                "title": a["title"],
                "company": a["company"],
                "status": a["status"],
                "work_mode": a["work_mode"],
                "applied_date": a["applied_date"] or "",
                "url": a["url"] or "",
            })

        return {"pipeline": pipeline, "active_apps": active_apps}
    except Exception as e:
        logger.error("Failed to collect job pipeline: %s", e)
        return {"pipeline": {}, "active_apps": [], "error": str(e)}


def collect_forge_stats(conn: sqlite3.Connection) -> dict:
    """Collect SynapseForge study statistics."""
    try:
        # Total concepts
        total = conn.execute("SELECT COUNT(*) FROM forge_concepts").fetchone()[0]

        # Due now
        now_iso = datetime.now(timezone.utc).isoformat()
        due_count = conn.execute(
            "SELECT COUNT(*) FROM forge_concepts WHERE next_review <= ?",
            (now_iso,),
        ).fetchone()[0]

        # Average mastery
        avg_row = conn.execute(
            "SELECT AVG(mastery_level) FROM forge_concepts"
        ).fetchone()
        avg_mastery = round(avg_row[0] or 0.0, 2)

        # Mastery distribution
        mastery_dist = {}
        for label, threshold in [
            ("Forged (95%+)", 0.95), ("Inferno (80-95%)", 0.80),
            ("Blaze (60-80%)", 0.60), ("Flame (40-60%)", 0.40),
            ("Ember (20-40%)", 0.20), ("Spark (0-20%)", 0.0),
        ]:
            mastery_dist[label] = 0

        concept_rows = conn.execute(
            "SELECT mastery_level FROM forge_concepts"
        ).fetchall()
        for cr in concept_rows:
            m = cr[0]
            if m >= 0.95:
                mastery_dist["Forged (95%+)"] += 1
            elif m >= 0.80:
                mastery_dist["Inferno (80-95%)"] += 1
            elif m >= 0.60:
                mastery_dist["Blaze (60-80%)"] += 1
            elif m >= 0.40:
                mastery_dist["Flame (40-60%)"] += 1
            elif m >= 0.20:
                mastery_dist["Ember (20-40%)"] += 1
            else:
                mastery_dist["Spark (0-20%)"] += 1

        # Streak calculation
        streak_rows = conn.execute(
            "SELECT date FROM forge_streaks ORDER BY date DESC LIMIT 90"
        ).fetchall()
        streak_dates = {r["date"] for r in streak_rows}
        current_streak = 0
        check_date = date.today()
        while check_date.isoformat() in streak_dates:
            current_streak += 1
            check_date -= timedelta(days=1)

        # Total reviews
        total_reviews = conn.execute(
            "SELECT COUNT(*) FROM forge_reviews"
        ).fetchone()[0]

        # Subjects
        subjects = []
        subject_rows = conn.execute(
            "SELECT id, name, short_name FROM forge_subjects WHERE active = 1"
        ).fetchall()
        for s in subject_rows:
            concept_count = conn.execute(
                "SELECT COUNT(*) FROM forge_concepts WHERE subject_id = ?",
                (s["id"],),
            ).fetchone()[0]
            subjects.append({
                "name": s["name"],
                "short_name": s["short_name"],
                "concept_count": concept_count,
            })

        return {
            "total_concepts": total,
            "due_count": due_count,
            "avg_mastery": avg_mastery,
            "mastery_distribution": mastery_dist,
            "current_streak": current_streak,
            "total_reviews": total_reviews,
            "subjects": subjects,
        }
    except Exception as e:
        logger.error("Failed to collect forge stats: %s", e)
        return {
            "total_concepts": 0, "due_count": 0, "avg_mastery": 0.0,
            "mastery_distribution": {}, "current_streak": 0,
            "total_reviews": 0, "subjects": [], "error": str(e),
        }


def collect_upcoming_deadlines(conn: sqlite3.Connection) -> list[dict]:
    """Collect deadlines from tasks within the next 7 days."""
    try:
        today = date.today()
        week_out = (today + timedelta(days=7)).isoformat()
        today_str = today.isoformat()

        rows = conn.execute(
            """SELECT title, due_date, priority, project, status
               FROM tasks
               WHERE due_date IS NOT NULL
                 AND due_date <= ?
                 AND status NOT IN ('done', 'cancelled')
               ORDER BY due_date ASC""",
            (week_out,),
        ).fetchall()

        deadlines = []
        for r in rows:
            is_overdue = r["due_date"] < today_str
            deadlines.append({
                "title": r["title"],
                "due_date": r["due_date"],
                "priority": r["priority"],
                "project": r["project"] or "",
                "status": r["status"],
                "overdue": is_overdue,
            })
        return deadlines
    except Exception as e:
        logger.error("Failed to collect deadlines: %s", e)
        return []


def collect_networking_tracker(creds) -> dict:
    """Read the networking tracker from Google Sheets."""
    try:
        from googleapiclient.discovery import build

        service = build(
            "sheets", "v4", credentials=creds, cache_discovery=False,
        )
        result = service.spreadsheets().values().get(
            spreadsheetId=NETWORKING_SPREADSHEET_ID,
            range=f"{NETWORKING_SHEET}!A1:Z100",
        ).execute()

        values = result.get("values", [])
        if not values:
            return {"items": [], "action_needed": []}

        headers = [h.lower().strip() for h in values[0]]
        items = []
        action_needed = []

        for row in values[1:]:
            # Pad row to match headers
            padded = row + [""] * (len(headers) - len(row))
            item = dict(zip(headers, padded))
            items.append(item)

            # Flag items needing action: status is "To Do" or has upcoming deadline
            status = item.get("status", "").strip().lower()
            deadline = item.get("deadline", "").strip()
            if status == "to do" or (deadline and "todo" not in status.lower()):
                action_needed.append(item)

        return {"items": items, "action_needed": action_needed}
    except Exception as e:
        logger.error("Failed to read networking tracker: %s", e)
        return {"items": [], "action_needed": [], "error": str(e)}


def collect_pipeline_tracker(creds) -> list[dict]:
    """Read the job pipeline tracker from Google Sheets (supplements DB data)."""
    try:
        from googleapiclient.discovery import build

        service = build(
            "sheets", "v4", credentials=creds, cache_discovery=False,
        )
        result = service.spreadsheets().values().get(
            spreadsheetId=NETWORKING_SPREADSHEET_ID,
            range=f"{PIPELINE_SHEET}!A1:Z100",
        ).execute()

        values = result.get("values", [])
        if not values:
            return []

        headers = [h.lower().strip() for h in values[0]]
        items = []
        for row in values[1:]:
            padded = row + [""] * (len(headers) - len(row))
            item = dict(zip(headers, padded))
            # Only include non-closed items
            if item.get("status", "").strip().lower() != "closed":
                items.append(item)

        return items
    except Exception as e:
        logger.error("Failed to read pipeline tracker: %s", e)
        return []


def collect_homelab() -> dict:
    """Collect homelab journal data: past entries, present stats, future plans."""
    try:
        from .homelab import get_status, list_journal_entries
        from .config import HOMELAB_JOURNAL_DIR, HOMELAB_JOURNAL_INDEX, HOMELAB_JOURNAL_FILENAME

        # Past: last 3 journal entries
        entries_data = list_journal_entries(limit=3)
        past_entries = entries_data.get("entries", [])

        # Present: quick stats + skills in progress
        status = get_status()
        quick_stats = status.get("quick_stats", {})
        skills = status.get("skills", {})
        in_progress_skills = skills.get("in_progress", [])

        # Future: next steps from latest journal + priority queue from index
        next_steps = []
        if past_entries:
            latest = past_entries[0]
            link = latest.get("link", "")
            if link:
                # Try to read the latest journal file for ## Next Steps
                for pattern in [f"{link}.md", HOMELAB_JOURNAL_FILENAME.format(date=latest.get('date', ''))]:
                    journal_file = HOMELAB_JOURNAL_DIR / pattern
                    if journal_file.exists():
                        try:
                            content = journal_file.read_text(encoding="utf-8")
                            # Extract ## Next Steps section
                            ns_match = re.search(
                                r"##\s*Next\s*Steps\s*\n(.*?)(?=\n##|\Z)",
                                content, re.DOTALL | re.IGNORECASE,
                            )
                            if ns_match:
                                for line in ns_match.group(1).strip().splitlines():
                                    line = line.strip()
                                    if line.startswith(("-", "*", "1", "2", "3", "4", "5")):
                                        cleaned = re.sub(r"^[-*\d.)\s]+", "", line).strip()
                                        if cleaned:
                                            next_steps.append(cleaned)
                        except Exception:
                            pass
                        break

        # Priority queue from JOURNAL_INDEX.md
        planned_queue = []
        if HOMELAB_JOURNAL_INDEX.exists():
            try:
                idx_content = HOMELAB_JOURNAL_INDEX.read_text(encoding="utf-8")
                # Parse the planned priority queue table (| # | Project | Track | ... |)
                planned_match = re.search(
                    r"###\s*Planned.*?\n\|.*?\n\|[-\s|]+\n(.*?)(?=\n###|\n##|\n\*\*Backlog|\Z)",
                    idx_content, re.DOTALL | re.IGNORECASE,
                )
                if planned_match:
                    for line in planned_match.group(1).strip().splitlines():
                        line = line.strip()
                        if line.startswith("|"):
                            cols = [c.strip() for c in line.split("|")[1:-1]]
                            # cols[0] = #, cols[1] = Project name
                            if len(cols) >= 2 and cols[1]:
                                planned_queue.append(cols[1])
            except Exception:
                pass

        return {
            "past_entries": past_entries,
            "quick_stats": quick_stats,
            "in_progress_skills": in_progress_skills,
            "next_steps": next_steps[:5],
            "planned_queue": planned_queue[:3],
        }
    except Exception as e:
        logger.error("Failed to collect homelab data: %s", e)
        return {"error": str(e)}


def collect_calendar(creds) -> dict:
    """Collect today's calendar events from Google Calendar."""
    try:
        from googleapiclient.discovery import build

        service = build(
            "calendar", "v3", credentials=creds, cache_discovery=False,
        )

        # Today's events: midnight to midnight in local time
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        time_min = start_of_day.astimezone(timezone.utc).isoformat()
        time_max = end_of_day.astimezone(timezone.utc).isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for event in result.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            all_day = "date" in start and "dateTime" not in start

            events.append({
                "summary": event.get("summary", "(No title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "all_day": all_day,
            })

        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error("Failed to collect calendar events: %s", e)
        return {"events": [], "count": 0, "error": str(e)}


def collect_time_allocation() -> dict:
    """Collect time allocation data from Pulse sessions."""
    try:
        from .time_allocation import get_weekly_report
        return get_weekly_report()
    except Exception as e:
        logger.error("Failed to collect time allocation: %s", e)
        return {"domains": [], "total_actual": 0.0, "total_target": 0.0, "error": str(e)}


def collect_news() -> dict:
    """Collect top headlines from NewsAPI (general + tech)."""
    from .config import NEWSAPI_KEY, NEWSAPI_BASE_URL

    if not NEWSAPI_KEY:
        return {
            "general": [], "tech": [],
            "general_total": 0, "tech_total": 0,
            "note": "NewsAPI key not configured. Set NEWSAPI_KEY env var.",
        }

    try:
        import urllib.request
        import urllib.error
        import json as _json

        headers = {"X-Api-Key": NEWSAPI_KEY}

        def _fetch(category: str = "") -> dict:
            params = "country=us&pageSize=10"
            if category:
                params += f"&category={category}"
            url = f"{NEWSAPI_BASE_URL}/top-headlines?{params}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return _json.loads(resp.read().decode())

        general_resp = _fetch()
        tech_resp = _fetch("technology")

        def _parse_articles(resp: dict, limit: int = 3) -> tuple[list, int]:
            articles = resp.get("articles", [])
            total = resp.get("totalResults", len(articles))
            parsed = []
            for a in articles[:limit]:
                parsed.append({
                    "title": a.get("title", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "description": (a.get("description") or "")[:120],
                    "url": a.get("url", ""),
                })
            return parsed, total

        general, general_total = _parse_articles(general_resp)
        tech, tech_total = _parse_articles(tech_resp)

        return {
            "general": general, "tech": tech,
            "general_total": general_total, "tech_total": tech_total,
        }
    except Exception as e:
        logger.error("Failed to collect news: %s", e)
        return {
            "general": [], "tech": [],
            "general_total": 0, "tech_total": 0,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# HTML Email Builder
# ---------------------------------------------------------------------------

# Color scheme
COLORS = {
    "bg": "#f4f4f7",
    "card_bg": "#ffffff",
    "header_bg": "#1a1a2e",
    "header_text": "#e0e0ff",
    "accent": "#4a90d9",
    "text": "#333333",
    "text_light": "#666666",
    "border": "#e0e0e0",
    "critical": "#dc3545",
    "high": "#fd7e14",
    "medium": "#ffc107",
    "low": "#28a745",
    "overdue": "#dc3545",
    "success": "#28a745",
    "info": "#17a2b8",
}

# Priority badge colors
PRIORITY_COLORS = {
    "critical": COLORS["critical"],
    "high": COLORS["high"],
    "medium": COLORS["medium"],
    "low": COLORS["low"],
}

# Status badge colors for job apps
STATUS_COLORS = {
    "discovered": "#6c757d",
    "preparing": "#ffc107",
    "ready": "#17a2b8",
    "applied": "#4a90d9",
    "interviewing": "#fd7e14",
    "offered": "#28a745",
}


def _badge(text: str, color: str) -> str:
    """Generate an inline badge span."""
    return (
        f'<span style="display:inline-block; padding:2px 8px; '
        f'border-radius:3px; font-size:11px; font-weight:600; '
        f'color:#ffffff; background-color:{color}; '
        f'text-transform:uppercase;">{text}</span>'
    )


def _section_header(title: str, icon: str = "") -> str:
    """Generate a section header."""
    return f"""
    <tr>
      <td style="padding:24px 24px 8px 24px;">
        <h2 style="margin:0; font-size:18px; color:{COLORS['accent']};
                    border-bottom:2px solid {COLORS['accent']};
                    padding-bottom:6px;">
          {icon + '  ' if icon else ''}{title}
        </h2>
      </td>
    </tr>"""


def _build_tasks_section(data: dict) -> str:
    """Build the active tasks section HTML."""
    tasks = data.get("tasks", [])
    overdue = data.get("overdue_count", 0)

    if not tasks and "error" not in data:
        return _section_header("Active Tasks") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No active tasks. Nice work!</p>
        </td></tr>"""

    if "error" in data:
        return _section_header("Active Tasks") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['critical']};">Could not load tasks: {data['error']}</p>
        </td></tr>"""

    summary = f"<strong>{len(tasks)}</strong> active task{'s' if len(tasks) != 1 else ''}"
    if overdue > 0:
        summary += f" &middot; {_badge(f'{overdue} overdue', COLORS['overdue'])}"

    rows_html = ""
    for t in tasks:
        priority_color = PRIORITY_COLORS.get(t["priority"], COLORS["medium"])
        due_display = t["due_date"] or "--"
        if t["due_date"] and t["due_date"] < date.today().isoformat():
            due_display = f'<span style="color:{COLORS["overdue"]}; font-weight:600;">{t["due_date"]} (OVERDUE)</span>'

        project_cell = f' <span style="color:{COLORS["text_light"]}; font-size:12px;">[{t["project"]}]</span>' if t["project"] else ""

        rows_html += f"""
        <tr>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']};">
            {_badge(t['priority'], priority_color)}
            {_badge(t['status'].replace('_', ' '), COLORS['info'])}
            <strong style="margin-left:4px;">{t['title']}</strong>{project_cell}
          </td>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']}; text-align:right; white-space:nowrap; font-size:13px;">
            {due_display}
          </td>
        </tr>"""

    return _section_header("Active Tasks") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <p style="margin:0 0 12px 0; color:{COLORS['text_light']};">{summary}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        {rows_html}
      </table>
    </td></tr>"""


def _build_pipeline_section(db_data: dict, sheets_data: list[dict]) -> str:
    """Build the job application pipeline section."""
    pipeline = db_data.get("pipeline", {})
    active_apps = db_data.get("active_apps", [])

    # Merge: prefer Sheets data if DB is empty
    if not active_apps and sheets_data:
        # Use Sheets pipeline data
        rows_html = ""
        for item in sheets_data:
            status = item.get("status", "Unknown")
            status_color = STATUS_COLORS.get(status.lower(), "#6c757d")
            company = item.get("company", "Unknown")
            role = item.get("role", "Unknown")
            work_mode = item.get("work mode", "")
            url = item.get("url", "")

            title_html = f'<a href="{url}" style="color:{COLORS["accent"]}; text-decoration:none;">{role}</a>' if url else role

            rows_html += f"""
            <tr>
              <td style="padding:8px 0; border-bottom:1px solid {COLORS['border']};">
                {_badge(status, status_color)}<br/>
                <strong>{company}</strong> - {title_html}
                {(' <span style="font-size:12px; color:#666;">(' + work_mode + ')</span>') if work_mode else ''}
              </td>
            </tr>"""

        return _section_header("Job Pipeline") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="margin:0 0 12px 0; color:{COLORS['text_light']};">
            <strong>{len(sheets_data)}</strong> active application{'s' if len(sheets_data) != 1 else ''} (from tracker)
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
            {rows_html}
          </table>
        </td></tr>"""

    if not active_apps and not sheets_data:
        if "error" in db_data:
            return _section_header("Job Pipeline") + f"""
            <tr><td style="padding:4px 24px 16px 24px;">
              <p style="color:{COLORS['critical']};">Could not load pipeline: {db_data['error']}</p>
            </td></tr>"""
        return _section_header("Job Pipeline") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No active applications.</p>
        </td></tr>"""

    # Pipeline summary
    pipeline_parts = []
    for status_name in ["discovered", "preparing", "ready", "applied", "interviewing", "offered"]:
        cnt = pipeline.get(status_name, 0)
        if cnt > 0:
            color = STATUS_COLORS.get(status_name, "#6c757d")
            pipeline_parts.append(f"{_badge(f'{status_name}: {cnt}', color)}")

    pipeline_summary = " &nbsp; ".join(pipeline_parts) if pipeline_parts else "No active apps"

    rows_html = ""
    for a in active_apps:
        status_color = STATUS_COLORS.get(a["status"], "#6c757d")
        url = a.get("url", "")
        title_html = f'<a href="{url}" style="color:{COLORS["accent"]}; text-decoration:none;">{a["title"]}</a>' if url else a["title"]

        date_info = ""
        if a.get("applied_date"):
            date_info = f' <span style="font-size:12px; color:#666;">Applied: {a["applied_date"]}</span>'

        rows_html += f"""
        <tr>
          <td style="padding:8px 0; border-bottom:1px solid {COLORS['border']};">
            {_badge(a['status'], status_color)}<br/>
            <strong>{a['company']}</strong> - {title_html}
            {(' <span style="font-size:12px; color:#666;">(' + a['work_mode'] + ')</span>') if a.get('work_mode') else ''}
            {date_info}
          </td>
        </tr>"""

    return _section_header("Job Pipeline") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <p style="margin:0 0 12px 0;">{pipeline_summary}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        {rows_html}
      </table>
    </td></tr>"""


def _build_networking_section(data: dict) -> str:
    """Build the networking tracker section."""
    items = data.get("items", [])
    action_needed = data.get("action_needed", [])

    if "error" in data:
        return _section_header("Networking") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['critical']};">Could not load networking tracker: {data['error']}</p>
        </td></tr>"""

    if not items:
        return _section_header("Networking") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No networking items tracked.</p>
        </td></tr>"""

    rows_html = ""
    for item in items:
        org = item.get("organization", "Unknown")
        activity = item.get("activity", "")
        status = item.get("status", "")
        deadline = item.get("deadline", "")
        next_step = item.get("next step", "")
        link = item.get("link", "")
        completed = item.get("date completed", "")

        # Determine status color
        status_lower = status.strip().lower()
        if status_lower == "to do":
            status_badge = _badge(status, COLORS["high"])
        elif status_lower == "submitted":
            status_badge = _badge(status, COLORS["info"])
        elif status_lower in ("done", "completed"):
            status_badge = _badge(status, COLORS["success"])
        else:
            status_badge = _badge(status, "#6c757d")

        org_html = f'<a href="{link}" style="color:{COLORS["accent"]}; text-decoration:none;">{org}</a>' if link else org

        deadline_html = ""
        if deadline:
            deadline_html = f'<br/><span style="font-size:12px; color:{COLORS["text_light"]};">Deadline: {deadline}</span>'

        next_step_html = ""
        if next_step:
            next_step_html = f'<br/><span style="font-size:12px; color:{COLORS["text"]};">Next: {next_step}</span>'

        rows_html += f"""
        <tr>
          <td style="padding:8px 0; border-bottom:1px solid {COLORS['border']};">
            {status_badge}
            <strong style="margin-left:4px;">{org_html}</strong> - {activity}
            {deadline_html}
            {next_step_html}
          </td>
        </tr>"""

    action_count = sum(1 for i in items if i.get("status", "").strip().lower() == "to do")
    action_note = ""
    if action_count > 0:
        action_note = f" &middot; {_badge(f'{action_count} need action', COLORS['high'])}"

    return _section_header("Networking") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <p style="margin:0 0 12px 0; color:{COLORS['text_light']};">
        <strong>{len(items)}</strong> tracked item{'s' if len(items) != 1 else ''}{action_note}
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        {rows_html}
      </table>
    </td></tr>"""


def _build_forge_section(data: dict) -> str:
    """Build the SynapseForge study stats section."""
    if "error" in data:
        return _section_header("SynapseForge") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['critical']};">Could not load study stats: {data['error']}</p>
        </td></tr>"""

    total = data.get("total_concepts", 0)
    due = data.get("due_count", 0)
    avg = data.get("avg_mastery", 0.0)
    streak = data.get("current_streak", 0)
    reviews = data.get("total_reviews", 0)
    subjects = data.get("subjects", [])
    mastery_dist = data.get("mastery_distribution", {})

    if total == 0:
        return _section_header("SynapseForge") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No concepts tracked yet.</p>
        </td></tr>"""

    # Streak display
    streak_display = f"{streak} day{'s' if streak != 1 else ''}"
    streak_color = COLORS["success"] if streak > 0 else COLORS["text_light"]

    # Due concepts emphasis
    due_display = str(due)
    if due > 0:
        due_display = f'<span style="color:{COLORS["high"]}; font-weight:600;">{due}</span>'

    # Mastery bar (visual)
    mastery_pct = int(avg * 100)
    bar_color = COLORS["success"] if mastery_pct >= 60 else (COLORS["medium"] if mastery_pct >= 40 else COLORS["high"])

    # Mastery distribution table
    dist_html = ""
    if mastery_dist:
        dist_rows = ""
        for level, count in mastery_dist.items():
            if count > 0:
                dist_rows += f"""
                <tr>
                  <td style="padding:2px 8px 2px 0; font-size:12px; color:{COLORS['text_light']};">{level}</td>
                  <td style="padding:2px 0; font-size:12px; font-weight:600;">{count}</td>
                </tr>"""
        if dist_rows:
            dist_html = f"""
            <table cellpadding="0" cellspacing="0" style="margin-top:8px;">
              {dist_rows}
            </table>"""

    # Subjects
    subjects_html = ""
    if subjects:
        subject_parts = []
        for s in subjects:
            subject_parts.append(f'{s["short_name"]} ({s["concept_count"]} concepts)')
        subjects_html = f"""
        <p style="margin:8px 0 0 0; font-size:13px; color:{COLORS['text_light']};">
          Subjects: {" | ".join(subject_parts)}
        </p>"""

    return _section_header("SynapseForge") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        <tr>
          <td width="25%" style="text-align:center; padding:8px;">
            <div style="font-size:24px; font-weight:700; color:{COLORS['accent']};">{total}</div>
            <div style="font-size:11px; color:{COLORS['text_light']}; text-transform:uppercase;">Concepts</div>
          </td>
          <td width="25%" style="text-align:center; padding:8px;">
            <div style="font-size:24px; font-weight:700;">{due_display}</div>
            <div style="font-size:11px; color:{COLORS['text_light']}; text-transform:uppercase;">Due Today</div>
          </td>
          <td width="25%" style="text-align:center; padding:8px;">
            <div style="font-size:24px; font-weight:700; color:{streak_color};">{streak_display}</div>
            <div style="font-size:11px; color:{COLORS['text_light']}; text-transform:uppercase;">Streak</div>
          </td>
          <td width="25%" style="text-align:center; padding:8px;">
            <div style="font-size:24px; font-weight:700;">{reviews}</div>
            <div style="font-size:11px; color:{COLORS['text_light']}; text-transform:uppercase;">Reviews</div>
          </td>
        </tr>
      </table>
      <!-- Mastery bar -->
      <div style="margin:8px 0 4px 0;">
        <span style="font-size:13px; color:{COLORS['text_light']};">Average Mastery: <strong>{mastery_pct}%</strong></span>
        <div style="background:{COLORS['border']}; border-radius:4px; height:8px; margin-top:4px;">
          <div style="background:{bar_color}; border-radius:4px; height:8px; width:{mastery_pct}%;"></div>
        </div>
      </div>
      {dist_html}
      {subjects_html}
    </td></tr>"""


def _build_deadlines_section(deadlines: list[dict]) -> str:
    """Build the upcoming deadlines section."""
    if not deadlines:
        return _section_header("Upcoming Deadlines") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No deadlines in the next 7 days.</p>
        </td></tr>"""

    rows_html = ""
    for d in deadlines:
        priority_color = PRIORITY_COLORS.get(d["priority"], COLORS["medium"])
        date_color = COLORS["overdue"] if d["overdue"] else COLORS["text"]
        overdue_label = " (OVERDUE)" if d["overdue"] else ""

        rows_html += f"""
        <tr>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']};">
            {_badge(d['priority'], priority_color)}
            <strong style="margin-left:4px;">{d['title']}</strong>
            {(' <span style="font-size:12px; color:#666;">[' + d['project'] + ']</span>') if d['project'] else ''}
          </td>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']}; text-align:right; white-space:nowrap;">
            <span style="color:{date_color}; font-weight:{'600' if d['overdue'] else '400'};">
              {d['due_date']}{overdue_label}
            </span>
          </td>
        </tr>"""

    return _section_header("Upcoming Deadlines") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        {rows_html}
      </table>
    </td></tr>"""


def _build_homelab_section(data: dict) -> str:
    """Build the homelab journal section: Past / Present / Future."""
    if "error" in data:
        return _section_header("Homelab") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['text_light']}; font-style:italic;">
            Homelab data unavailable: {data['error']}
          </p>
        </td></tr>"""

    past = data.get("past_entries", [])
    stats = data.get("quick_stats", {})
    skills = data.get("in_progress_skills", [])
    next_steps = data.get("next_steps", [])
    planned = data.get("planned_queue", [])

    # Past: recent entries mini table
    past_html = ""
    if past:
        rows = ""
        for entry in past:
            rows += f"""
            <tr>
              <td style="padding:2px 8px 2px 0; font-size:12px; color:{COLORS['text_light']}; white-space:nowrap;">
                {entry.get('date', '')}
              </td>
              <td style="padding:2px 0; font-size:12px;">{entry.get('title', '')}</td>
            </tr>"""
        past_html = f"""
        <div style="margin-bottom:12px;">
          <strong style="font-size:13px; color:{COLORS['text']};">Past</strong>
          <table cellpadding="0" cellspacing="0" style="margin-top:4px;">{rows}</table>
        </div>"""
    else:
        past_html = """
        <div style="margin-bottom:12px;">
          <strong style="font-size:13px;">Past</strong>
          <p style="font-size:12px; color:#666; margin:4px 0;">No journal entries yet.</p>
        </div>"""

    # Present: stats badges + skills
    stats_badges = ""
    total_sessions = stats.get("Total Lab Sessions", stats.get("total_sessions", ""))
    latest_entry = stats.get("Latest Entry", stats.get("latest_entry", ""))
    if total_sessions:
        stats_badges += _badge(f"{total_sessions} sessions", COLORS["info"]) + " "
    if latest_entry:
        stats_badges += _badge(f"Latest: {latest_entry}", COLORS["success"]) + " "

    skills_html = ""
    if skills:
        skills_html = f'<br/><span style="font-size:12px; color:{COLORS["text_light"]};">In progress: {", ".join(skills)}</span>'

    present_html = f"""
    <div style="margin-bottom:12px;">
      <strong style="font-size:13px; color:{COLORS['text']};">Present</strong>
      <div style="margin-top:4px;">{stats_badges}{skills_html}</div>
    </div>"""

    # Future: planned queue + next steps
    future_items = ""
    if planned:
        for i, item in enumerate(planned, 1):
            future_items += f"""
            <div style="margin:2px 0; font-size:12px;">
              {_badge(f'#{i}', COLORS['accent'])}
              <span style="margin-left:4px;">{item}</span>
            </div>"""

    next_items = ""
    if next_steps:
        for step in next_steps:
            next_items += f"""
            <div style="margin:2px 0; font-size:12px;">
              {_badge('next', COLORS['high'])}
              <span style="margin-left:4px;">{step}</span>
            </div>"""

    future_html = ""
    if future_items or next_items:
        future_html = f"""
        <div>
          <strong style="font-size:13px; color:{COLORS['text']};">Future</strong>
          <div style="margin-top:4px;">{future_items}{next_items}</div>
        </div>"""

    return _section_header("Homelab") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      {past_html}
      {present_html}
      {future_html}
    </td></tr>"""


def _build_calendar_section(data: dict) -> str:
    """Build the calendar events section."""
    events = data.get("events", [])
    count = data.get("count", 0)

    if "error" in data:
        return _section_header("Today's Calendar") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['critical']};">Could not load calendar: {data['error']}</p>
        </td></tr>"""

    if not events:
        return _section_header("Today's Calendar") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No events scheduled today.</p>
        </td></tr>"""

    rows_html = ""
    # All-day events first
    all_day = [e for e in events if e.get("all_day")]
    timed = [e for e in events if not e.get("all_day")]

    for e in all_day:
        location_html = f' <span style="font-size:11px; color:{COLORS["text_light"]};">[{e["location"]}]</span>' if e.get("location") else ""
        rows_html += f"""
        <tr>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']};">
            {_badge('All day', COLORS['accent'])}
            <strong style="margin-left:4px;">{e['summary']}</strong>{location_html}
          </td>
        </tr>"""

    for e in timed:
        try:
            start_dt = datetime.fromisoformat(e["start"])
            end_dt = datetime.fromisoformat(e["end"])
            time_str = f"{start_dt.strftime('%I:%M %p').lstrip('0')} - {end_dt.strftime('%I:%M %p').lstrip('0')}"
        except Exception:
            time_str = e.get("start", "")

        location_html = f' <span style="font-size:11px; color:{COLORS["text_light"]};">[{e["location"]}]</span>' if e.get("location") else ""
        rows_html += f"""
        <tr>
          <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']};">
            <span style="font-size:12px; color:{COLORS['text_light']}; margin-right:8px;">{time_str}</span>
            <strong>{e['summary']}</strong>{location_html}
          </td>
        </tr>"""

    return _section_header("Today's Calendar") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      <p style="margin:0 0 8px 0; color:{COLORS['text_light']};">
        {_badge(f'{count} event{"s" if count != 1 else ""}', COLORS['accent'])}
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
        {rows_html}
      </table>
    </td></tr>"""


def _build_news_section(data: dict) -> str:
    """Build the news headlines section."""
    general = data.get("general", [])
    tech = data.get("tech", [])
    general_total = data.get("general_total", 0)
    tech_total = data.get("tech_total", 0)
    note = data.get("note", "")

    if note:
        return _section_header("News") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['text_light']}; font-size:12px; font-style:italic;">{note}</p>
        </td></tr>"""

    if "error" in data:
        return _section_header("News") + f"""
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:{COLORS['critical']};">Could not load news: {data['error']}</p>
        </td></tr>"""

    if not general and not tech:
        return _section_header("News") + """
        <tr><td style="padding:4px 24px 16px 24px;">
          <p style="color:#666; font-style:italic;">No news available.</p>
        </td></tr>"""

    def _article_rows(articles: list, total: int) -> str:
        html = ""
        for a in articles:
            source_badge = _badge(a.get("source", ""), "#6c757d") if a.get("source") else ""
            title = a.get("title", "")
            url = a.get("url", "")
            desc = a.get("description", "")
            title_html = f'<a href="{url}" style="color:{COLORS["accent"]}; text-decoration:none;">{title}</a>' if url else title
            desc_html = f'<br/><span style="font-size:11px; color:{COLORS["text_light"]};">{desc}</span>' if desc else ""

            html += f"""
            <tr>
              <td style="padding:6px 0; border-bottom:1px solid {COLORS['border']};">
                {source_badge}
                <span style="margin-left:4px;">{title_html}</span>
                {desc_html}
              </td>
            </tr>"""

        remaining = total - len(articles)
        if remaining > 0:
            html += f"""
            <tr>
              <td style="padding:4px 0; font-size:11px; color:{COLORS['text_light']};">
                ...and {remaining} more
              </td>
            </tr>"""
        return html

    general_html = ""
    if general:
        general_html = f"""
        <div style="margin-bottom:12px;">
          <strong style="font-size:13px; color:{COLORS['text']};">Top Stories</strong>
          <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; margin-top:4px;">
            {_article_rows(general, general_total)}
          </table>
        </div>"""

    tech_html = ""
    if tech:
        tech_html = f"""
        <div>
          <strong style="font-size:13px; color:{COLORS['text']};">Tech News</strong>
          <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; margin-top:4px;">
            {_article_rows(tech, tech_total)}
          </table>
        </div>"""

    return _section_header("News") + f"""
    <tr><td style="padding:4px 24px 16px 24px;">
      {general_html}
      {tech_html}
    </td></tr>"""


def _build_domains_section(data: dict) -> str:
    """Build the Life Domains goals section for the daily briefing."""
    if not data or not data.get("domains"):
        return ""

    rows = []
    for domain in data["domains"][:6]:  # Top 6 domains
        progress_pct = int(domain.get("progress", 0) * 100)
        bar_color = COLORS["success"] if progress_pct >= 60 else (
            COLORS["medium"] if progress_pct >= 30 else COLORS["critical"]
        )
        active = domain.get("active_goal_count", 0)

        rows.append(f"""
          <tr>
            <td style="padding:8px 12px; border-bottom:1px solid {COLORS['border']};">
              <strong>{domain['name']}</strong>
            </td>
            <td style="padding:8px 12px; border-bottom:1px solid {COLORS['border']}; text-align:center;">
              {active} goals
            </td>
            <td style="padding:8px 12px; border-bottom:1px solid {COLORS['border']}; width:120px;">
              <div style="background:#eee; border-radius:4px; height:12px; overflow:hidden;">
                <div style="background:{bar_color}; height:100%; width:{progress_pct}%;"></div>
              </div>
              <span style="font-size:11px; color:{COLORS['text_light']};">{progress_pct}%</span>
            </td>
          </tr>""")

    if not rows:
        return ""

    return f"""
          <tr>
            <td style="padding:20px 24px;">
              <h2 style="margin:0 0 12px 0; font-size:18px; color:{COLORS['text']};
                          border-bottom:2px solid {COLORS['accent']}; padding-bottom:8px;">
                Life Domains
              </h2>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr style="background-color:#f8f9fa;">
                  <th style="padding:6px 12px; text-align:left; font-size:13px;">Domain</th>
                  <th style="padding:6px 12px; text-align:center; font-size:13px;">Active</th>
                  <th style="padding:6px 12px; text-align:left; font-size:13px;">Progress</th>
                </tr>
                {"".join(rows)}
              </table>
            </td>
          </tr>"""


def build_email_html(
    tasks_data: dict,
    pipeline_data: dict,
    sheets_pipeline: list[dict],
    networking_data: dict,
    forge_data: dict,
    deadlines: list[dict],
    calendar_data: Optional[dict] = None,
    homelab_data: Optional[dict] = None,
    news_data: Optional[dict] = None,
    domains_data: Optional[dict] = None,
) -> str:
    """Compose the full HTML email."""
    today = date.today()
    day_name = today.strftime("%A")
    date_display = today.strftime("%B %d, %Y")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    sections = []
    if calendar_data is not None:
        sections.append(_build_calendar_section(calendar_data))
    sections.append(_build_deadlines_section(deadlines))
    sections.append(_build_tasks_section(tasks_data))
    if domains_data is not None:
        sections.append(_build_domains_section(domains_data))
    if homelab_data is not None:
        sections.append(_build_homelab_section(homelab_data))
    sections.append(_build_pipeline_section(pipeline_data, sheets_pipeline))
    sections.append(_build_networking_section(networking_data))
    sections.append(_build_forge_section(forge_data))
    if news_data is not None:
        sections.append(_build_news_section(news_data))

    sections_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>JayBrain Daily Briefing</title>
</head>
<body style="margin:0; padding:0; background-color:{COLORS['bg']}; font-family:Segoe UI, Roboto, Helvetica, Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:{COLORS['bg']};">
    <tr>
      <td align="center" style="padding:24px 8px;">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background-color:{COLORS['card_bg']}; border-radius:8px;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:{COLORS['header_bg']}; padding:24px;
                        border-radius:8px 8px 0 0; text-align:center;">
              <h1 style="margin:0; font-size:24px; color:{COLORS['header_text']};
                          letter-spacing:1px;">
                JayBrain Daily Briefing
              </h1>
              <p style="margin:6px 0 0 0; font-size:14px; color:#9999bb;">
                {day_name}, {date_display}
              </p>
            </td>
          </tr>

          {sections_html}

          <!-- Footer -->
          <tr>
            <td style="padding:20px 24px; text-align:center;
                        border-top:1px solid {COLORS['border']};
                        background-color:#fafafa; border-radius:0 0 8px 8px;">
              <p style="margin:0; font-size:12px; color:{COLORS['text_light']};">
                Generated by <strong>JayBrain</strong> on {generated_at}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email Sender
# ---------------------------------------------------------------------------


def send_email(subject: str, html_body: str, to: str, creds=None) -> dict | bool:
    """Send an HTML email via the Gmail API using OAuth credentials.

    Uses the same OAuth token as Google Docs/Sheets -- no app password needed.
    Returns a dict with ``status`` and ``message_id`` on success, or False on
    failure (for backwards compatibility with callers that check truthiness).
    """
    if creds is None:
        creds = _get_google_credentials()
    if creds is None:
        logger.error("No Google credentials available for sending email.")
        return False

    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # Strip HTML tags for the plain-text fallback
        plain_text = re.sub(r"<[^>]+>", "", html_body).strip() or subject

        message = MIMEMultipart("alternative")
        message["From"] = RECIPIENT_EMAIL
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(plain_text, "plain"))
        message.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        result = service.users().messages().send(
            userId="me", body={"raw": raw},
        ).execute()

        msg_id = result.get("id", "")
        logger.info("Email sent successfully to %s via Gmail API (id=%s)", to, msg_id)
        return {"status": "sent", "message_id": msg_id}
    except Exception as e:
        logger.error("Failed to send email: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_briefing() -> dict:
    """Collect all data, build the email, and send it.

    Returns a dict with status and details, suitable for both CLI and MCP use.
    """
    logger.info("Starting JayBrain Daily Briefing")

    # --- Collect data (each section handles its own errors) ---
    conn = _get_db_connection()

    if conn:
        tasks_data = collect_tasks(conn)
        pipeline_data = collect_job_pipeline(conn)
        forge_data = collect_forge_stats(conn)
        deadlines = collect_upcoming_deadlines(conn)
    else:
        tasks_data = {"tasks": [], "overdue_count": 0, "error": "Database unavailable"}
        pipeline_data = {"pipeline": {}, "active_apps": [], "error": "Database unavailable"}
        forge_data = {
            "total_concepts": 0, "due_count": 0, "avg_mastery": 0.0,
            "mastery_distribution": {}, "current_streak": 0,
            "total_reviews": 0, "subjects": [], "error": "Database unavailable",
        }
        deadlines = []

    # Google credentials (shared across Sheets reads, Calendar, and Gmail send)
    google_creds = _get_google_credentials()
    networking_data = collect_networking_tracker(google_creds) if google_creds else {"items": [], "action_needed": [], "error": "No Google credentials"}
    sheets_pipeline = collect_pipeline_tracker(google_creds) if google_creds else []

    # New sections: calendar, homelab, news
    calendar_data = collect_calendar(google_creds) if google_creds else {"events": [], "count": 0, "error": "No Google credentials"}
    homelab_data = collect_homelab()
    news_data = collect_news()

    # Life domains goal data
    domains_data = None
    try:
        from .life_domains import get_domain_overview
        domains_data = get_domain_overview()
    except Exception as e:
        logger.debug("Life domains data unavailable: %s", e)

    if conn:
        conn.close()

    # --- Build email ---
    today_str = date.today().strftime("%b %d, %Y")
    subject = f"JayBrain Briefing - {today_str}"

    html = build_email_html(
        tasks_data=tasks_data,
        pipeline_data=pipeline_data,
        sheets_pipeline=sheets_pipeline,
        networking_data=networking_data,
        forge_data=forge_data,
        deadlines=deadlines,
        calendar_data=calendar_data,
        homelab_data=homelab_data,
        news_data=news_data,
        domains_data=domains_data,
    )

    # --- Send via Gmail API ---
    success = send_email(subject, html, RECIPIENT_EMAIL, creds=google_creds)

    if success:
        logger.info("Daily briefing sent successfully")
        return {
            "status": "sent",
            "recipient": RECIPIENT_EMAIL,
            "date": today_str,
            "sections": {
                "calendar_events": calendar_data.get("count", 0),
                "deadlines": len(deadlines),
                "tasks": len(tasks_data.get("tasks", [])),
                "homelab_entries": len(homelab_data.get("past_entries", [])),
                "active_apps": len(pipeline_data.get("active_apps", [])),
                "networking_items": len(networking_data.get("items", [])),
                "forge_concepts": forge_data.get("total_concepts", 0),
                "news_general": len(news_data.get("general", [])),
                "news_tech": len(news_data.get("tech", [])),
            },
        }
    else:
        return {"status": "failed", "error": "Email send failed. Check logs."}


# ---------------------------------------------------------------------------
# Telegram Briefing
# ---------------------------------------------------------------------------


def _fmt_section(title: str, lines: list[str]) -> str:
    """Format a section with a title and indented lines. Omits if no lines."""
    if not lines:
        return ""
    body = "\n".join(f"  {line}" for line in lines)
    return f"\n{title}\n{body}"


def format_telegram_briefing(
    tasks_data: dict,
    pipeline_data: dict,
    forge_data: dict,
    deadlines: list[dict],
    calendar_data: Optional[dict] = None,
    homelab_data: Optional[dict] = None,
    domains_data: Optional[dict] = None,
    time_data: Optional[dict] = None,
    network_data: Optional[dict] = None,
) -> str:
    """Format collected data as a plain-text Telegram message.

    Sections with no data are omitted. Keeps the message concise for
    quick morning scanning on mobile.
    """
    today = date.today()
    day_name = today.strftime("%A")
    date_display = today.strftime("%b %d, %Y")
    parts = [f"JayBrain Daily Briefing -- {day_name}, {date_display}"]

    # Calendar
    if calendar_data and calendar_data.get("events"):
        events = calendar_data["events"]
        lines = []
        for e in events:
            if e.get("all_day"):
                lines.append(f"[All day] {e['summary']}")
            else:
                try:
                    start_dt = datetime.fromisoformat(e["start"])
                    time_str = start_dt.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    time_str = e.get("start", "")
                loc = f" [{e['location']}]" if e.get("location") else ""
                lines.append(f"{time_str} - {e['summary']}{loc}")
        parts.append(_fmt_section(f"CALENDAR ({len(events)} event{'s' if len(events) != 1 else ''})", lines))

    # Exam countdown
    from .config import SECURITY_PLUS_EXAM_DATE
    if SECURITY_PLUS_EXAM_DATE:
        try:
            exam_date = datetime.strptime(SECURITY_PLUS_EXAM_DATE, "%Y-%m-%d")
            days_left = (exam_date.date() - today).days
            if 0 <= days_left <= 14:
                avg = forge_data.get("avg_mastery", 0.0)
                parts.append(_fmt_section("EXAM COUNTDOWN", [
                    f"Security+ in {days_left} day{'s' if days_left != 1 else ''} | Avg mastery: {int(avg * 100)}%"
                ]))
        except ValueError:
            pass

    # Deadlines
    if deadlines:
        lines = []
        for d in deadlines:
            prefix = "[OVERDUE] " if d.get("overdue") else ""
            lines.append(f"{prefix}{d['title']} ({d['due_date']})")
        parts.append(_fmt_section(f"DEADLINES ({len(deadlines)})", lines))

    # Tasks
    tasks = tasks_data.get("tasks", [])
    overdue = tasks_data.get("overdue_count", 0)
    if tasks:
        count_str = f"{len(tasks)} active"
        if overdue:
            count_str += f", {overdue} overdue"
        lines = []
        for t in tasks[:8]:
            lines.append(f"[{t['priority']}] {t['title']}")
        if len(tasks) > 8:
            lines.append(f"...and {len(tasks) - 8} more")
        parts.append(_fmt_section(f"TASKS ({count_str})", lines))

    # Time allocation
    if time_data and time_data.get("domains"):
        lines = []
        for d in time_data["domains"]:
            if d["target_hours"] > 0 or d["actual_hours"] > 0:
                # Shorten long domain names
                name = d["name"].split(" -- ")[0].split(" (")[0]
                status_tag = ""
                if d["status"] == "under":
                    status_tag = " << under"
                elif d["status"] == "over":
                    status_tag = " >> over"
                lines.append(
                    f"{name}: {d['actual_hours']}h / {d['target_hours']}h ({d['pct']:.0f}%){status_tag}"
                )
        total_actual = time_data.get("total_actual", 0)
        total_target = time_data.get("total_target", 0)
        if total_target > 0:
            lines.append(f"Total: {total_actual}h / {total_target}h")
        parts.append(_fmt_section(f"TIME ALLOCATION ({time_data.get('period_days', 7)}-day)", lines))

    # Life domains
    if domains_data and domains_data.get("domains"):
        lines = []
        for dom in domains_data["domains"][:6]:
            active = dom.get("active_goal_count", 0)
            progress = int(dom.get("progress", 0) * 100)
            name = dom["name"].split(" -- ")[0].split(" (")[0]
            if active > 0:
                lines.append(f"{name} ({active} goals, {progress}%)")
        if lines:
            parts.append(_fmt_section("LIFE DOMAINS", lines))

    # Network decay
    if network_data and network_data.get("stale_count", 0) > 0:
        stale = [c for c in network_data.get("contacts", []) if c.get("overdue_by", 0) > 0]
        if stale:
            lines = []
            for c in stale[:5]:
                company_str = f" ({c['company']})" if c.get("company") else ""
                lines.append(f"{c['name']}{company_str} -- {c['overdue_by']}d overdue")
            if len(stale) > 5:
                lines.append(f"...and {len(stale) - 5} more")
            parts.append(_fmt_section(f"NETWORK ({len(stale)} stale)", lines))

    # Job pipeline
    pipeline = pipeline_data.get("pipeline", {})
    active_apps = pipeline_data.get("active_apps", [])
    if pipeline or active_apps:
        lines = []
        status_counts = []
        for status_name in ["discovered", "preparing", "ready", "applied", "interviewing", "offered"]:
            cnt = pipeline.get(status_name, 0)
            if cnt > 0:
                status_counts.append(f"{cnt} {status_name}")
        if status_counts:
            lines.append(" | ".join(status_counts))
        for a in active_apps[:3]:
            lines.append(f"{a['company']} - {a['title']} [{a['status']}]")
        if lines:
            parts.append(_fmt_section("JOB PIPELINE", lines))

    # Homelab
    if homelab_data and not homelab_data.get("error"):
        lines = []
        past = homelab_data.get("past_entries", [])
        if past:
            latest = past[0]
            lines.append(f"Last: {latest.get('date', '?')} -- {latest.get('title', '?')}")
        next_steps = homelab_data.get("next_steps", [])
        if next_steps:
            lines.append(f"Next: {next_steps[0]}")
        if lines:
            parts.append(_fmt_section("HOMELAB", lines))

    # SynapseForge (brief)
    if forge_data.get("total_concepts", 0) > 0:
        due = forge_data.get("due_count", 0)
        streak = forge_data.get("current_streak", 0)
        avg = forge_data.get("avg_mastery", 0.0)
        lines = [
            f"{forge_data['total_concepts']} concepts | {due} due | Streak: {streak}d | Mastery: {int(avg * 100)}%"
        ]
        parts.append(_fmt_section("SYNAPSEFORGE", lines))

    return "\n".join(p for p in parts if p)


def run_telegram_briefing() -> dict:
    """Collect all data, format for Telegram, and send.

    This is the daemon entry point -- runs daily at the configured hour.
    """
    logger.info("Starting Telegram daily briefing")

    conn = _get_db_connection()

    if conn:
        tasks_data = collect_tasks(conn)
        pipeline_data = collect_job_pipeline(conn)
        forge_data = collect_forge_stats(conn)
        deadlines = collect_upcoming_deadlines(conn)
    else:
        tasks_data = {"tasks": [], "overdue_count": 0, "error": "Database unavailable"}
        pipeline_data = {"pipeline": {}, "active_apps": []}
        forge_data = {"total_concepts": 0, "due_count": 0, "avg_mastery": 0.0,
                      "mastery_distribution": {}, "current_streak": 0,
                      "total_reviews": 0, "subjects": []}
        deadlines = []

    google_creds = _get_google_credentials()
    calendar_data = collect_calendar(google_creds) if google_creds else None
    homelab_data = collect_homelab()
    time_data = collect_time_allocation()

    domains_data = None
    try:
        from .life_domains import get_domain_overview
        domains_data = get_domain_overview()
    except Exception as e:
        logger.debug("Life domains data unavailable: %s", e)

    network_data = None
    try:
        from .network_decay import get_network_health
        network_data = get_network_health()
    except Exception as e:
        logger.debug("Network decay data unavailable: %s", e)

    if conn:
        conn.close()

    message = format_telegram_briefing(
        tasks_data=tasks_data,
        pipeline_data=pipeline_data,
        forge_data=forge_data,
        deadlines=deadlines,
        calendar_data=calendar_data,
        homelab_data=homelab_data,
        domains_data=domains_data,
        time_data=time_data,
        network_data=network_data,
    )

    try:
        from .telegram import send_telegram_message
        result = send_telegram_message(message, caller="daemon_daily_briefing")
        logger.info("Telegram briefing sent: %s", result.get("status", "unknown"))
        return {"status": "sent", "length": len(message), "telegram": result}
    except Exception as e:
        logger.error("Failed to send Telegram briefing: %s", e, exc_info=True)
        return {"status": "failed", "error": str(e)}


def main() -> int:
    """Run the daily briefing: collect data, build email, send."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    result = run_briefing()
    if result.get("status") == "sent":
        return 0
    else:
        logger.error("Briefing failed: %s", result.get("error", "unknown"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
