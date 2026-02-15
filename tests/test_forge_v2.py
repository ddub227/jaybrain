"""Tests for SynapseForge v2 features: subjects, objectives, v2 scoring,
interleaved queue, readiness, calibration, error tracking."""

import json
from datetime import datetime, timezone

import pytest

from jaybrain.config import ensure_data_dirs, FORGE_MASTERY_DELTAS_V2
from jaybrain.db import (
    get_connection,
    init_db,
    get_forge_concept,
    get_forge_objectives,
    get_concepts_for_objective,
    get_error_patterns,
)
from jaybrain.forge import (
    _calculate_mastery_delta_v2,
    _classify_error,
    add_concept,
    add_objective,
    calculate_readiness,
    create_subject,
    generate_knowledge_map,
    get_calibration,
    get_error_analysis,
    get_study_queue,
    get_subjects,
    link_concept_to_objective,
    record_review,
)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Create a fresh database for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("jaybrain.config.DB_PATH", db_path)
    monkeypatch.setattr("jaybrain.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("jaybrain.config.FORGE_DIR", tmp_path / "forge")
    ensure_data_dirs()
    init_db()
    yield


@pytest.fixture
def subject():
    """Create a test subject."""
    return create_subject(
        name="Test Exam",
        short_name="TEST-101",
        pass_score=0.80,
        total_questions=50,
        time_limit_minutes=60,
    )


@pytest.fixture
def subject_with_objectives(subject):
    """Create a subject with two objectives and linked concepts."""
    obj1 = add_objective(subject["id"], "1.1", "Topic A", "Domain 1", 0.60)
    obj2 = add_objective(subject["id"], "2.1", "Topic B", "Domain 2", 0.40)

    c1 = add_concept("Term A", "Definition A", category="security",
                     tags=["1.1"], subject_id=subject["id"])
    c2 = add_concept("Term B", "Definition B", category="security",
                     tags=["1.1"], subject_id=subject["id"])
    c3 = add_concept("Term C", "Definition C", category="security",
                     tags=["2.1"], subject_id=subject["id"])

    link_concept_to_objective(c1.id, "1.1", subject["id"])
    link_concept_to_objective(c2.id, "1.1", subject["id"])
    link_concept_to_objective(c3.id, "2.1", subject["id"])

    return {
        "subject": subject,
        "objectives": [obj1, obj2],
        "concepts": [c1, c2, c3],
    }


class TestMasteryDeltaV2:
    def test_correct_confident(self):
        delta = _calculate_mastery_delta_v2(True, 5)
        assert delta == FORGE_MASTERY_DELTAS_V2["correct_confident"]

    def test_correct_unsure(self):
        delta = _calculate_mastery_delta_v2(True, 2)
        assert delta == FORGE_MASTERY_DELTAS_V2["correct_unsure"]

    def test_incorrect_confident(self):
        delta = _calculate_mastery_delta_v2(False, 4)
        assert delta == FORGE_MASTERY_DELTAS_V2["incorrect_confident"]

    def test_incorrect_unsure(self):
        delta = _calculate_mastery_delta_v2(False, 2)
        assert delta == FORGE_MASTERY_DELTAS_V2["incorrect_unsure"]


class TestErrorClassification:
    def test_misconception(self):
        assert _classify_error(False, 5, 0.3, 1, 3) == "misconception"

    def test_lapse(self):
        assert _classify_error(False, 2, 0.7, 3, 5) == "lapse"

    def test_slip(self):
        assert _classify_error(False, 2, 0.3, 2, 5) == "slip"

    def test_mistake(self):
        assert _classify_error(False, 2, 0.1, 0, 1) == "mistake"

    def test_correct_returns_empty(self):
        assert _classify_error(True, 5, 0.5, 3, 5) == ""


class TestSubjectManagement:
    def test_create_subject(self, subject):
        assert subject["name"] == "Test Exam"
        assert subject["short_name"] == "TEST-101"
        assert subject["pass_score"] == 0.80

    def test_list_subjects(self, subject):
        subjects = get_subjects()
        assert len(subjects) >= 1
        found = [s for s in subjects if s["id"] == subject["id"]]
        assert len(found) == 1

    def test_add_objective(self, subject):
        obj = add_objective(subject["id"], "1.1", "Test Objective", "Domain 1", 0.5)
        assert obj["code"] == "1.1"
        assert obj["exam_weight"] == 0.5

    def test_link_concept_to_objective(self, subject):
        add_objective(subject["id"], "1.1", "Test Objective", "Domain 1", 0.5)
        concept = add_concept("Test Term", "Test Def", category="security",
                              subject_id=subject["id"])
        result = link_concept_to_objective(concept.id, "1.1", subject["id"])
        assert result is True

        conn = get_connection()
        try:
            objs = get_forge_objectives(conn, subject["id"])
            concepts = get_concepts_for_objective(conn, objs[0]["id"])
            assert len(concepts) == 1
            assert concepts[0]["id"] == concept.id
        finally:
            conn.close()


class TestV2Review:
    def test_review_correct_confident(self):
        concept = add_concept("Test", "Def", category="security")
        updated = record_review(
            concept.id, "understood", confidence=5,
            was_correct=True,
        )
        assert updated.mastery_level == pytest.approx(0.20, abs=0.01)
        assert updated.correct_count == 1

    def test_review_incorrect_confident_creates_error(self):
        concept = add_concept("Test", "Def", category="security")
        updated = record_review(
            concept.id, "struggled", confidence=5,
            was_correct=False, notes="confused X with Y",
        )
        assert updated.mastery_level < 0.0 + 0.01  # clamped to 0

        conn = get_connection()
        try:
            errors = get_error_patterns(conn, concept_id=concept.id)
            assert len(errors) == 1
            assert errors[0]["error_type"] == "misconception"
        finally:
            conn.close()

    def test_v1_fallback_when_was_correct_none(self):
        concept = add_concept("Test", "Def", category="security")
        updated = record_review(concept.id, "understood", confidence=4)
        # Should use v1 delta (0.15)
        assert updated.mastery_level == pytest.approx(0.15, abs=0.01)


class TestInterleavedQueue:
    def test_interleaved_queue_returns_results(self, subject_with_objectives):
        data = subject_with_objectives
        queue = get_study_queue(subject_id=data["subject"]["id"], limit=10)
        assert "interleaved" in queue
        assert queue["total"] == 3

    def test_interleaved_queue_weights_by_exam_weight(self, subject_with_objectives):
        data = subject_with_objectives
        queue = get_study_queue(subject_id=data["subject"]["id"], limit=10)
        items = queue["interleaved"]
        # Domain 1 has weight 0.60 and all concepts at mastery 0, so it should
        # appear before Domain 2 (weight 0.40)
        assert items[0]["exam_weight"] == 0.60

    def test_fallback_queue_without_subject(self):
        add_concept("Fallback", "Def", category="security")
        queue = get_study_queue(limit=5)
        assert "new" in queue  # v1 format


class TestReadiness:
    def test_readiness_empty(self, subject_with_objectives):
        data = subject_with_objectives
        readiness = calculate_readiness(data["subject"]["id"])
        assert "overall" in readiness
        assert readiness["total_concepts"] == 3
        assert readiness["reviewed_concepts"] == 0
        assert readiness["coverage"] == 0.0

    def test_readiness_after_reviews(self, subject_with_objectives):
        data = subject_with_objectives
        for c in data["concepts"]:
            record_review(c.id, "understood", confidence=5, was_correct=True)
        readiness = calculate_readiness(data["subject"]["id"])
        assert readiness["coverage"] == 1.0
        assert readiness["avg_mastery"] > 0


class TestCalibration:
    def test_calibration_empty(self):
        cal = get_calibration()
        assert cal["total_reviews"] == 0
        assert cal["calibration_score"] == 0.0

    def test_calibration_after_reviews(self, subject_with_objectives):
        data = subject_with_objectives
        # 2 confident correct, 1 confident wrong
        record_review(data["concepts"][0].id, "understood", confidence=5,
                       was_correct=True)
        record_review(data["concepts"][1].id, "understood", confidence=4,
                       was_correct=True)
        record_review(data["concepts"][2].id, "struggled", confidence=4,
                       was_correct=False)

        cal = get_calibration(data["subject"]["id"])
        assert cal["total_reviews"] == 3
        assert cal["confident_correct"] == 2
        assert cal["confident_incorrect"] == 1
        assert cal["overconfidence_rate"] > 0


class TestKnowledgeMap:
    def test_knowledge_map_generates_markdown(self, subject_with_objectives):
        data = subject_with_objectives
        md = generate_knowledge_map(data["subject"]["id"])
        assert "# Knowledge Map: Test Exam" in md
        assert "Domain 1" in md
        assert "Term A" in md

    def test_knowledge_map_invalid_subject(self):
        md = generate_knowledge_map("nonexistent")
        assert "not found" in md.lower()


class TestErrorAnalysis:
    def test_error_analysis_empty(self):
        analysis = get_error_analysis()
        assert analysis["total_errors"] == 0

    def test_error_analysis_after_errors(self):
        concept = add_concept("Test", "Def", category="security")
        record_review(concept.id, "struggled", confidence=5,
                       was_correct=False, notes="confused A with B")
        record_review(concept.id, "struggled", confidence=5,
                       was_correct=False, notes="still confused")

        analysis = get_error_analysis(concept_id=concept.id)
        assert analysis["total_errors"] == 2
        assert "misconception" in analysis["by_type"]
        assert len(analysis["recurring_concepts"]) == 1
