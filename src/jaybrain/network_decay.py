"""Network relationship decay -- track contacts and nudge when they go cold.

Uses the knowledge graph's person entities with properties JSON to store
contact metadata (last_contact, decay_threshold_days, contact_count).
No new tables required.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .config import NETWORK_DECAY_DEFAULT_DAYS
from .db import get_connection

logger = logging.getLogger(__name__)


def add_contact(
    name: str,
    contact_type: str = "professional",
    company: str = "",
    role: str = "",
    how_met: str = "",
    decay_threshold_days: int = NETWORK_DECAY_DEFAULT_DAYS,
) -> dict:
    """Add a new contact as a person entity in the knowledge graph.

    Sets last_contact to now and contact_count to 0.
    If a person with this name already exists, merges the new properties.
    """
    from .graph import add_entity

    now = datetime.now(timezone.utc).isoformat()
    description = f"{role} at {company}".strip(" at ") if (role or company) else ""
    properties = {
        "contact_type": contact_type,
        "company": company,
        "role": role,
        "how_met": how_met,
        "decay_threshold_days": decay_threshold_days,
        "last_contact": now,
        "contact_count": 0,
    }

    result = add_entity(
        name=name,
        entity_type="person",
        description=description,
        properties=properties,
    )
    return result


def log_interaction(name: str, note: str = "") -> dict:
    """Record an interaction with a contact.

    Finds the person by name (case-insensitive), updates last_contact to now,
    increments contact_count, and optionally stores a note.
    """
    from .graph import search_entities, add_entity

    matches = search_entities(name, entity_type="person", limit=5)
    if not matches:
        return {"error": f"No contact found matching '{name}'"}

    # Prefer exact match (case-insensitive), otherwise take first result
    contact = None
    for m in matches:
        if m["name"].lower() == name.lower():
            contact = m
            break
    if not contact:
        contact = matches[0]

    now = datetime.now(timezone.utc).isoformat()
    props = contact.get("properties", {})
    contact_count = props.get("contact_count", 0) + 1

    update_props = {
        "last_contact": now,
        "contact_count": contact_count,
    }
    if note:
        update_props["last_note"] = note

    result = add_entity(
        name=contact["name"],
        entity_type="person",
        properties=update_props,
    )
    return result


def get_stale_contacts(threshold_override: Optional[int] = None) -> list[dict]:
    """Get contacts sorted by staleness (most overdue first).

    Returns all contacts that have last_contact in their properties,
    with calculated days_since_contact and overdue_by fields.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM graph_entities WHERE entity_type = 'person' ORDER BY name"
        ).fetchall()

        now = datetime.now(timezone.utc)
        contacts = []

        for row in rows:
            props = json.loads(row["properties"]) if row["properties"] else {}
            last_contact = props.get("last_contact")
            if not last_contact:
                continue

            try:
                last_dt = datetime.fromisoformat(last_contact)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            days_since = (now - last_dt).days
            threshold = threshold_override or props.get(
                "decay_threshold_days", NETWORK_DECAY_DEFAULT_DAYS
            )
            overdue_by = days_since - threshold

            contacts.append({
                "name": row["name"],
                "company": props.get("company", ""),
                "role": props.get("role", ""),
                "contact_type": props.get("contact_type", ""),
                "last_contact": last_contact,
                "days_since_contact": days_since,
                "threshold": threshold,
                "overdue_by": overdue_by,
                "contact_count": props.get("contact_count", 0),
                "last_note": props.get("last_note", ""),
            })

        contacts.sort(key=lambda c: c["overdue_by"], reverse=True)
        return contacts
    finally:
        conn.close()


def get_network_health() -> dict:
    """Get a summary of network health: total, healthy, stale, most neglected."""
    contacts = get_stale_contacts()
    total = len(contacts)
    stale = [c for c in contacts if c["overdue_by"] > 0]
    healthy = [c for c in contacts if c["overdue_by"] <= 0]

    result = {
        "total_contacts": total,
        "healthy_count": len(healthy),
        "stale_count": len(stale),
        "contacts": contacts,
    }

    if stale:
        result["most_neglected"] = stale[0]

    return result


def check_network_decay() -> dict:
    """Heartbeat check: notify if contacts are overdue for outreach.

    Called by the daemon on schedule. Uses dispatch_notification for
    rate-limited Telegram alerts.
    """
    check_name = "network_decay"

    try:
        contacts = get_stale_contacts()
        overdue = [c for c in contacts if c["overdue_by"] > 0]

        if not overdue:
            from .heartbeat import _log_check
            _log_check(check_name, False, "No stale contacts", False)
            return {"triggered": False, "stale_count": 0}

        lines = [f"{len(overdue)} contact(s) need attention:"]
        for c in overdue[:5]:
            company_str = f" ({c['company']})" if c["company"] else ""
            lines.append(
                f"  - {c['name']}{company_str} -- {c['overdue_by']} days overdue"
            )
        if len(overdue) > 5:
            lines.append(f"  ...and {len(overdue) - 5} more")

        message = "\n".join(lines)

        from .heartbeat import dispatch_notification
        dispatch_notification(check_name, message)

        return {"triggered": True, "stale_count": len(overdue), "message": message}
    except Exception as e:
        logger.error("check_network_decay failed: %s", e)
        return {"error": str(e)}
# test
