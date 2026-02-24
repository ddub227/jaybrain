"""Life Domains goal tracking engine.

Structured goal tracking synced from a Google Doc, with auto-metrics from
existing JayBrain data (forge readiness, app counts), conflict detection,
and priority stack computation.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import (
    LIFE_DOMAINS_AVAILABLE_HOURS_WEEK,
    LIFE_DOMAINS_DOC_ID,
    SECURITY_PLUS_EXAM_DATE,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Domain / Goal CRUD
# ---------------------------------------------------------------------------

def get_domain_overview() -> dict:
    """Get all domains with their goals and aggregate progress."""
    conn = get_connection()
    try:
        domains = conn.execute(
            "SELECT * FROM life_domains ORDER BY priority DESC"
        ).fetchall()

        result = []
        for d in domains:
            goals = conn.execute(
                """SELECT * FROM life_goals
                WHERE domain_id = ? ORDER BY status, target_date""",
                (d["id"],),
            ).fetchall()

            goal_list = []
            for g in goals:
                sub_goals = conn.execute(
                    "SELECT * FROM life_sub_goals WHERE goal_id = ?",
                    (g["id"],),
                ).fetchall()
                goal_list.append({
                    "id": g["id"],
                    "title": g["title"],
                    "status": g["status"],
                    "progress": g["progress"],
                    "target_date": g["target_date"],
                    "auto_metric_source": g["auto_metric_source"],
                    "sub_goals": [
                        {
                            "id": s["id"],
                            "title": s["title"],
                            "status": s["status"],
                            "progress": s["progress"],
                        }
                        for s in sub_goals
                    ],
                })

            # Aggregate domain progress
            active_goals = [g for g in goal_list if g["status"] == "active"]
            domain_progress = (
                sum(g["progress"] for g in active_goals) / len(active_goals)
                if active_goals
                else 0.0
            )

            result.append({
                "id": d["id"],
                "name": d["name"],
                "description": d["description"],
                "priority": d["priority"],
                "hours_per_week": d["hours_per_week"],
                "progress": round(domain_progress, 2),
                "goals": goal_list,
                "goal_count": len(goal_list),
                "active_goal_count": len(active_goals),
            })

        return {"domains": result, "total_domains": len(result)}
    finally:
        conn.close()


def get_goal_detail(goal_id: str) -> dict:
    """Get detailed info about a specific goal including metrics and deps."""
    conn = get_connection()
    try:
        goal = conn.execute(
            "SELECT * FROM life_goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        sub_goals = conn.execute(
            "SELECT * FROM life_sub_goals WHERE goal_id = ?", (goal_id,)
        ).fetchall()

        metrics = conn.execute(
            """SELECT * FROM life_goal_metrics
            WHERE goal_id = ? ORDER BY recorded_at DESC LIMIT 10""",
            (goal_id,),
        ).fetchall()

        deps = conn.execute(
            """SELECT g.id, g.title, g.status, g.progress
            FROM life_goal_dependencies d
            JOIN life_goals g ON g.id = d.depends_on_goal_id
            WHERE d.goal_id = ?""",
            (goal_id,),
        ).fetchall()

        domain = conn.execute(
            "SELECT name FROM life_domains WHERE id = ?", (goal["domain_id"],)
        ).fetchone()

        return {
            "id": goal["id"],
            "title": goal["title"],
            "description": goal["description"],
            "domain": domain["name"] if domain else "",
            "status": goal["status"],
            "progress": goal["progress"],
            "target_date": goal["target_date"],
            "auto_metric_source": goal["auto_metric_source"],
            "sub_goals": [
                {"id": s["id"], "title": s["title"], "status": s["status"], "progress": s["progress"]}
                for s in sub_goals
            ],
            "recent_metrics": [
                {"name": m["metric_name"], "value": m["metric_value"], "source": m["source"], "at": m["recorded_at"]}
                for m in metrics
            ],
            "dependencies": [
                {"id": d["id"], "title": d["title"], "status": d["status"], "progress": d["progress"]}
                for d in deps
            ],
        }
    finally:
        conn.close()


def update_goal_progress(goal_id: str, progress: float, note: str = "") -> dict:
    """Update a goal's progress and optionally record a metric."""
    progress = max(0.0, min(1.0, progress))
    now = now_iso()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE life_goals SET progress = ?, updated_at = ? WHERE id = ?",
            (progress, now, goal_id),
        )
        if cursor.rowcount == 0:
            return {"error": f"Goal {goal_id} not found"}

        # Record metric
        conn.execute(
            """INSERT INTO life_goal_metrics
            (id, goal_id, metric_name, metric_value, source, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (_generate_id(), goal_id, note or "progress_update", progress, "manual", now),
        )
        conn.commit()
        return {"status": "updated", "goal_id": goal_id, "progress": progress}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Google Doc Sync
# ---------------------------------------------------------------------------

def _parse_domains_doc(text: str) -> list[dict]:
    """Parse the Life Domains Google Doc text into structured domain/goal data.

    Handles both markdown (# headers, - bullets) and Google Docs plain text
    export format (bare "Domain N:" headers, numbered sub-goals, * bullets).

    Section state machine:
      "idle"      -- before any goal-producing section; bullets ignored
      "sub_goals" -- inside Sub-goals: section; bullets/numbers -> sub-goals
      "goals"     -- inside a markdown-only freeform section; bullets -> goals
    """
    domains = []
    current_domain = None
    current_goal = None
    # "idle" = skip bullets, "sub_goals" = capture sub-goals, "goals" = capture goals
    section = "idle"

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        if not raw_line.strip():
            continue

        # Indented bullet -> sub-goal (check BEFORE stripping to detect indent)
        sub_match = re.match(r'^(\s{2,}|\t+)[-*]\s+(.+)', raw_line)
        if sub_match and current_goal and current_domain:
            current_goal["sub_goals"].append(sub_match.group(2).strip())
            continue

        line = raw_line.strip()

        # Skip horizontal rules (Google Docs exports these as underscores)
        if re.match(r'^[_\-=]{3,}$', line):
            continue

        # Skip metadata lines
        if line.startswith(("\ufeff", "Last updated:", "Status:")):
            continue

        # Domain header: markdown "## Domain..." or plain "Domain N: ..."
        md_header = re.match(r'^#{1,2}\s+(?:Domain\s+\d+:\s*)?(.+)', line)
        plain_header = re.match(r'^Domain\s+\d+:\s*(.+)', line) if not md_header else None
        header_match = md_header or plain_header
        if header_match:
            name = header_match.group(1).strip()
            # Skip meta-headers and non-domain sections
            lower = name.lower()
            if any(skip in lower for skip in (
                "life domains", "table of contents", "overview",
                "goal priority stack", "goal conflicts",
            )):
                current_domain = None
                current_goal = None
                section = "idle"
                continue
            current_domain = {
                "name": name,
                "description": "",
                "goals": [],
            }
            domains.append(current_domain)
            current_goal = None
            # Markdown format: bullets are freeform goals
            # Google Doc plain text: only Primary Goal/Sub-goals produce goals
            section = "goals" if md_header else "idle"
            continue

        if not current_domain:
            continue

        # "Primary Goal:" line -> create the domain's main goal
        pg_match = re.match(r'^(?:\*\*)?Primary Goal:?\*?\*?\s*(.+)', line)
        if pg_match:
            goal_text = pg_match.group(1).strip()
            date_match = re.search(r'\(by\s+(.+?)\)', goal_text)
            target_date = date_match.group(1) if date_match else None
            current_goal = {
                "title": re.sub(r'\(by\s+.+?\)', '', goal_text).strip(),
                "target_date": target_date,
                "sub_goals": [],
            }
            current_domain["goals"].append(current_goal)
            section = "idle"
            continue

        # "Target Exam Date:" -> capture as target_date on current goal
        td_match = re.match(r'^(?:\*\*)?Target\s+(?:Exam\s+)?Date:?\*?\*?\s*(.+)', line)
        if td_match and current_goal:
            current_goal["target_date"] = td_match.group(1).strip()
            continue

        # "Sub-goals:" section marker -> capture sub-goals
        if re.match(r'^(?:\*\*)?Sub-goals?:?\*?\*?\s*$', line, re.IGNORECASE):
            section = "sub_goals"
            continue

        # Non-goal section headers -> stop capturing
        if re.match(
            r'^(?:\*\*)?(?:Current Status|Decision Tree|Time Allocation|'
            r'Key Metrics|Exam Domains|Dependencies|Subscription|Key Dates|'
            r'Vision|BLOCKED BY)',
            line, re.IGNORECASE,
        ):
            section = "idle"
            continue

        # Numbered item: "1. ..." or "1) ..."
        num_match = re.match(r'^\d+[.)]\s+(.+)', line)
        if num_match and section == "sub_goals" and current_goal:
            current_goal["sub_goals"].append(num_match.group(1).strip())
            continue

        # Bullet: "- text" or "* text"
        bullet_match = re.match(r'^[-*]\s+(.+)', line)
        if bullet_match:
            bullet_text = bullet_match.group(1).strip()
            if section == "sub_goals" and current_goal:
                current_goal["sub_goals"].append(bullet_text)
            elif section == "goals" and current_domain:
                # Markdown-format freeform goals (no "Primary Goal:" header)
                date_match = re.search(r'\(by\s+(.+?)\)', bullet_text)
                target_date = date_match.group(1) if date_match else None
                current_goal = {
                    "title": re.sub(r'\(by\s+.+?\)', '', bullet_text).strip(),
                    "target_date": target_date,
                    "sub_goals": [],
                }
                current_domain["goals"].append(current_goal)
            # In "idle" section, bullets are ignored (status lines, metrics, etc.)
            continue

        # Description text for domain (before any goals are added)
        if current_domain and not current_domain["goals"] and section == "idle":
            if current_domain["description"]:
                current_domain["description"] += " " + line
            else:
                current_domain["description"] = line

    return domains


def sync_from_gdoc() -> dict:
    """Sync Life Domains from Google Doc to local database.

    Fetches the doc, parses it, and upserts domains/goals.
    """
    ensure_data_dirs()

    if not LIFE_DOMAINS_DOC_ID:
        return {"error": "LIFE_DOMAINS_DOC_ID not configured"}

    # Fetch Google Doc content
    try:
        from .gdocs import read_google_doc
        doc_text = read_google_doc(LIFE_DOMAINS_DOC_ID)
    except ImportError:
        return {"error": "gdocs module not available"}
    except Exception as e:
        logger.error("Failed to fetch Life Domains doc: %s", e)
        return {"error": str(e)}

    parsed = _parse_domains_doc(doc_text)
    if not parsed:
        return {"error": "No domains found in document", "doc_id": LIFE_DOMAINS_DOC_ID}

    now = now_iso()
    conn = get_connection()
    try:
        domains_synced = 0
        goals_synced = 0

        for priority, domain_data in enumerate(reversed(parsed)):
            # Upsert domain by name
            existing = conn.execute(
                "SELECT id FROM life_domains WHERE name = ?",
                (domain_data["name"],),
            ).fetchone()

            if existing:
                domain_id = existing["id"]
                conn.execute(
                    """UPDATE life_domains SET description = ?, priority = ?,
                    updated_at = ? WHERE id = ?""",
                    (domain_data.get("description", ""), priority, now, domain_id),
                )
            else:
                domain_id = _generate_id()
                conn.execute(
                    """INSERT INTO life_domains
                    (id, name, description, priority, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (domain_id, domain_data["name"],
                     domain_data.get("description", ""), priority, now, now),
                )
            domains_synced += 1

            # Upsert goals
            for goal_data in domain_data.get("goals", []):
                existing_goal = conn.execute(
                    "SELECT id FROM life_goals WHERE domain_id = ? AND title = ?",
                    (domain_id, goal_data["title"]),
                ).fetchone()

                if existing_goal:
                    goal_id = existing_goal["id"]
                    conn.execute(
                        "UPDATE life_goals SET target_date = ?, updated_at = ? WHERE id = ?",
                        (goal_data.get("target_date"), now, goal_id),
                    )
                else:
                    goal_id = _generate_id()
                    conn.execute(
                        """INSERT INTO life_goals
                        (id, domain_id, title, target_date, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (goal_id, domain_id, goal_data["title"],
                         goal_data.get("target_date"), now, now),
                    )
                goals_synced += 1

                # Upsert sub-goals
                for sg_title in goal_data.get("sub_goals", []):
                    existing_sg = conn.execute(
                        "SELECT id FROM life_sub_goals WHERE goal_id = ? AND title = ?",
                        (goal_id, sg_title),
                    ).fetchone()
                    if not existing_sg:
                        conn.execute(
                            """INSERT INTO life_sub_goals
                            (id, goal_id, title, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)""",
                            (_generate_id(), goal_id, sg_title, now, now),
                        )

        conn.commit()
        return {
            "status": "synced",
            "domains_synced": domains_synced,
            "goals_synced": goals_synced,
            "doc_id": LIFE_DOMAINS_DOC_ID,
        }
    except Exception as e:
        logger.error("sync_from_gdoc failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-Metrics
# ---------------------------------------------------------------------------

def collect_auto_metrics() -> dict:
    """Collect automated metrics from existing JayBrain data.

    Sources:
    - Forge readiness for Security+ goals
    - Application counts for Career goals
    - Study streak for Learning goals
    """
    conn = get_connection()
    try:
        now = now_iso()
        metrics_collected = 0

        # Find goals with auto_metric_source
        goals = conn.execute(
            "SELECT id, auto_metric_source FROM life_goals WHERE auto_metric_source != ''"
        ).fetchall()

        for goal in goals:
            source = goal["auto_metric_source"]
            value = None

            if source == "forge_readiness":
                value = _get_forge_readiness_metric(conn)
            elif source == "application_count":
                value = _get_application_count_metric(conn)
            elif source == "forge_streak":
                value = _get_forge_streak_metric(conn)

            if value is not None:
                conn.execute(
                    """INSERT INTO life_goal_metrics
                    (id, goal_id, metric_name, metric_value, source, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (_generate_id(), goal["id"], source, value, "auto", now),
                )
                metrics_collected += 1

        conn.commit()
        return {"status": "collected", "metrics_collected": metrics_collected}
    except Exception as e:
        logger.error("collect_auto_metrics failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def _get_forge_readiness_metric(conn) -> Optional[float]:
    """Get overall forge readiness as a 0-1 float."""
    try:
        row = conn.execute(
            "SELECT AVG(mastery_level) FROM forge_concepts WHERE subject_id != ''"
        ).fetchone()
        return round(row[0], 3) if row[0] is not None else None
    except Exception:
        return None


def _get_application_count_metric(conn) -> Optional[float]:
    """Get count of active applications."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status NOT IN ('rejected', 'withdrawn')"
        ).fetchone()
        return float(row[0])
    except Exception:
        return None


def _get_forge_streak_metric(conn) -> Optional[float]:
    """Get current forge study streak in days."""
    try:
        rows = conn.execute(
            "SELECT date FROM forge_streaks ORDER BY date DESC LIMIT 30"
        ).fetchall()
        if not rows:
            return 0.0
        streak = 0
        today = datetime.now(timezone.utc).date()
        for row in rows:
            try:
                d = datetime.fromisoformat(row["date"]).date()
            except (ValueError, TypeError):
                d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            expected = today - __import__("datetime").timedelta(days=streak)
            if d == expected:
                streak += 1
            else:
                break
        return float(streak)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Conflict Detection
# ---------------------------------------------------------------------------

def detect_conflicts() -> dict:
    """Detect scheduling and resource conflicts across goals."""
    conn = get_connection()
    try:
        conflicts = []

        # 1. Time allocation exceeds available hours
        domains = conn.execute("SELECT * FROM life_domains").fetchall()
        total_hours = sum(d["hours_per_week"] for d in domains)
        if total_hours > LIFE_DOMAINS_AVAILABLE_HOURS_WEEK:
            conflicts.append({
                "type": "time_overcommit",
                "severity": "high",
                "message": (
                    f"Total allocated hours ({total_hours:.0f}h/week) exceeds "
                    f"available hours ({LIFE_DOMAINS_AVAILABLE_HOURS_WEEK}h/week)"
                ),
            })

        # 2. Goals with past target dates still active
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        overdue = conn.execute(
            """SELECT g.title, g.target_date, d.name as domain_name
            FROM life_goals g JOIN life_domains d ON d.id = g.domain_id
            WHERE g.status = 'active' AND g.target_date IS NOT NULL
            AND g.target_date < ?""",
            (now_str,),
        ).fetchall()
        for g in overdue:
            conflicts.append({
                "type": "overdue_goal",
                "severity": "medium",
                "message": f"'{g['title']}' in {g['domain_name']} is past target date ({g['target_date']})",
            })

        # 3. Dependency conflicts (blocked goal has active work)
        dep_issues = conn.execute(
            """SELECT g1.title as goal_title, g2.title as dep_title,
                      g2.status as dep_status, g2.progress as dep_progress
            FROM life_goal_dependencies d
            JOIN life_goals g1 ON g1.id = d.goal_id
            JOIN life_goals g2 ON g2.id = d.depends_on_goal_id
            WHERE g1.status = 'active' AND g1.progress > 0
            AND g2.status = 'active' AND g2.progress < 0.5"""
        ).fetchall()
        for dep in dep_issues:
            conflicts.append({
                "type": "dependency_risk",
                "severity": "medium",
                "message": (
                    f"'{dep['goal_title']}' depends on '{dep['dep_title']}' "
                    f"which is only {dep['dep_progress']:.0%} complete"
                ),
            })

        return {
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "available_hours": LIFE_DOMAINS_AVAILABLE_HOURS_WEEK,
            "allocated_hours": total_hours,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Priority Stack
# ---------------------------------------------------------------------------

def get_priority_stack() -> dict:
    """Compute the current priority stack -- what to focus on right now.

    Considers: domain priority, deadline proximity, exam dates, dependencies.
    """
    conn = get_connection()
    try:
        goals = conn.execute(
            """SELECT g.*, d.name as domain_name, d.priority as domain_priority
            FROM life_goals g
            JOIN life_domains d ON d.id = g.domain_id
            WHERE g.status = 'active'"""
        ).fetchall()

        scored = []
        now = datetime.now(timezone.utc)
        for g in goals:
            score = g["domain_priority"] * 10  # Base from domain priority

            # Deadline proximity bonus
            if g["target_date"]:
                try:
                    target = datetime.fromisoformat(g["target_date"])
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    days_left = (target - now).days
                    if days_left < 0:
                        score += 50  # Overdue
                    elif days_left < 7:
                        score += 30
                    elif days_left < 30:
                        score += 15
                    elif days_left < 90:
                        score += 5
                except (ValueError, TypeError):
                    pass

            # Low progress on high-priority = boost
            if g["progress"] < 0.3:
                score += 10

            scored.append({
                "goal_id": g["id"],
                "title": g["title"],
                "domain": g["domain_name"],
                "progress": g["progress"],
                "target_date": g["target_date"],
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        return {
            "priority_stack": scored[:10],
            "total_active_goals": len(scored),
        }
    finally:
        conn.close()
