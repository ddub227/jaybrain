"""Event discovery -- find local cybersecurity and networking events.

Searches Eventbrite API and web sources for relevant events in the configured
location. Runs weekly via daemon, results stored in discovered_events table.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from .config import (
    EVENT_DISCOVERY_LOCATION,
    EVENTBRITE_API_KEY,
    SCRAPE_TIMEOUT,
    SCRAPE_USER_AGENT,
    ensure_data_dirs,
)
from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Search keywords for relevant events
SEARCH_KEYWORDS = [
    "cybersecurity",
    "information security",
    "SOC analyst",
    "security operations",
    "networking IT",
    "ISSA",
    "ISACA",
    "BSides",
    "CTF capture the flag",
    "infosec",
    "blue team",
    "purple team",
]

# Relevance keywords for scoring
RELEVANCE_TERMS = {
    "cybersecurity": 3,
    "security": 2,
    "soc": 3,
    "siem": 3,
    "incident response": 3,
    "networking": 1,
    "python": 1,
    "cloud": 1,
    "devops": 1,
    "ctf": 3,
    "bsides": 3,
    "blue team": 3,
    "threat": 2,
    "detection": 2,
    "splunk": 3,
    "career": 1,
}


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _score_relevance(title: str, description: str) -> float:
    """Score event relevance from 0.0 to 1.0 based on keyword matches."""
    text = f"{title} {description}".lower()
    score = 0
    max_possible = sum(RELEVANCE_TERMS.values())

    for term, weight in RELEVANCE_TERMS.items():
        if term in text:
            score += weight

    return min(1.0, score / max_possible * 3)  # Scale up for partial matches


def discover_eventbrite(
    location: str = "",
    keywords: list[str] | None = None,
) -> list[dict]:
    """Search Eventbrite for relevant events.

    Returns list of event dicts with title, description, url, date, location.
    """
    if not EVENTBRITE_API_KEY:
        logger.info("Eventbrite API key not configured, skipping")
        return []

    location = location or EVENT_DISCOVERY_LOCATION
    keywords = keywords or SEARCH_KEYWORDS[:5]  # Top 5 keywords
    events = []

    headers = {
        "Authorization": f"Bearer {EVENTBRITE_API_KEY}",
    }

    for keyword in keywords:
        try:
            params = {
                "q": keyword,
                "location.address": location,
                "location.within": "50mi",
                "start_date.range_start": datetime.now(timezone.utc).isoformat(),
                "start_date.range_end": (
                    datetime.now(timezone.utc) + timedelta(days=60)
                ).isoformat(),
                "expand": "venue",
            }
            resp = requests.get(
                "https://www.eventbriteapi.com/v3/events/search/",
                headers=headers,
                params=params,
                timeout=SCRAPE_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("Eventbrite search failed for '%s': %s", keyword, resp.status_code)
                continue

            data = resp.json()
            for event in data.get("events", []):
                venue = event.get("venue", {})
                events.append({
                    "title": event.get("name", {}).get("text", ""),
                    "description": (event.get("description", {}).get("text", "") or "")[:500],
                    "url": event.get("url", ""),
                    "event_date": event.get("start", {}).get("utc", ""),
                    "location": venue.get("address", {}).get("localized_address_display", location),
                    "source": "eventbrite",
                })
        except Exception as e:
            logger.warning("Eventbrite search error for '%s': %s", keyword, e)
            continue

    return events


def discover_web_events(location: str = "") -> list[dict]:
    """Search the web for cybersecurity events via basic scraping.

    Falls back gracefully if scraping fails.
    """
    location = location or EVENT_DISCOVERY_LOCATION
    events = []

    # Try a few known cybersecurity event aggregators
    urls = [
        f"https://www.meetup.com/find/?keywords=cybersecurity&location={location.replace(' ', '%20')}",
    ]

    headers = {"User-Agent": SCRAPE_USER_AGENT}

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=SCRAPE_TIMEOUT)
            if resp.status_code != 200:
                continue

            # Basic parsing -- extract event-like content
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for event cards/links with relevant titles
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if not text or len(text) < 10:
                    continue
                text_lower = text.lower()
                if any(kw in text_lower for kw in ["security", "cyber", "networking", "ctf", "infosec"]):
                    events.append({
                        "title": text[:200],
                        "description": "",
                        "url": link["href"] if link["href"].startswith("http") else "",
                        "event_date": "",
                        "location": location,
                        "source": "web_scrape",
                    })
        except Exception as e:
            logger.debug("Web scraping failed for %s: %s", url, e)
            continue

    return events


def filter_relevant_events(events: list[dict], min_relevance: float = 0.1) -> list[dict]:
    """Score and filter events by relevance."""
    scored = []
    seen_titles = set()

    for event in events:
        title = event.get("title", "").strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())

        score = _score_relevance(title, event.get("description", ""))
        if score >= min_relevance:
            event["relevance_score"] = round(score, 2)
            scored.append(event)

    scored.sort(key=lambda e: e["relevance_score"], reverse=True)
    return scored[:20]  # Top 20


def _save_events(events: list[dict]) -> int:
    """Save discovered events to database. Returns count of new events."""
    conn = get_connection()
    try:
        now = now_iso()
        saved = 0

        for event in events:
            title = event.get("title", "")
            # Dedup by title
            existing = conn.execute(
                "SELECT id FROM discovered_events WHERE title = ?", (title,)
            ).fetchone()
            if existing:
                continue

            conn.execute(
                """INSERT INTO discovered_events
                (id, title, description, url, event_date, location,
                 source, relevance_score, tags, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
                (
                    _generate_id(),
                    title,
                    event.get("description", "")[:500],
                    event.get("url", ""),
                    event.get("event_date", ""),
                    event.get("location", ""),
                    event.get("source", ""),
                    event.get("relevance_score", 0.0),
                    json.dumps(event.get("tags", [])),
                    now, now,
                ),
            )
            saved += 1

        conn.commit()
        return saved
    except Exception as e:
        logger.error("Failed to save events: %s", e)
        return 0
    finally:
        conn.close()


