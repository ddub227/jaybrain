"""Tests for the interview_prep module."""

import pytest

from jaybrain.db import init_db, get_connection, insert_job_posting, insert_application
from jaybrain.config import ensure_data_dirs
from jaybrain.interview_prep import add_prep, get_prep_context
from jaybrain.models import InterviewPrepType
import jaybrain.interview_prep as prep_mod


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


def _create_job_and_app(conn, job_id="j1", app_id="a1"):
    """Create a job posting and application for testing."""
    insert_job_posting(
        conn, job_id, "Engineer", "Acme",
        url="https://acme.com/jobs/1",
        description="Build stuff",
        required_skills=["Python", "SQL"],
        preferred_skills=["Docker"],
        salary_min=90000, salary_max=130000,
        job_type="full_time", work_mode="remote",
        location="Remote", board_id=None, tags=[],
    )
    insert_application(conn, app_id, job_id, "discovered", "", [])


class TestAddPrep:
    def test_add_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        prep = add_prep("a1", content="Tell me about yourself...")
        assert prep.application_id == "a1"
        assert prep.prep_type == InterviewPrepType.GENERAL
        assert "Tell me about yourself" in prep.content
        assert len(prep.id) == 12

    def test_add_with_type(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        prep = add_prep("a1", prep_type="technical", content="SQL joins explanation")
        assert prep.prep_type == InterviewPrepType.TECHNICAL

    def test_add_with_tags(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        prep = add_prep("a1", content="STAR format", tags=["behavioral"])
        assert prep.tags == ["behavioral"]

    def test_add_app_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Application not found"):
            add_prep("nonexistent", content="Nope")

    def test_add_multiple_types(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        add_prep("a1", prep_type="general", content="Intro")
        add_prep("a1", prep_type="technical", content="Coding")
        add_prep("a1", prep_type="behavioral", content="STAR")
        add_prep("a1", prep_type="company_research", content="Acme history")


class TestGetPrepContext:
    def test_basic_context(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        # Patch profile module's PROFILE_PATH for isolation
        import jaybrain.profile as profile_mod
        import jaybrain.config as config
        monkeypatch.setattr(profile_mod, "PROFILE_PATH", config.PROFILE_PATH)

        add_prep("a1", prep_type="general", content="General prep")
        add_prep("a1", prep_type="technical", content="Tech prep")

        ctx = get_prep_context("a1")
        assert ctx["application"]["id"] == "a1"
        assert ctx["job"]["title"] == "Engineer"
        assert ctx["job"]["company"] == "Acme"
        assert ctx["job"]["required_skills"] == ["Python", "SQL"]
        assert ctx["prep_count"] == 2
        assert "general" in ctx["prep"]
        assert "technical" in ctx["prep"]

    def test_context_app_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Application not found"):
            get_prep_context("nonexistent")

    def test_context_includes_profile(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job_and_app(conn)
        conn.close()

        import jaybrain.profile as profile_mod
        import jaybrain.config as config
        monkeypatch.setattr(profile_mod, "PROFILE_PATH", config.PROFILE_PATH)

        ctx = get_prep_context("a1")
        assert "name" in ctx["profile"]
        assert ctx["profile"]["name"] == "Joshua"
