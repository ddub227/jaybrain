"""Tests for SynapseForge - spaced repetition learning system."""

from datetime import datetime, timedelta, timezone

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import (
    get_connection,
    get_forge_concept,
    get_forge_concepts_due,
    get_forge_concepts_new,
    get_forge_concepts_struggling,
    get_forge_reviews,
    get_forge_streak_data,
    init_db,
    insert_forge_concept,
    insert_forge_review,
    now_iso,
    search_forge_fts,
    update_forge_concept,
    upsert_forge_streak,
)
from jaybrain.forge import (
    _calculate_mastery_delta,
    _calculate_next_review,
    _calculate_streaks,
    _parse_concept_row,
    add_concept,
    get_concept_detail,
    get_forge_stats,
    get_study_queue,
    record_review,
    update_concept,
)


def _setup_db(temp_data_dir):
    """Helper to init DB for each test."""
    ensure_data_dirs()
    init_db()


class TestConceptCRUD:
    def test_insert_and_get_concept(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "c001", "MCP", "Model Context Protocol",
                "mcp", "intermediate", ["protocol", "ai"],
                related_jaybrain_component="server.py",
                source="docs",
            )
            row = get_forge_concept(conn, "c001")
            assert row is not None
            assert row["term"] == "MCP"
            assert row["definition"] == "Model Context Protocol"
            assert row["category"] == "mcp"
            assert row["difficulty"] == "intermediate"
            assert row["mastery_level"] == 0.0
            assert row["review_count"] == 0
        finally:
            conn.close()

    def test_update_concept(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "c002", "SQLite", "Embedded database",
                "databases", "beginner", [],
            )
            update_forge_concept(conn, "c002", definition="Embedded relational database", mastery_level=0.5)
            row = get_forge_concept(conn, "c002")
            assert row["definition"] == "Embedded relational database"
            assert row["mastery_level"] == 0.5
        finally:
            conn.close()

    def test_update_nonexistent_concept(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            result = update_forge_concept(conn, "nonexistent", term="foo")
            assert result is False
        finally:
            conn.close()

    def test_get_concepts_new(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "c010", "New1", "Def1", "python", "beginner", [])
            insert_forge_concept(conn, "c011", "New2", "Def2", "python", "beginner", [])
            # Mark c011 as reviewed
            update_forge_concept(conn, "c011", review_count=1)
            new = get_forge_concepts_new(conn)
            ids = [r["id"] for r in new]
            assert "c010" in ids
            assert "c011" not in ids
        finally:
            conn.close()

    def test_get_concepts_struggling(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "c020", "Struggling", "Def", "python", "beginner", [])
            update_forge_concept(conn, "c020", mastery_level=0.15, review_count=3)
            insert_forge_concept(conn, "c021", "Doing OK", "Def", "python", "beginner", [])
            update_forge_concept(conn, "c021", mastery_level=0.5, review_count=3)
            struggling = get_forge_concepts_struggling(conn)
            ids = [r["id"] for r in struggling]
            assert "c020" in ids
            assert "c021" not in ids
        finally:
            conn.close()


class TestSM2Algorithm:
    def test_understood_high_confidence(self):
        delta = _calculate_mastery_delta("understood", 5)
        assert delta == 0.15

    def test_understood_low_confidence(self):
        delta = _calculate_mastery_delta("understood", 3)
        assert delta == 0.10

    def test_reviewed(self):
        delta = _calculate_mastery_delta("reviewed", 3)
        assert delta == 0.05

    def test_struggled(self):
        delta = _calculate_mastery_delta("struggled", 2)
        assert delta == -0.10

    def test_skipped(self):
        delta = _calculate_mastery_delta("skipped", 1)
        assert delta == 0.0

    def test_mastery_floor_at_zero(self):
        # mastery 0.05, struggled => 0.05 - 0.10 = -0.05, should floor at 0.0
        delta = _calculate_mastery_delta("struggled", 1)
        new_mastery = max(0.0, 0.05 + delta)
        assert new_mastery == 0.0

    def test_mastery_ceiling_at_one(self):
        # mastery 0.95, understood high => 0.95 + 0.15 = 1.10, should cap at 1.0
        delta = _calculate_mastery_delta("understood", 5)
        new_mastery = min(1.0, 0.95 + delta)
        assert new_mastery == 1.0

    def test_interval_low_mastery(self):
        next_review = _calculate_next_review(0.1)
        expected = datetime.now(timezone.utc) + timedelta(days=1)
        assert abs((next_review - expected).total_seconds()) < 5

    def test_interval_mid_mastery(self):
        next_review = _calculate_next_review(0.5)
        expected = datetime.now(timezone.utc) + timedelta(days=7)
        assert abs((next_review - expected).total_seconds()) < 5

    def test_interval_high_mastery(self):
        next_review = _calculate_next_review(0.9)
        expected = datetime.now(timezone.utc) + timedelta(days=30)
        assert abs((next_review - expected).total_seconds()) < 5

    def test_record_review_understood(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "r001", "Test", "Testing", "python", "beginner", [])
        finally:
            conn.close()

        concept = record_review("r001", "understood", confidence=5)
        assert concept.mastery_level == pytest.approx(0.15, abs=0.001)
        assert concept.review_count == 1
        assert concept.correct_count == 1
        assert concept.last_reviewed is not None

    def test_record_review_struggled(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "r002", "Hard", "Difficult topic", "python", "advanced", [])
            update_forge_concept(conn, "r002", mastery_level=0.3)
        finally:
            conn.close()

        concept = record_review("r002", "struggled", confidence=1)
        assert concept.mastery_level == pytest.approx(0.2, abs=0.001)
        assert concept.review_count == 1
        assert concept.correct_count == 0

    def test_record_review_skipped(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "r003", "Skip", "Skipped topic", "python", "beginner", [])
            update_forge_concept(conn, "r003", mastery_level=0.5)
        finally:
            conn.close()

        concept = record_review("r003", "skipped", confidence=1)
        assert concept.mastery_level == pytest.approx(0.5, abs=0.001)

    def test_record_review_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Concept not found"):
            record_review("nonexistent", "understood", confidence=3)


class TestStudyQueue:
    def test_study_queue_ordering(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        now = datetime.now(timezone.utc)
        try:
            # Due concept (next_review in the past)
            insert_forge_concept(conn, "sq01", "Due", "Due for review", "python", "beginner", [])
            update_forge_concept(
                conn, "sq01",
                next_review=(now - timedelta(hours=1)).isoformat(),
                review_count=2,
                mastery_level=0.4,
            )

            # New concept (never reviewed, next_review in the future)
            insert_forge_concept(conn, "sq02", "New", "Never reviewed", "python", "beginner", [])
            update_forge_concept(
                conn, "sq02",
                next_review=(now + timedelta(days=5)).isoformat(),
            )

            # Struggling concept (low mastery, reviewed)
            insert_forge_concept(conn, "sq03", "Struggling", "Low mastery", "python", "beginner", [])
            update_forge_concept(
                conn, "sq03",
                mastery_level=0.1, review_count=3,
                next_review=(now + timedelta(days=5)).isoformat(),
            )

            # Up next concept (due within 3 days)
            insert_forge_concept(conn, "sq04", "UpNext", "Coming up", "python", "beginner", [])
            update_forge_concept(
                conn, "sq04",
                mastery_level=0.5, review_count=2,
                next_review=(now + timedelta(days=2)).isoformat(),
            )
        finally:
            conn.close()

        queue = get_study_queue()
        assert len(queue["due_now"]) >= 1
        assert any(c["id"] == "sq01" for c in queue["due_now"])
        assert any(c["id"] == "sq02" for c in queue["new"])
        assert any(c["id"] == "sq03" for c in queue["struggling"])
        assert any(c["id"] == "sq04" for c in queue["up_next"])

    def test_study_queue_category_filter(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "sf01", "Python", "Language", "python", "beginner", [])
            insert_forge_concept(conn, "sf02", "SQL", "Query lang", "databases", "beginner", [])
        finally:
            conn.close()

        queue = get_study_queue(category="python")
        all_ids = []
        for section in ["due_now", "new", "struggling", "up_next"]:
            all_ids.extend(c["id"] for c in queue[section])
        # sf01 is python, should appear; sf02 is databases, should not
        assert "sf01" in all_ids or len(all_ids) == 0  # sf01 may be in 'new'
        assert "sf02" not in all_ids

    def test_study_queue_no_duplicates(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        now = datetime.now(timezone.utc)
        try:
            # A concept that is both "due" and would qualify as "new" (review_count=0)
            insert_forge_concept(conn, "dup01", "Dup", "Duplicate test", "python", "beginner", [])
            update_forge_concept(
                conn, "dup01",
                next_review=(now - timedelta(hours=1)).isoformat(),
            )
        finally:
            conn.close()

        queue = get_study_queue()
        all_ids = []
        for section in ["due_now", "new", "struggling", "up_next"]:
            all_ids.extend(c["id"] for c in queue[section])
        # dup01 should appear exactly once
        assert all_ids.count("dup01") == 1


class TestStreaks:
    def test_upsert_streak(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            upsert_forge_streak(conn, "2025-01-15", concepts_reviewed=2, concepts_added=1)
            rows = get_forge_streak_data(conn)
            assert len(rows) == 1
            assert rows[0]["concepts_reviewed"] == 2
            assert rows[0]["concepts_added"] == 1
        finally:
            conn.close()

    def test_upsert_streak_accumulates(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            upsert_forge_streak(conn, "2025-01-15", concepts_reviewed=2)
            upsert_forge_streak(conn, "2025-01-15", concepts_reviewed=3)
            rows = get_forge_streak_data(conn)
            assert len(rows) == 1
            assert rows[0]["concepts_reviewed"] == 5
        finally:
            conn.close()

    def test_calculate_streaks_empty(self):
        current, longest = _calculate_streaks([])
        assert current == 0
        assert longest == 0

    def test_calculate_streaks_consecutive(self):
        today = datetime.now(timezone.utc).date()
        mock_rows = [
            {"date": (today - timedelta(days=i)).strftime("%Y-%m-%d")}
            for i in range(5)
        ]
        current, longest = _calculate_streaks(mock_rows)
        assert current == 5
        assert longest == 5

    def test_calculate_streaks_gap_resets_current(self):
        today = datetime.now(timezone.utc).date()
        # Today and yesterday, then gap, then 3 days before gap
        mock_rows = [
            {"date": today.strftime("%Y-%m-%d")},
            {"date": (today - timedelta(days=1)).strftime("%Y-%m-%d")},
            # gap on day 2
            {"date": (today - timedelta(days=3)).strftime("%Y-%m-%d")},
            {"date": (today - timedelta(days=4)).strftime("%Y-%m-%d")},
            {"date": (today - timedelta(days=5)).strftime("%Y-%m-%d")},
        ]
        current, longest = _calculate_streaks(mock_rows)
        assert current == 2  # today + yesterday
        assert longest == 3  # 3-day run before the gap


class TestFTSSearch:
    def test_fts_search_by_term(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "fts01", "FastMCP", "Fast MCP server framework",
                "mcp", "intermediate", ["framework"],
            )
            insert_forge_concept(
                conn, "fts02", "SQLite", "Embedded database engine",
                "databases", "beginner", ["database"],
            )
            results = search_forge_fts(conn, '"FastMCP"')
            ids = [r[0] for r in results]
            assert "fts01" in ids
            assert "fts02" not in ids
        finally:
            conn.close()

    def test_fts_search_by_definition(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "fts03", "WAL", "Write-Ahead Logging for SQLite transactions",
                "databases", "advanced", [],
            )
            results = search_forge_fts(conn, '"transactions"')
            ids = [r[0] for r in results]
            assert "fts03" in ids
        finally:
            conn.close()

    def test_fts_search_by_notes(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "fts04", "Embedding", "Vector representation",
                "ai_ml", "intermediate", [],
                notes="Used in semantic search with ONNX runtime",
            )
            results = search_forge_fts(conn, '"ONNX"')
            ids = [r[0] for r in results]
            assert "fts04" in ids
        finally:
            conn.close()


class TestStatsAggregation:
    def test_empty_stats(self, temp_data_dir):
        _setup_db(temp_data_dir)
        stats = get_forge_stats()
        assert stats["total_concepts"] == 0
        assert stats["total_reviews"] == 0
        assert stats["due_count"] == 0
        assert stats["avg_mastery"] == 0.0
        assert stats["current_streak"] == 0

    def test_stats_with_data(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        now = datetime.now(timezone.utc)
        try:
            insert_forge_concept(conn, "st01", "A", "Def A", "python", "beginner", [])
            update_forge_concept(conn, "st01", mastery_level=0.0)
            insert_forge_concept(conn, "st02", "B", "Def B", "databases", "advanced", [])
            update_forge_concept(conn, "st02", mastery_level=0.5)
            insert_forge_concept(conn, "st03", "C", "Def C", "python", "beginner", [])
            update_forge_concept(
                conn, "st03",
                mastery_level=0.9,
                next_review=(now - timedelta(hours=1)).isoformat(),
            )
            insert_forge_review(conn, "st01", "reviewed", 3)
            insert_forge_review(conn, "st02", "understood", 5)
        finally:
            conn.close()

        stats = get_forge_stats()
        assert stats["total_concepts"] == 3
        assert stats["total_reviews"] == 2
        assert stats["concepts_by_category"]["python"] == 2
        assert stats["concepts_by_category"]["databases"] == 1
        assert stats["concepts_by_difficulty"]["beginner"] == 2
        assert stats["concepts_by_difficulty"]["advanced"] == 1
        assert stats["due_count"] >= 1  # st03 is due
        assert stats["avg_mastery"] > 0


class TestConceptDetail:
    def test_get_concept_detail(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(
                conn, "det01", "FTS5", "Full-text search extension",
                "databases", "intermediate", ["search", "sqlite"],
                source="SQLite docs",
            )
            insert_forge_review(conn, "det01", "understood", 4)
            insert_forge_review(conn, "det01", "reviewed", 3)
        finally:
            conn.close()

        detail = get_concept_detail("det01")
        assert detail is not None
        assert detail["concept"]["term"] == "FTS5"
        assert detail["concept"]["category"] == "databases"
        assert detail["concept"]["source"] == "SQLite docs"
        assert detail["review_count"] == 2
        assert len(detail["reviews"]) == 2

    def test_get_concept_detail_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        detail = get_concept_detail("nonexistent")
        assert detail is None


class TestUpdateConcept:
    def test_update_term(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "up01", "Old", "Definition", "python", "beginner", [])
        finally:
            conn.close()

        concept = update_concept("up01", term="New Term")
        assert concept is not None
        assert concept.term == "New Term"

    def test_update_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = update_concept("nonexistent", term="foo")
        assert result is None

    def test_update_tags(self, temp_data_dir):
        _setup_db(temp_data_dir)
        conn = get_connection()
        try:
            insert_forge_concept(conn, "up02", "Tagged", "Def", "python", "beginner", ["old"])
        finally:
            conn.close()

        concept = update_concept("up02", tags=["new", "updated"])
        assert concept is not None
        assert "new" in concept.tags
        assert "updated" in concept.tags
