"""Tests for the profile module (YAML read/write)."""

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.profile import (
    get_profile,
    update_profile,
    DEFAULT_PROFILE,
    _ensure_profile_exists,
)
import jaybrain.profile as profile_mod


def _setup(temp_data_dir, monkeypatch):
    ensure_data_dirs()
    # Patch the module-level PROFILE_PATH import
    import jaybrain.config as config
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", config.PROFILE_PATH)


class TestGetProfile:
    def test_creates_default_if_missing(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = get_profile()
        assert profile["name"] == "Joshua"
        assert profile["nickname"] == "JJ"
        assert "communication_style" in profile["preferences"]

    def test_reads_existing_profile(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        # Create default first
        get_profile()
        # Read again
        profile = get_profile()
        assert profile["name"] == "Joshua"

    def test_default_profile_structure(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = get_profile()
        assert isinstance(profile["preferences"], dict)
        assert isinstance(profile["projects"], list)
        assert isinstance(profile["tools"], list)
        assert isinstance(profile["notes"], dict)


class TestUpdateProfile:
    def test_update_preference(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("preferences", "theme", "dark")
        assert profile["preferences"]["theme"] == "dark"
        # Original preferences should still exist
        assert "communication_style" in profile["preferences"]

    def test_update_note(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("notes", "reminder", "Check logs daily")
        assert profile["notes"]["reminder"] == "Check logs daily"

    def test_add_project(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("projects", "new-project", "new-project")
        assert "new-project" in profile["projects"]

    def test_add_duplicate_project_ignored(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        update_profile("projects", "jaybrain", "jaybrain")
        profile = update_profile("projects", "jaybrain", "jaybrain")
        # Should not have duplicates
        assert profile["projects"].count("jaybrain") == 1

    def test_add_tool(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("tools", "Docker", "Docker")
        assert "Docker" in profile["tools"]

    def test_update_root(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("root", "nickname", "Jay")
        assert profile["nickname"] == "Jay"

    def test_update_new_section(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        profile = update_profile("custom_section", "key1", "value1")
        assert profile["custom_section"]["key1"] == "value1"

    def test_update_persists(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        update_profile("preferences", "editor", "vim")
        # Read fresh
        profile = get_profile()
        assert profile["preferences"]["editor"] == "vim"

    def test_multiple_updates(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir, monkeypatch)
        update_profile("preferences", "a", "1")
        update_profile("preferences", "b", "2")
        profile = update_profile("preferences", "c", "3")
        assert profile["preferences"]["a"] == "1"
        assert profile["preferences"]["b"] == "2"
        assert profile["preferences"]["c"] == "3"
