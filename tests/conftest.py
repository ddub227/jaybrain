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

    # Also patch the db module's reference to DB_PATH
    import jaybrain.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", data_dir / "jaybrain.db")

    return data_dir
