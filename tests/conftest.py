"""Shared test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch, tmp_path):
    """Override data directories to use a temp dir for each test."""
    import jaybrain.config as config

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "DB_PATH", data_dir / "jaybrain.db")
    monkeypatch.setattr(config, "MEMORIES_DIR", data_dir / "memories")
    monkeypatch.setattr(config, "SESSIONS_DIR", data_dir / "sessions")
    monkeypatch.setattr(config, "PROFILE_PATH", data_dir / "profile.yaml")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "FORGE_DIR", data_dir / "forge")
    monkeypatch.setattr(config, "JOB_SEARCH_DIR", tmp_path / "job_search")
    monkeypatch.setattr(config, "RESUME_TEMPLATE_PATH", tmp_path / "job_search" / "resume_template.md")
    monkeypatch.setattr(config, "ACTIVE_SESSION_FILE", data_dir / ".active_session")

    # Also patch the db module's reference to DB_PATH
    import jaybrain.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", data_dir / "jaybrain.db")

    # Patch resume_tailor's imported references so they use the temp paths
    import jaybrain.resume_tailor as resume_mod
    monkeypatch.setattr(resume_mod, "RESUME_TEMPLATE_PATH", tmp_path / "job_search" / "resume_template.md")
    monkeypatch.setattr(resume_mod, "JOB_SEARCH_DIR", tmp_path / "job_search")

    # Patch profile module's imported references
    import jaybrain.profile as profile_mod
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", data_dir / "profile.yaml")

    # Patch sessions module's imported references
    import jaybrain.sessions as sessions_mod
    monkeypatch.setattr(sessions_mod, "SESSIONS_DIR", data_dir / "sessions")
    monkeypatch.setattr(sessions_mod, "ACTIVE_SESSION_FILE", data_dir / ".active_session")

    # Homelab paths (file-based, isolated to tmp_path)
    homelab_root = tmp_path / "homelab"
    homelab_notes = homelab_root / "notes"
    homelab_journal = homelab_notes / "Journal"
    monkeypatch.setattr(config, "HOMELAB_ROOT", homelab_root)
    monkeypatch.setattr(config, "HOMELAB_NOTES_DIR", homelab_notes)
    monkeypatch.setattr(config, "HOMELAB_JOURNAL_DIR", homelab_journal)
    monkeypatch.setattr(config, "HOMELAB_JOURNAL_INDEX", homelab_journal / "JOURNAL_INDEX.md")
    monkeypatch.setattr(config, "HOMELAB_CODEX_PATH", homelab_notes / "LABSCRIBE_CODEX.md")
    monkeypatch.setattr(config, "HOMELAB_NEXUS_PATH", homelab_notes / "LAB_NEXUS.md")
    monkeypatch.setattr(config, "HOMELAB_TOOLS_CSV", homelab_root / "HOMELAB_TOOLS_INVENTORY.csv")
    monkeypatch.setattr(config, "HOMELAB_ATTACHMENTS_DIR", homelab_journal / "attachments")

    # Daemon paths (isolated to tmp_path)
    monkeypatch.setattr(config, "DAEMON_PID_FILE", data_dir / "daemon.pid")
    monkeypatch.setattr(config, "DAEMON_LOG_FILE", data_dir / "daemon.log")

    # Patch daemon module's imported DB_PATH reference
    try:
        import jaybrain.daemon as daemon_mod
        monkeypatch.setattr(daemon_mod, "DB_PATH", data_dir / "jaybrain.db")
    except ImportError:
        pass

    # Trash paths
    trash_dir = data_dir / "trash"
    monkeypatch.setattr(config, "TRASH_DIR", trash_dir)
    try:
        import jaybrain.trash as trash_mod
        monkeypatch.setattr(trash_mod, "TRASH_DIR", trash_dir)
    except ImportError:
        pass

    # Conversation archive paths
    monkeypatch.setattr(config, "CLAUDE_PROJECTS_DIR", tmp_path / "claude_projects")

    return data_dir
