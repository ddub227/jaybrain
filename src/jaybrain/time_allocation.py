"""Time allocation tracking -- actual hours from Pulse vs Life Domains targets.

Uses activity-based time calculation: sum gaps between consecutive tool calls
per session, capping gaps at the idle threshold. Wall-clock session time is
unreliable (sessions left open show 49h+).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import (
    TIME_ALLOCATION_CWD_MAP,
    TIME_ALLOCATION_IDLE_THRESHOLD_MIN,
    TIME_ALLOCATION_LOOKBACK_DAYS,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Cache: short label -> full domain name from DB
_domain_name_cache: dict[str, str] = {}


def _resolve_domain_name(short_label: str) -> str:
    """Resolve a short label (e.g. 'Career') to the full DB domain name.

    Matches if the domain name starts with the label (case-insensitive).
    Falls back to the short label if no DB match found.
    """
    if short_label in _domain_name_cache:
        return _domain_name_cache[short_label]

    # Populate cache on first call
    if not _domain_name_cache:
        try:
            conn = get_connection()
            try:
                rows = conn.execute("SELECT name FROM life_domains").fetchall()
                # Pre-populate with identity mappings so we only query once
                for r in rows:
                    _domain_name_cache[r["name"]] = r["name"]
            finally:
                conn.close()
        except Exception:
            pass

    # Find a domain whose name starts with the short label
    label_lower = short_label.lower()
    for full_name in list(_domain_name_cache.values()):
        if full_name.lower().startswith(label_lower):
            _domain_name_cache[short_label] = full_name
            return full_name

    # No match -- use the label as-is
    _domain_name_cache[short_label] = short_label
    return short_label


def _map_cwd_to_domain(cwd: str) -> str:
    """Map a working directory path to a domain name via config patterns."""
    cwd_lower = cwd.lower()
    for pattern, domain in TIME_ALLOCATION_CWD_MAP.items():
        if pattern.lower() in cwd_lower:
            return _resolve_domain_name(domain)
    return "Uncategorized"


def calculate_active_time(
    session_id: str,
    idle_threshold_min: int = TIME_ALLOCATION_IDLE_THRESHOLD_MIN,
) -> float:
    """Calculate active hours for a session from activity log timestamps.

    Walks consecutive events in session_activity_log. If the gap between two
    consecutive events is <= idle_threshold_min, that gap counts as active time.
    Gaps larger than the threshold are treated as idle and skipped.

    Returns active time in hours.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT timestamp FROM session_activity_log
            WHERE session_id = ?
            ORDER BY timestamp ASC""",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return 0.0

    threshold = timedelta(minutes=idle_threshold_min)
    active_seconds = 0.0

    for i in range(1, len(rows)):
        t_prev = datetime.fromisoformat(rows[i - 1]["timestamp"])
        t_curr = datetime.fromisoformat(rows[i]["timestamp"])
        gap = t_curr - t_prev
        if gap <= threshold:
            active_seconds += gap.total_seconds()

    return active_seconds / 3600.0


def query_time_by_domain(days_back: int = TIME_ALLOCATION_LOOKBACK_DAYS) -> dict:
    """Aggregate active time across sessions, grouped by domain.

    Returns: {
        "domains": {domain_name: hours, ...},
        "total_hours": float,
        "sessions_analyzed": int,
        "period_start": str,
        "period_end": str,
    }
    """
    ensure_data_dirs()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).isoformat()

    conn = get_connection()
    try:
        sessions = conn.execute(
            """SELECT session_id, cwd FROM claude_sessions
            WHERE started_at >= ?""",
            (cutoff,),
        ).fetchall()
    except Exception:
        # Table may not exist yet
        return {
            "domains": {},
            "total_hours": 0.0,
            "sessions_analyzed": 0,
            "period_start": cutoff,
            "period_end": now.isoformat(),
        }
    finally:
        conn.close()

    domain_hours: dict[str, float] = defaultdict(float)
    sessions_analyzed = 0

    for s in sessions:
        hours = calculate_active_time(s["session_id"])
        if hours > 0:
            domain = _map_cwd_to_domain(s["cwd"])
            domain_hours[domain] += hours
            sessions_analyzed += 1

    return {
        "domains": dict(domain_hours),
        "total_hours": sum(domain_hours.values()),
        "sessions_analyzed": sessions_analyzed,
        "period_start": cutoff,
        "period_end": now.isoformat(),
    }


def _get_domain_targets() -> dict[str, float]:
    """Fetch hours_per_week targets from life_domains table."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT name, hours_per_week FROM life_domains"
        ).fetchall()
        return {r["name"]: r["hours_per_week"] for r in rows if r["hours_per_week"] > 0}
    except Exception:
        return {}
    finally:
        conn.close()


