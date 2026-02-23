"""Personality layer -- template-based flavor text for JayBrain.

All personality is generated from templates and random selection. No LLM calls.
Applied to Telegram messages, daily briefings, and heartbeat notifications.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone

from .db import get_connection, now_iso

logger = logging.getLogger(__name__)

# Personality traits config
PERSONALITY_TRAITS = {
    "default": {
        "name": "Default",
        "description": "Balanced, helpful, slightly witty",
        "energy": 0.7,
        "humor": 0.5,
    },
    "professional": {
        "name": "Professional",
        "description": "Crisp, efficient, minimal flavor",
        "energy": 0.4,
        "humor": 0.1,
    },
    "casual": {
        "name": "Casual",
        "description": "Relaxed, friendly, more humor",
        "energy": 0.8,
        "humor": 0.7,
    },
    "hype": {
        "name": "Hype",
        "description": "High energy motivator, Tim Dillon energy",
        "energy": 1.0,
        "humor": 0.9,
    },
}

# Greeting templates by time of day
GREETINGS = {
    "morning": [
        "Rise and grind, JJ.",
        "Morning. Let's get after it.",
        "New day, new opportunities.",
        "Good morning. Coffee first, then world domination.",
        "Top of the morning. What are we conquering today?",
    ],
    "afternoon": [
        "Afternoon check-in. How's the day going?",
        "Still crushing it?",
        "Midday status: operational.",
        "Afternoon. Let's keep the momentum.",
    ],
    "evening": [
        "Evening, JJ. Wrapping up or just getting started?",
        "Night owl mode activated.",
        "Evening session. The quiet hours are the productive hours.",
        "Late night? I respect the grind.",
    ],
}

GREETINGS_HYPE = {
    "morning": [
        "Wake up, JJ! The cybersecurity world needs you!",
        "GOOD MORNING. Today we're building something INCREDIBLE.",
        "Let's GO. The daemon isn't going to build itself!",
    ],
    "afternoon": [
        "Afternoon power hour! LET'S KEEP IT MOVING.",
        "Halfway through the day and STILL GOING STRONG.",
    ],
    "evening": [
        "Evening session? That's DEDICATION. That's what winners do!",
        "The late night is when LEGENDS are made. Let's DO THIS.",
    ],
}

# Flavor text for different contexts
FLAVOR_STUDY = [
    "Knowledge is power. Let's charge up.",
    "Every concept mastered is a step toward that cert.",
    "Forge time. Let's heat up those neurons.",
    "Study mode engaged. Distractions eliminated.",
]

FLAVOR_STUDY_HYPE = [
    "TIME TO FORGE. Those concepts aren't going to master themselves!",
    "Security+ doesn't stand a CHANCE against this level of preparation!",
    "SYNAPSEFORGE ACTIVATED. Let's turn those sparks into INFERNOS!",
]

FLAVOR_TASK = [
    "Another task down. Solid progress.",
    "Checked off. Moving on.",
    "Done and dusted.",
    "Marked complete. What's next?",
]

FLAVOR_HEARTBEAT = [
    "Quick heads up --",
    "FYI --",
    "Notification --",
    "Ping --",
]

FLAVOR_HEARTBEAT_HYPE = [
    "ATTENTION! This is NOT a drill --",
    "BREAKING NEWS from your friendly AI --",
    "Important update coming in HOT --",
]


def _get_time_of_day() -> str:
    hour = datetime.now(timezone.utc).hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    else:
        return "evening"


def _get_config() -> dict:
    """Load personality config from DB, with defaults."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM personality_config WHERE id = 1"
        ).fetchone()
        if row:
            return {
                "style": row["style"],
                "energy_level": row["energy_level"],
                "humor_level": row["humor_level"],
                "traits": json.loads(row["traits"]) if row["traits"] else {},
            }
    except Exception:
        pass
    finally:
        conn.close()

    return {"style": "default", "energy_level": 0.7, "humor_level": 0.5, "traits": {}}


def get_greeting() -> str:
    """Get a time-appropriate greeting."""
    config = _get_config()
    time_of_day = _get_time_of_day()

    if config["style"] == "hype" or config["energy_level"] >= 0.9:
        pool = GREETINGS_HYPE.get(time_of_day, GREETINGS_HYPE["morning"])
    else:
        pool = GREETINGS.get(time_of_day, GREETINGS["morning"])

    return random.choice(pool)


def flavor_text(context: str = "general") -> str:
    """Get flavor text for a given context.

    context: 'study', 'task', 'heartbeat', 'general'
    """
    config = _get_config()
    is_hype = config["style"] == "hype" or config["energy_level"] >= 0.9

    if context == "study":
        pool = FLAVOR_STUDY_HYPE if is_hype else FLAVOR_STUDY
    elif context == "task":
        pool = FLAVOR_TASK
    elif context == "heartbeat":
        pool = FLAVOR_HEARTBEAT_HYPE if is_hype else FLAVOR_HEARTBEAT
    else:
        pool = FLAVOR_TASK

    return random.choice(pool)


def get_personality_prompt() -> str:
    """Get a personality system prompt addition for Telegram/LLM context."""
    config = _get_config()
    style = config["style"]
    traits = PERSONALITY_TRAITS.get(style, PERSONALITY_TRAITS["default"])

    parts = [
        f"Personality style: {traits['name']} -- {traits['description']}.",
    ]

    if config["energy_level"] >= 0.8:
        parts.append("Use enthusiastic, energetic language.")
    elif config["energy_level"] <= 0.3:
        parts.append("Keep responses calm and measured.")

    if config["humor_level"] >= 0.7:
        parts.append("Include occasional humor and wit.")
    elif config["humor_level"] <= 0.2:
        parts.append("Keep responses serious and professional.")

    return " ".join(parts)


def get_or_update_config(**updates) -> dict:
    """View or update personality config. Called by MCP tool."""
    conn = get_connection()
    try:
        now = now_iso()

        if not updates:
            # Just return current config
            return _get_config()

        # Ensure row exists
        conn.execute(
            """INSERT OR IGNORE INTO personality_config
            (id, style, energy_level, humor_level, traits, updated_at)
            VALUES (1, 'default', 0.7, 0.5, '{}', ?)""",
            (now,),
        )

        if "style" in updates:
            if updates["style"] not in PERSONALITY_TRAITS:
                return {"error": f"Unknown style: {updates['style']}. Available: {list(PERSONALITY_TRAITS.keys())}"}
            conn.execute(
                "UPDATE personality_config SET style = ?, updated_at = ? WHERE id = 1",
                (updates["style"], now),
            )
        if "energy_level" in updates:
            conn.execute(
                "UPDATE personality_config SET energy_level = ?, updated_at = ? WHERE id = 1",
                (max(0.0, min(1.0, updates["energy_level"])), now),
            )
        if "humor_level" in updates:
            conn.execute(
                "UPDATE personality_config SET humor_level = ?, updated_at = ? WHERE id = 1",
                (max(0.0, min(1.0, updates["humor_level"])), now),
            )

        conn.commit()

        config = _get_config()
        config["status"] = "updated"
        return config
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
