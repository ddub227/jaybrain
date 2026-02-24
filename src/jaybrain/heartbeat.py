"""Heartbeat notifications -- proactive checks with Telegram push alerts.

The daemon runs these checks on schedule. Each check evaluates a condition
and optionally sends a Telegram notification. Rate limiting prevents spam.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import (
    HEARTBEAT_APP_STALE_DAYS,
    HEARTBEAT_FORGE_DUE_THRESHOLD,
    SECURITY_PLUS_EXAM_DATE,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Rate limit: don't send the same check notification more than once per window
RATE_LIMIT_HOURS = {
    "forge_study_morning": 20,
    "forge_study_evening": 20,
    "exam_countdown": 22,
    "stale_applications": 22,
    "session_crash": 2,
    "goal_staleness": 160,  # ~weekly
    "time_allocation": 160,  # ~weekly
    "network_decay": 160,  # ~weekly
}


def _was_recently_notified(check_name: str) -> bool:
    """Check if this notification was already sent within the rate limit window."""
    hours = RATE_LIMIT_HOURS.get(check_name, 12)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM heartbeat_log
            WHERE check_name = ? AND notified = 1 AND checked_at > ?""",
            (check_name, cutoff),
        ).fetchone()
        return row[0] > 0
    except Exception:
        return False
    finally:
        conn.close()


def _log_check(check_name: str, triggered: bool, message: str, notified: bool) -> None:
    """Record a heartbeat check to the log."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO heartbeat_log
            (check_name, triggered, message, notified, checked_at)
            VALUES (?, ?, ?, ?, ?)""",
            (check_name, int(triggered), message, int(notified), now_iso()),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to log heartbeat check: %s", e)
    finally:
        conn.close()


def dispatch_notification(check_name: str, message: str) -> bool:
    """Send a Telegram notification if not rate-limited.

    Returns True if the notification was sent.
    """
    if _was_recently_notified(check_name):
        _log_check(check_name, True, message, False)
        return False

    try:
        from .telegram import send_telegram_message
        send_telegram_message(message)
        _log_check(check_name, True, message, True)
        return True
    except Exception as e:
        logger.error("Failed to send heartbeat notification: %s", e)
        _log_check(check_name, True, message, False)
        return False


# ---------------------------------------------------------------------------
# Individual Checks
# ---------------------------------------------------------------------------

def check_forge_study_morning() -> dict:
    """Morning check: concepts due for review + streak status."""
    return _check_forge_study("forge_study_morning", "morning")


def check_forge_study_evening() -> dict:
    """Evening check: remind if no study today."""
    return _check_forge_study("forge_study_evening", "evening")


def _check_forge_study(check_name: str, time_of_day: str) -> dict:
    """Core forge study check logic."""
    ensure_data_dirs()
    conn = get_connection()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Count due concepts
        due_count = conn.execute(
            "SELECT COUNT(*) FROM forge_concepts WHERE next_review <= ?",
            (today,),
        ).fetchone()[0]

        # Check streak
        streak_row = conn.execute(
            "SELECT date FROM forge_streaks ORDER BY date DESC LIMIT 1"
        ).fetchone()
        studied_today = streak_row and streak_row["date"] == today if streak_row else False

        if due_count < HEARTBEAT_FORGE_DUE_THRESHOLD and studied_today:
            _log_check(check_name, False, "No action needed", False)
            return {"triggered": False, "due_count": due_count, "studied_today": studied_today}

        # Build notification
        parts = []
        if time_of_day == "morning":
            parts.append(f"You have {due_count} concepts due for review.")
            if not studied_today:
                parts.append("No study logged yet today -- your streak is at risk.")
        else:
            if not studied_today:
                parts.append("No study session today. Quick 10-minute review can keep your streak alive.")
            if due_count >= HEARTBEAT_FORGE_DUE_THRESHOLD:
                parts.append(f"{due_count} concepts are overdue.")

        message = " ".join(parts)
        if parts:
            dispatch_notification(check_name, message)

        return {"triggered": True, "due_count": due_count, "studied_today": studied_today, "message": message}
    except Exception as e:
        logger.error("check_forge_study failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def check_exam_countdown() -> dict:
    """Daily Security+ exam countdown notification."""
    check_name = "exam_countdown"
    ensure_data_dirs()

    if not SECURITY_PLUS_EXAM_DATE:
        _log_check(check_name, False, "No exam date configured", False)
        return {"triggered": False, "message": "No exam date configured"}

    try:
        exam_date = datetime.strptime(SECURITY_PLUS_EXAM_DATE, "%Y-%m-%d")
        exam_date = exam_date.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"error": f"Invalid exam date format: {SECURITY_PLUS_EXAM_DATE}"}

    now = datetime.now(timezone.utc)
    days_left = (exam_date - now).days

    if days_left < 0:
        _log_check(check_name, False, "Exam date has passed", False)
        return {"triggered": False, "days_left": days_left, "message": "Exam date has passed"}

    if days_left > 14:
        _log_check(check_name, False, f"{days_left} days left (>14, no alert)", False)
        return {"triggered": False, "days_left": days_left}

    # Get readiness data
    conn = get_connection()
    try:
        avg_mastery = conn.execute(
            "SELECT AVG(mastery_level) FROM forge_concepts WHERE subject_id != ''"
        ).fetchone()[0]
        avg_mastery = avg_mastery or 0.0
    finally:
        conn.close()

    message = (
        f"Security+ exam in {days_left} days! "
        f"Current average mastery: {avg_mastery:.0%}. "
    )
    if days_left <= 3:
        message += "Final stretch -- focus on weak areas."
    elif days_left <= 7:
        message += "One week out. Review flagged concepts."

    dispatch_notification(check_name, message)
    return {"triggered": True, "days_left": days_left, "avg_mastery": avg_mastery, "message": message}


