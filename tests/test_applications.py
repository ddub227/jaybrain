"""Tests for the applications module (job application pipeline)."""

import pytest

from jaybrain.db import init_db, get_connection, insert_job_posting
from jaybrain.config import ensure_data_dirs
from jaybrain.applications import (
    create_application,
    modify_application,
    get_applications,
)
from jaybrain.models import ApplicationStatus


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


def _create_job(conn, job_id="job1", title="Engineer", company="Acme"):
    """Insert a job posting for testing."""
    insert_job_posting(
        conn, job_id, title, company,
        url="https://example.com",
        description="A great role",
        required_skills=["Python"],
        preferred_skills=["Docker"],
        salary_min=80000,
        salary_max=120000,
        job_type="full_time",
        work_mode="remote",
        location="Remote",
        board_id=None,
        tags=["tech"],
    )


class TestCreateApplication:
    def test_create_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application("job1")
        assert app.job_id == "job1"
        assert app.status == ApplicationStatus.DISCOVERED
        assert app.notes == ""
        assert app.tags == []
        assert len(app.id) == 12

    def test_create_with_fields(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application(
            "job1",
            status="preparing",
            notes="Looks promising",
            tags=["priority"],
        )
        assert app.status == ApplicationStatus.PREPARING
        assert app.notes == "Looks promising"
        assert app.tags == ["priority"]

    def test_create_job_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Job posting not found"):
            create_application("nonexistent")


class TestModifyApplication:
    def test_update_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application("job1")
        updated = modify_application(app.id, status="applied")
        assert updated is not None
        assert updated.status == ApplicationStatus.APPLIED

    def test_update_notes(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application("job1")
        updated = modify_application(app.id, notes="Had phone screen")
        assert updated.notes == "Had phone screen"

    def test_update_resume_path(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application("job1")
        updated = modify_application(app.id, resume_path="/path/to/resume.md")
        assert updated.resume_path == "/path/to/resume.md"

    def test_update_nonexistent(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = modify_application("nonexistent", status="applied")
        assert result is None

    def test_full_pipeline_flow(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn)
        conn.close()

        app = create_application("job1")
        assert app.status == ApplicationStatus.DISCOVERED

        app = modify_application(app.id, status="preparing")
        assert app.status == ApplicationStatus.PREPARING

        app = modify_application(app.id, status="ready",
                                  resume_path="/resume.md",
                                  cover_letter_path="/cover.md")
        assert app.status == ApplicationStatus.READY

        app = modify_application(app.id, status="applied",
                                  applied_date="2026-02-14")
        assert app.status == ApplicationStatus.APPLIED
        assert app.applied_date == "2026-02-14"

        app = modify_application(app.id, status="interviewing")
        assert app.status == ApplicationStatus.INTERVIEWING


class TestGetApplications:
    def test_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = get_applications()
        assert result["count"] == 0
        assert result["applications"] == []
        assert result["pipeline"] == {}

    def test_list_all(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn, "j1", "Role A", "CompA")
        _create_job(conn, "j2", "Role B", "CompB")
        conn.close()

        create_application("j1")
        create_application("j2")

        result = get_applications()
        assert result["count"] == 2

    def test_list_with_job_info(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn, "j1", "Senior Dev", "TechCorp")
        conn.close()

        create_application("j1")
        result = get_applications()
        app = result["applications"][0]
        assert app["job"]["title"] == "Senior Dev"
        assert app["job"]["company"] == "TechCorp"

    def test_filter_by_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn, "j1", "A", "X")
        _create_job(conn, "j2", "B", "Y")
        conn.close()

        a1 = create_application("j1")
        a2 = create_application("j2")
        modify_application(a2.id, status="applied")

        result = get_applications(status="applied")
        assert result["count"] == 1
        assert result["applications"][0]["status"] == "applied"

    def test_pipeline_summary(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        _create_job(conn, "j1", "A", "X")
        _create_job(conn, "j2", "B", "Y")
        _create_job(conn, "j3", "C", "Z")
        conn.close()

        a1 = create_application("j1")
        a2 = create_application("j2")
        a3 = create_application("j3")
        modify_application(a2.id, status="applied")
        modify_application(a3.id, status="applied")

        result = get_applications()
        assert result["pipeline"]["discovered"] == 1
        assert result["pipeline"]["applied"] == 2