def get_weekly_report(days_back: int = TIME_ALLOCATION_LOOKBACK_DAYS) -> dict:
    """Compare actual hours per domain vs Life Domains targets.

    Returns: {
        "domains": [
            {
                "name": str,
                "actual_hours": float,
                "target_hours": float,
                "pct": float,       # actual/target as percentage
                "status": str,      # "on_track", "under", "over", "no_target"
            },
            ...
        ],
        "total_actual": float,
        "total_target": float,
        "period_days": int,
    }
    """
    time_data = query_time_by_domain(days_back)
    targets = _get_domain_targets()

    # Collect all domain names from both sources
    all_domains = set(time_data["domains"].keys()) | set(targets.keys())

    # Scale targets if lookback period != 7 days
    scale = days_back / 7.0

    domains = []
    for name in sorted(all_domains):
        actual = time_data["domains"].get(name, 0.0)
        raw_target = targets.get(name, 0.0)
        scaled_target = raw_target * scale

        if scaled_target > 0:
            pct = (actual / scaled_target) * 100
            if pct < 50:
                status = "under"
            elif pct > 150:
                status = "over"
            else:
                status = "on_track"
        else:
            pct = 0.0
            status = "no_target"

        domains.append({
            "name": name,
            "actual_hours": round(actual, 1),
            "target_hours": round(scaled_target, 1),
            "pct": round(pct, 0),
            "status": status,
        })

    total_target = sum(d["target_hours"] for d in domains)

    return {
        "domains": domains,
        "total_actual": round(time_data["total_hours"], 1),
        "total_target": round(total_target, 1),
        "period_days": days_back,
        "sessions_analyzed": time_data["sessions_analyzed"],
    }


def get_daily_breakdown(days_back: int = TIME_ALLOCATION_LOOKBACK_DAYS) -> list[dict]:
    """Per-day breakdown of hours by domain.

    Returns a list of dicts, one per day:
    [
        {"date": "2026-02-22", "domains": {"JayBrain Development": 3.2, ...}, "total": 5.4},
        ...
    ]
    """
    ensure_data_dirs()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days_back)).isoformat()

    conn = get_connection()
    try:
        sessions = conn.execute(
            """SELECT session_id, cwd, started_at FROM claude_sessions
            WHERE started_at >= ?""",
            (cutoff,),
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()

    # Build per-day, per-domain hours
    # Assign session to the day it started
    day_data: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for s in sessions:
        hours = calculate_active_time(s["session_id"])
        if hours > 0:
            domain = _map_cwd_to_domain(s["cwd"])
            day = s["started_at"][:10]  # YYYY-MM-DD
            day_data[day][domain] += hours

    result = []
    for day in sorted(day_data.keys()):
        domains = {k: round(v, 1) for k, v in day_data[day].items()}
        result.append({
            "date": day,
            "domains": domains,
            "total": round(sum(day_data[day].values()), 1),
        })

    return result


def check_time_allocation() -> dict:
    """Heartbeat check: weekly actual vs target, notify on significant drift.

    Sends a Telegram notification if any domain is <50% or >150% of its
    weekly target.
    """
    from .heartbeat import dispatch_notification

    check_name = "time_allocation"
    report = get_weekly_report()

    alerts = []
    for d in report["domains"]:
        if d["status"] == "under":
            alerts.append(
                f"  - {d['name']}: {d['actual_hours']}h / {d['target_hours']}h ({d['pct']:.0f}%) -- under target"
            )
        elif d["status"] == "over":
            alerts.append(
                f"  - {d['name']}: {d['actual_hours']}h / {d['target_hours']}h ({d['pct']:.0f}%) -- over target"
            )

    if not alerts:
        return {"triggered": False, "report": report}

    lines = [f"Time allocation drift detected ({report['period_days']}-day window):"]
    lines.extend(alerts)
    lines.append(f"\nTotal: {report['total_actual']}h / {report['total_target']}h target")

    message = "\n".join(lines)
    dispatch_notification(check_name, message)
    return {"triggered": True, "message": message, "report": report}
