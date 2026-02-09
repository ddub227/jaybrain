"""User profile YAML read/write."""

from __future__ import annotations

import logging
from typing import Any, Optional

import yaml

from .config import PROFILE_PATH, ensure_data_dirs
from .models import UserProfile

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = {
    "name": "Joshua",
    "nickname": "JJ",
    "preferences": {
        "communication_style": "direct, no fluff",
        "code_style": "clean, no emojis in code",
        "learning_style": "hands-on with explanations",
    },
    "projects": ["jaybrain", "homelab"],
    "tools": ["Claude Code", "Python", "Git"],
    "notes": {},
}


def _ensure_profile_exists() -> None:
    """Create default profile.yaml if it doesn't exist."""
    ensure_data_dirs()
    if not PROFILE_PATH.exists():
        PROFILE_PATH.write_text(
            yaml.dump(DEFAULT_PROFILE, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )


def get_profile() -> dict:
    """Read the user profile from YAML."""
    _ensure_profile_exists()
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if data else DEFAULT_PROFILE
    except Exception as e:
        logger.warning("Failed to read profile, returning default: %s", e)
        return DEFAULT_PROFILE


def update_profile(section: str, key: str, value: Any) -> dict:
    """Update a specific field in the profile.

    Args:
        section: Top-level section (e.g., "preferences", "notes", "projects")
        key: Key within the section to update
        value: New value

    Returns:
        Updated profile dict
    """
    profile = get_profile()

    if section in ("preferences", "notes"):
        if section not in profile:
            profile[section] = {}
        profile[section][key] = value
    elif section in ("projects", "tools"):
        if section not in profile:
            profile[section] = []
        if isinstance(profile[section], list):
            if value not in profile[section]:
                profile[section].append(value)
        else:
            profile[section] = [value]
    elif section == "root":
        profile[key] = value
    else:
        # Create new section if it doesn't exist
        if section not in profile:
            profile[section] = {}
        if isinstance(profile[section], dict):
            profile[section][key] = value
        else:
            profile[section] = {key: value}

    # Write back
    PROFILE_PATH.write_text(
        yaml.dump(profile, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return profile