def run_event_discovery() -> dict:
    """Main discovery workflow -- search all sources, filter, save.

    Called by daemon weekly or manually via MCP tool.
    """
    ensure_data_dirs()
    all_events = []

    # Eventbrite (if API key available)
    try:
        eb_events = discover_eventbrite()
        all_events.extend(eb_events)
        logger.info("Eventbrite: found %d events", len(eb_events))
    except Exception as e:
        logger.warning("Eventbrite discovery failed: %s", e)

    # Web scraping
    try:
        web_events = discover_web_events()
        all_events.extend(web_events)
        logger.info("Web scraping: found %d events", len(web_events))
    except Exception as e:
        logger.warning("Web discovery failed: %s", e)

    # Filter and score
    relevant = filter_relevant_events(all_events)

    # Save to DB
    saved = _save_events(relevant)

    # Notify if interesting events found
    if relevant:
        try:
            top_events = relevant[:3]
            lines = [f"Found {len(relevant)} relevant events this week:"]
            for e in top_events:
                lines.append(f"  - {e['title']} (relevance: {e.get('relevance_score', 0):.0%})")
            from .telegram import send_telegram_message
            send_telegram_message("\n".join(lines))
        except Exception:
            pass  # Notification is optional

    return {
        "total_discovered": len(all_events),
        "relevant": len(relevant),
        "new_saved": saved,
        "location": EVENT_DISCOVERY_LOCATION,
    }


def list_events(status: str = "new", limit: int = 20) -> dict:
    """List discovered events, optionally filtered by status."""
    conn = get_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM discovered_events WHERE status = ? ORDER BY event_date LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM discovered_events ORDER BY event_date LIMIT ?",
                (limit,),
            ).fetchall()

        return {
            "events": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "description": r["description"][:200],
                    "url": r["url"],
                    "event_date": r["event_date"],
                    "location": r["location"],
                    "source": r["source"],
                    "relevance_score": r["relevance_score"],
                    "status": r["status"],
                }
                for r in rows
            ],
            "count": len(rows),
            "filter": status,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
