"""Tests for job boards, postings, and applications."""

from datetime import datetime

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import (
    get_application,
    get_application_pipeline,
    get_connection,
    get_job_board,
    get_job_posting,
    init_db,
    insert_application,
    insert_job_board,
    insert_job_posting,
    list_applications,
    list_job_boards,
    list_job_postings,
    search_job_postings_fts,
    update_application,
    update_job_board,
)
from jaybrain.job_boards import add_board, get_boards, _parse_board_row
from jaybrain.jobs import add_job, get_job, search_jobs, _parse_posting_row
from jaybrain.applications import create_application, modify_application, get_applications


def _setup_db(temp_data_dir):
    """Helper to init DB for each test."""
    ensure_data_dirs()
    init_db()


class TestJobBoardCRUD:
    def test_insert_and_get_board(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_board(conn, "b001", "RemoteOK", "https://remoteok.com", "general", ["remote"])
            row = get_job_board(conn, "b001")
            assert row is not None
            assert row["name"] == "RemoteOK"
            assert row["url"] == "https://remoteok.com"
            assert row["board_type"] == "general"
            assert row["active"] == 1
        finally:
            conn.close()

    def test_list_boards_active_only(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_board(conn, "b010", "Active", "https://a.com", "general", [])
            insert_job_board(conn, "b011", "Inactive", "https://b.com", "general", [])
            update_job_board(conn, "b011", active=0)
            active = list_job_boards(conn, active_only=True)
            all_boards = list_job_boards(conn, active_only=False)
            assert len(active) == 1
            assert len(all_boards) == 2
        finally:
            conn.close()

    def test_update_board(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_board(conn, "b020", "Board", "https://old.com", "general", [])
            update_job_board(conn, "b020", name="Updated Board", tags=["new"])
            row = get_job_board(conn, "b020")
            assert row["name"] == "Updated Board"
        finally:
            conn.close()


class TestJobBoardModule:
    def test_add_board(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board("TestBoard", "https://test.com", "niche", ["security"])
        assert board.name == "TestBoard"
        assert board.url == "https://test.com"
        assert board.board_type == "niche"
        assert "security" in board.tags

    def test_get_boards(self, temp_data_dir):
        _setup_db(temp_data_dir)
        add_board("Board1", "https://one.com")
        add_board("Board2", "https://two.com")
        boards = get_boards()
        assert len(boards) == 2


class TestJobPostingCRUD:
    def test_insert_and_get_posting(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j001", "SOC Analyst", "Acme Corp", "https://acme.com/jobs/1",
                "Analyze security events...", ["SIEM", "Python"],
                ["Splunk", "AWS"], 80000, 120000,
                "full_time", "remote", "", None, ["security"],
            )
            row = get_job_posting(conn, "j001")
            assert row is not None
            assert row["title"] == "SOC Analyst"
            assert row["company"] == "Acme Corp"
            assert row["salary_min"] == 80000
        finally:
            conn.close()

    def test_list_postings_by_work_mode(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j010", "Remote Job", "Co1", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_job_posting(
                conn, "j011", "Onsite Job", "Co2", "", "",
                [], [], None, None, "full_time", "onsite", "NYC", None, [],
            )
            remote = list_job_postings(conn, work_mode="remote")
            assert len(remote) == 1
            assert remote[0]["id"] == "j010"
        finally:
            conn.close()

    def test_fts_search_by_title(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j020", "Security Engineer", "BigCo", "", "Design and implement security...",
                ["Python", "AWS"], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_job_posting(
                conn, "j021", "Data Scientist", "DataCo", "", "Build ML models...",
                ["Python", "TensorFlow"], [], None, None, "full_time", "remote", "", None, [],
            )
            results = search_job_postings_fts(conn, '"Security"')
            ids = [r[0] for r in results]
            assert "j020" in ids
            assert "j021" not in ids
        finally:
            conn.close()

    def test_fts_search_by_skills(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j030", "DevOps", "Ops Inc", "", "",
                ["Kubernetes", "Docker"], ["Terraform"], None, None,
                "full_time", "remote", "", None, [],
            )
            results = search_job_postings_fts(conn, '"Kubernetes"')
            ids = [r[0] for r in results]
            assert "j030" in ids
        finally:
            conn.close()


class TestJobsModule:
    def test_add_job(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job(
            "Pen Tester", "SecCo",
            url="https://secco.com/jobs/1",
            required_skills=["Burp Suite", "Python"],
            work_mode="remote",
        )
        assert posting.title == "Pen Tester"
        assert posting.company == "SecCo"
        assert "Burp Suite" in posting.required_skills

    def test_get_job(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job("Analyst", "Corp")
        result = get_job(posting.id)
        assert result is not None
        assert result.title == "Analyst"

    def test_get_job_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        assert get_job("nonexistent") is None

    def test_search_jobs_by_query(self, temp_data_dir):
        _setup_db(temp_data_dir)
        add_job("Network Engineer", "NetCo", description="Configure routers and switches")
        add_job("Software Dev", "DevCo", description="Build web applications")
        results = search_jobs(query="routers")
        assert len(results) >= 1
        assert results[0].title == "Network Engineer"

    def test_search_jobs_no_query(self, temp_data_dir):
        _setup_db(temp_data_dir)
        add_job("Job1", "Co1")
        add_job("Job2", "Co2")
        results = search_jobs()
        assert len(results) == 2


class TestApplicationCRUD:
    def test_insert_and_get_application(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j100", "Test Job", "TestCo", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_application(conn, "a001", "j100", "discovered", "Looks interesting", ["security"])
            row = get_application(conn, "a001")
            assert row is not None
            assert row["job_id"] == "j100"
            assert row["status"] == "discovered"
        finally:
            conn.close()

    def test_update_application(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j101", "Test Job", "TestCo", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_application(conn, "a010", "j101", "discovered", "", [])
            update_application(conn, "a010", status="applied", applied_date="2026-02-09")
            row = get_application(conn, "a010")
            assert row["status"] == "applied"
            assert row["applied_date"] == "2026-02-09"
        finally:
            conn.close()

    def test_pipeline_counts(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j110", "Job A", "Co", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_job_posting(
                conn, "j111", "Job B", "Co", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_application(conn, "a020", "j110", "discovered", "", [])
            insert_application(conn, "a021", "j110", "applied", "", [])
            insert_application(conn, "a022", "j111", "applied", "", [])
            pipeline = get_application_pipeline(conn)
            assert pipeline["discovered"] == 1
            assert pipeline["applied"] == 2
        finally:
            conn.close()


class TestApplicationsModule:
    def test_create_application(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job("Test", "TestCo")
        app = create_application(posting.id, notes="Good fit")
        assert app.job_id == posting.id
        assert app.status.value == "discovered"
        assert app.notes == "Good fit"

    def test_create_application_invalid_job(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Job posting not found"):
            create_application("nonexistent")

    def test_modify_application(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job("Test", "TestCo")
        app = create_application(posting.id)
        updated = modify_application(app.id, status="preparing", notes="Working on resume")
        assert updated.status.value == "preparing"
        assert updated.notes == "Working on resume"

    def test_modify_application_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        assert modify_application("nonexistent", status="applied") is None

    def test_get_applications_with_pipeline(self, temp_data_dir):
        _setup_db(temp_data_dir)
        p1 = add_job("Job1", "Co1")
        p2 = add_job("Job2", "Co2")
        create_application(p1.id)
        app2 = create_application(p2.id)
        modify_application(app2.id, status="applied", applied_date="2026-02-09")
        result = get_applications()
        assert result["count"] == 2
        assert "pipeline" in result
        assert result["pipeline"]["discovered"] == 1
        assert result["pipeline"]["applied"] == 1

    def test_get_applications_filter_by_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        p1 = add_job("Job1", "Co1")
        p2 = add_job("Job2", "Co2")
        create_application(p1.id)
        app2 = create_application(p2.id)
        modify_application(app2.id, status="applied")
        result = get_applications(status="applied")
        assert result["count"] == 1
        assert result["applications"][0]["status"] == "applied"
