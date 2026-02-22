"""Tests for resume tailoring, skill analysis, and interview prep."""

from pathlib import Path

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import (
    get_connection,
    get_interview_prep_for_app,
    init_db,
    insert_application,
    insert_interview_prep,
    insert_job_posting,
)
from jaybrain.jobs import add_job
from jaybrain.applications import create_application
from jaybrain.resume_tailor import (
    analyze_fit,
    get_template,
    save_cover_letter,
    save_tailored_resume,
    _safe_filename,
    _extract_skills_from_template,
)
from jaybrain.interview_prep import add_prep, get_prep_context


def _setup_db(temp_data_dir):
    """Helper to init DB for each test."""
    ensure_data_dirs()
    init_db()


class TestResumeTemplate:
    def test_no_template(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = get_template()
        assert result["status"] == "no_template"

    def test_template_exists(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod

        template_path = config.JOB_SEARCH_DIR / "resume_template.md"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text("# Test User\n<!-- SUMMARY -->\nSummary here\n<!-- /SUMMARY -->", encoding="utf-8")
        monkeypatch.setattr(resume_mod, "RESUME_TEMPLATE_PATH", template_path)

        result = get_template()
        assert result["status"] == "ok"
        assert "Test User" in result["content"]

    def test_extract_skills_from_template(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod

        template_path = config.JOB_SEARCH_DIR / "resume_template.md"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_content = (
            "# Resume\n"
            "<!-- SKILLS -->\n"
            "- Python\n"
            "- JavaScript\n"
            "- AWS\n"
            "- Docker\n"
            "<!-- /SKILLS -->\n"
        )
        template_path.write_text(template_content, encoding="utf-8")
        monkeypatch.setattr(resume_mod, "RESUME_TEMPLATE_PATH", template_path)

        skills = _extract_skills_from_template()
        assert "Python" in skills
        assert "JavaScript" in skills
        assert "AWS" in skills

    def test_extract_skills_no_markers(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod

        template_path = config.JOB_SEARCH_DIR / "resume_template.md"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text("# Resume\nNo skills section here", encoding="utf-8")
        monkeypatch.setattr(resume_mod, "RESUME_TEMPLATE_PATH", template_path)

        skills = _extract_skills_from_template()
        assert skills == []


class TestSkillAnalysis:
    def test_analyze_fit_with_template(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod

        template_path = config.JOB_SEARCH_DIR / "resume_template.md"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(
            "<!-- SKILLS -->\n- Python\n- AWS\n- Linux\n<!-- /SKILLS -->",
            encoding="utf-8",
        )
        monkeypatch.setattr(resume_mod, "RESUME_TEMPLATE_PATH", template_path)

        posting = add_job(
            "SOC Analyst", "SecCo",
            required_skills=["Python", "SIEM", "Linux"],
            preferred_skills=["AWS", "Splunk"],
        )
        result = analyze_fit(posting.id)
        assert result["job_id"] == posting.id
        assert result["company"] == "SecCo"
        assert "python" in result["required_matches"]
        assert "linux" in result["required_matches"]
        assert "siem" in result["required_gaps"]
        assert "aws" in result["preferred_matches"]
        assert result["overall_fit_score"] > 0
        assert result["overall_fit_score"] <= 1.0

    def test_analyze_fit_no_skills(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job(
            "Generic Role", "Corp",
            required_skills=["Python"],
        )
        result = analyze_fit(posting.id)
        # No template, so no skills matched -- required_score is 0
        assert result["required_match_pct"] == 0.0

    def test_analyze_fit_job_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Job posting not found"):
            analyze_fit("nonexistent")

    def test_analyze_fit_no_required_skills(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job("Easy Role", "EasyCo")
        result = analyze_fit(posting.id)
        # No required or preferred skills means 100% match by default
        assert result["required_match_pct"] == 100.0
        assert result["preferred_match_pct"] == 100.0
        assert result["overall_fit_score"] == 1.0


class TestSaveTailoredDocuments:
    def test_save_tailored_resume(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod
        monkeypatch.setattr(resume_mod, "JOB_SEARCH_DIR", config.JOB_SEARCH_DIR)

        result = save_tailored_resume("Acme Corp", "SOC Analyst", "# Tailored Resume\nContent here")
        assert result["status"] == "saved"
        assert "Acmecorp" in result["filename"] or "AcmeCorp" in result["filename"]
        assert "Resume_" in result["filename"]
        assert Path(result["path"]).exists()
        content = Path(result["path"]).read_text(encoding="utf-8")
        assert "Tailored Resume" in content

    def test_save_cover_letter(self, temp_data_dir, monkeypatch):
        _setup_db(temp_data_dir)
        import jaybrain.config as config
        import jaybrain.resume_tailor as resume_mod
        monkeypatch.setattr(resume_mod, "JOB_SEARCH_DIR", config.JOB_SEARCH_DIR)

        result = save_cover_letter("BigTech", "Security Engineer", "Dear Hiring Manager...")
        assert result["status"] == "saved"
        assert "CoverLetter_" in result["filename"]
        assert result["filename"].endswith(".md")
        assert Path(result["path"]).exists()

    def test_safe_filename(self):
        assert _safe_filename("Acme Corp") == "AcmeCorp"
        assert _safe_filename("SOC Analyst") == "SocAnalyst"
        assert _safe_filename("simple") == "Simple"


class TestInterviewPrepCRUD:
    def test_insert_and_get_prep(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j200", "Test", "Co", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_application(conn, "a200", "j200", "interviewing", "", [])
            insert_interview_prep(conn, "p001", "a200", "technical", "Explain TCP/IP", ["networking"])
            rows = get_interview_prep_for_app(conn, "a200")
            assert len(rows) == 1
            assert rows[0]["prep_type"] == "technical"
            assert rows[0]["content"] == "Explain TCP/IP"
        finally:
            conn.close()

    def test_multiple_prep_types(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_job_posting(
                conn, "j201", "Test", "Co", "", "",
                [], [], None, None, "full_time", "remote", "", None, [],
            )
            insert_application(conn, "a201", "j201", "interviewing", "", [])
            insert_interview_prep(conn, "p010", "a201", "technical", "Tech content", [])
            insert_interview_prep(conn, "p011", "a201", "behavioral", "STAR method", [])
            insert_interview_prep(conn, "p012", "a201", "company_research", "Founded in...", [])
            rows = get_interview_prep_for_app(conn, "a201")
            assert len(rows) == 3
        finally:
            conn.close()


class TestInterviewPrepModule:
    def test_add_prep(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job("Test", "Co")
        app = create_application(posting.id)
        prep = add_prep(app.id, "technical", "Explain BGP routing", ["networking"])
        assert prep.application_id == app.id
        assert prep.prep_type.value == "technical"
        assert prep.content == "Explain BGP routing"

    def test_add_prep_invalid_application(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Application not found"):
            add_prep("nonexistent", "general", "content")

    def test_get_prep_context(self, temp_data_dir):
        _setup_db(temp_data_dir)
        posting = add_job(
            "Security Analyst", "DefenseCo",
            description="Monitor SIEM alerts",
            required_skills=["SIEM", "Python"],
        )
        app = create_application(posting.id, notes="Strong match")
        add_prep(app.id, "technical", "SIEM tool comparison")
        add_prep(app.id, "behavioral", "Tell me about a time you handled an incident")
        add_prep(app.id, "company_research", "DefenseCo is a leading cybersecurity firm")

        context = get_prep_context(app.id)
        assert context["application"]["id"] == app.id
        assert context["job"]["title"] == "Security Analyst"
        assert context["job"]["company"] == "DefenseCo"
        assert context["prep_count"] == 3
        assert "technical" in context["prep"]
        assert "behavioral" in context["prep"]
        assert "company_research" in context["prep"]

    def test_get_prep_context_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Application not found"):
            get_prep_context("nonexistent")
