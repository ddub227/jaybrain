"""Tests for the onboarding module."""

import json
from unittest.mock import patch, MagicMock

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db, now_iso


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestStartOnboarding:
    def test_start_fresh(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding

        result = start_onboarding()
        assert result["status"] == "started"
        assert result["current_step"] == 0
        assert result["total_steps"] > 0
        assert "question" in result["next_question"]

    def test_resume_existing(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding, answer_step

        start_onboarding()
        answer_step(0, "Joshua")

        result = start_onboarding()
        assert result["status"] == "resuming"
        assert result["current_step"] == 1
        assert "name" in result["completed_steps"]

    def test_already_completed(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding

        conn = get_connection()
        try:
            now = now_iso()
            conn.execute(
                """INSERT INTO onboarding_state
                (id, current_step, total_steps, responses, completed, started_at, completed_at)
                VALUES (1, 9, 9, '{}', 1, ?, ?)""",
                (now, now),
            )
            conn.commit()
        finally:
            conn.close()

        result = start_onboarding()
        assert result["status"] == "already_completed"


class TestAnswerStep:
    def test_answer_first_step(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding, answer_step

        start_onboarding()
        result = answer_step(0, "JJ")

        assert result["status"] == "recorded"
        assert result["step_completed"] == 0
        assert result["next_step"] == 1

    def test_answer_without_starting(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import answer_step

        result = answer_step(0, "JJ")
        assert "error" in result

    def test_invalid_step(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding, answer_step

        start_onboarding()
        result = answer_step(99, "test")
        assert "error" in result

    @patch("jaybrain.onboarding._process_completed_intake")
    def test_complete_all_steps(self, mock_process, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding, answer_step, INTAKE_QUESTIONS

        start_onboarding()

        for i in range(len(INTAKE_QUESTIONS)):
            result = answer_step(i, f"Answer for step {i}")

        assert result["status"] == "completed"
        mock_process.assert_called_once()


class TestGetProgress:
    def test_not_started(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import get_progress

        result = get_progress()
        assert result["status"] == "not_started"

    def test_in_progress(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import start_onboarding, answer_step, get_progress

        start_onboarding()
        answer_step(0, "JJ")
        answer_step(1, "Security Analyst")

        result = get_progress()
        assert result["status"] == "in_progress"
        assert result["current_step"] == 2
        assert len(result["completed_steps"]) == 2


class TestProcessCompletedIntake:
    def test_populates_profile_and_memories(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import _process_completed_intake

        responses = {
            "name": "Joshua",
            "current_role": "IT Support",
            "target_role": "SOC Analyst",
            "certifications": "Security+ SY0-701",
            "communication_style": "concise",
            "tech_stack": "Python, Linux",
        }

        with patch("jaybrain.profile.update_profile") as mock_profile, \
             patch("jaybrain.memory.remember") as mock_remember:
            _process_completed_intake(responses)

        # Profile should have been updated
        assert mock_profile.call_count >= 3

        # Memories should have been created
        assert mock_remember.call_count >= 2

    def test_generates_domains_from_priorities(self, temp_data_dir):
        _setup_db()
        from jaybrain.onboarding import _generate_initial_domains

        _generate_initial_domains("Career change, Health, Learning new skills, Family")

        conn = get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM life_domains").fetchone()[0]
            assert count == 4
        finally:
            conn.close()


class TestMigration11:
    def test_phase4_tables_exist(self, temp_data_dir):
        _setup_db()

        conn = get_connection()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "discovered_events" in tables
            assert "onboarding_state" in tables
            assert "personality_config" in tables
        finally:
            conn.close()
