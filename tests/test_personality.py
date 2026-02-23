"""Tests for the personality module."""

import json
from unittest.mock import patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db, now_iso


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestGetGreeting:
    def test_returns_string(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_greeting

        greeting = get_greeting()
        assert isinstance(greeting, str)
        assert len(greeting) > 0

    def test_greeting_varies(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_greeting

        greetings = {get_greeting() for _ in range(20)}
        # Should get at least 2 different greetings in 20 tries
        assert len(greetings) >= 2

    def test_hype_mode_greeting(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_greeting

        # Set hype mode
        conn = get_connection()
        try:
            now = now_iso()
            conn.execute(
                """INSERT INTO personality_config
                (id, style, energy_level, humor_level, traits, updated_at)
                VALUES (1, 'hype', 1.0, 0.9, '{}', ?)""",
                (now,),
            )
            conn.commit()
        finally:
            conn.close()

        greeting = get_greeting()
        assert isinstance(greeting, str)


class TestFlavorText:
    def test_study_flavor(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import flavor_text

        text = flavor_text("study")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_heartbeat_flavor(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import flavor_text

        text = flavor_text("heartbeat")
        assert isinstance(text, str)

    def test_unknown_context_fallback(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import flavor_text

        text = flavor_text("unknown_context")
        assert isinstance(text, str)


class TestPersonalityPrompt:
    def test_default_prompt(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_personality_prompt

        prompt = get_personality_prompt()
        assert "Personality style" in prompt
        assert isinstance(prompt, str)


class TestGetOrUpdateConfig:
    def test_view_default_config(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_or_update_config

        result = get_or_update_config()
        assert result["style"] == "default"
        assert result["energy_level"] == 0.7
        assert result["humor_level"] == 0.5

    def test_update_style(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_or_update_config

        result = get_or_update_config(style="hype")
        assert result["style"] == "hype"
        assert result["status"] == "updated"

    def test_update_energy(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_or_update_config

        result = get_or_update_config(energy_level=0.3)
        assert result["energy_level"] == 0.3

    def test_invalid_style(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_or_update_config

        result = get_or_update_config(style="nonexistent")
        assert "error" in result

    def test_clamp_values(self, temp_data_dir):
        _setup_db()
        from jaybrain.personality import get_or_update_config

        result = get_or_update_config(energy_level=2.0, humor_level=-1.0)
        assert result["energy_level"] == 1.0
        assert result["humor_level"] == 0.0