def check_stale_applications() -> dict:
    """Check for job applications sitting in 'applied' status too long."""
    check_name = "stale_applications"
    ensure_data_dirs()

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=HEARTBEAT_APP_STALE_DAYS)
    ).isoformat()

    conn = get_connection()
    try:
        stale = conn.execute(
            """SELECT a.id, j.company, j.title, a.applied_date
            FROM applications a
            JOIN job_postings j ON j.id = a.job_id
            WHERE a.status = 'applied' AND a.applied_date IS NOT NULL
            AND a.applied_date < ?""",
            (cutoff,),
        ).fetchall()

        if not stale:
            _log_check(check_name, False, "No stale applications", False)
            return {"triggered": False, "stale_count": 0}

        lines = [f"{len(stale)} application(s) need follow-up:"]
        for app in stale[:5]:
            lines.append(f"  - {app['company']}: {app['title']}")

        message = "\n".join(lines)
        dispatch_notification(check_name, message)
        return {"triggered": True, "stale_count": len(stale), "message": message}
    except Exception as e:
        logger.error("check_stale_applications failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def check_session_crash() -> dict:
    """Detect stalled Claude Code sessions (active but no heartbeat >30 min)."""
    check_name = "session_crash"
    ensure_data_dirs()

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).isoformat()

    conn = get_connection()
    try:
        # Look in the Pulse tables (created by session_hook.py)
        try:
            stalled = conn.execute(
                """SELECT session_id, cwd, last_heartbeat, tool_count
                FROM claude_sessions
                WHERE status = 'active' AND last_heartbeat < ?""",
                (cutoff,),
            ).fetchall()
        except Exception:
            # Table may not exist
            _log_check(check_name, False, "claude_sessions table not available", False)
            return {"triggered": False, "stalled_count": 0}

        if not stalled:
            _log_check(check_name, False, "No stalled sessions", False)
            return {"triggered": False, "stalled_count": 0}

        lines = [f"{len(stalled)} stalled session(s) detected:"]
        for s in stalled[:3]:
            lines.append(f"  - {s['session_id'][:12]}... ({s['tool_count']} tools, cwd: {s['cwd']})")

        message = "\n".join(lines)
        dispatch_notification(check_name, message)
        return {"triggered": True, "stalled_count": len(stalled), "message": message}
    except Exception as e:
        logger.error("check_session_crash failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def check_goal_staleness() -> dict:
    """Weekly check: flag goals with no progress updates in 2+ weeks."""
    check_name = "goal_staleness"
    ensure_data_dirs()

    conn = get_connection()
    try:
        two_weeks_ago = (
            datetime.now(timezone.utc) - timedelta(weeks=2)
        ).isoformat()

        stale_goals = conn.execute(
            """SELECT g.title, d.name as domain_name, g.progress, g.updated_at
            FROM life_goals g
            JOIN life_domains d ON d.id = g.domain_id
            WHERE g.status = 'active' AND g.updated_at < ?""",
            (two_weeks_ago,),
        ).fetchall()

        if not stale_goals:
            _log_check(check_name, False, "No stale goals", False)
            return {"triggered": False, "stale_count": 0}

        lines = [f"{len(stale_goals)} goal(s) haven't been updated in 2+ weeks:"]
        for g in stale_goals[:5]:
            lines.append(f"  - [{g['domain_name']}] {g['title']} ({g['progress']:.0%})")

        message = "\n".join(lines)
        dispatch_notification(check_name, message)
        return {"triggered": True, "stale_count": len(stale_goals), "message": message}
    except Exception as e:
        logger.error("check_goal_staleness failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP Tool Support
# ---------------------------------------------------------------------------

def get_heartbeat_status() -> dict:
    """Get recent heartbeat check history."""
    conn = get_connection()
    try:
        recent = conn.execute(
            """SELECT check_name, triggered, message, notified, checked_at
            FROM heartbeat_log
            ORDER BY checked_at DESC LIMIT 20"""
        ).fetchall()

        # Per-check latest
        latest_per_check = {}
        for r in recent:
            name = r["check_name"]
            if name not in latest_per_check:
                latest_per_check[name] = {
                    "last_checked": r["checked_at"],
                    "last_triggered": bool(r["triggered"]),
                    "last_notified": bool(r["notified"]),
                    "last_message": r["message"],
                }

        return {
            "checks": latest_per_check,
            "recent_log": [
                {
                    "check": r["check_name"],
                    "triggered": bool(r["triggered"]),
                    "notified": bool(r["notified"]),
                    "message": r["message"][:100],
                    "at": r["checked_at"],
                }
                for r in recent[:10]
            ],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def _check_time_allocation_wrapper() -> dict:
    """Wrapper to call time_allocation.check_time_allocation()."""
    from .time_allocation import check_time_allocation
    return check_time_allocation()


def _check_network_decay_wrapper() -> dict:
    """Wrapper to call network_decay.check_network_decay()."""
    from .network_decay import check_network_decay
    return check_network_decay()


def run_single_check(check_name: str) -> dict:
    """Run a single heartbeat check by name."""
    checks = {
        "forge_study": check_forge_study_morning,
        "forge_study_morning": check_forge_study_morning,
        "forge_study_evening": check_forge_study_evening,
        "exam_countdown": check_exam_countdown,
        "stale_applications": check_stale_applications,
        "session_crash": check_session_crash,
        "goal_staleness": check_goal_staleness,
        "time_allocation": _check_time_allocation_wrapper,
        "network_decay": _check_network_decay_wrapper,
    }

    func = checks.get(check_name)
    if not func:
        return {"error": f"Unknown check: {check_name}. Available: {list(checks.keys())}"}

    return func()
