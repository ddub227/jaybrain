"""SynapseForge - Personal learning tutor with spaced repetition.

The place where new neural connections are forged. Captures concepts
encountered while building JayBrain, tracks mastery over time using
SM-2 spaced repetition, and provides study queue prioritization.

Mastery levels: Spark > Ember > Flame > Blaze > Inferno > Forged
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import (
    DEFAULT_SEARCH_LIMIT,
    FORGE_INTERVALS,
    FORGE_MASTERY_DELTAS,
    SEARCH_CANDIDATES,
)
from .db import (
    get_connection,
    get_forge_concept,
    get_forge_concepts_due,
    get_forge_concepts_new,
    get_forge_concepts_struggling,
    get_forge_reviews,
    get_forge_streak_data,
    insert_forge_concept,
    insert_forge_review,
    search_forge_fts,
    search_forge_vec,
    update_forge_concept,
    upsert_forge_streak,
)
from .models import Concept, ConceptCategory, ConceptDifficulty, ForgeStats, Review, ReviewOutcome

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_concept_row(row) -> Concept:
    """Convert a database row to a Concept model."""
    return Concept(
        id=row["id"],
        term=row["term"],
        definition=row["definition"],
        category=ConceptCategory(row["category"]),
        difficulty=ConceptDifficulty(row["difficulty"]),
        tags=json.loads(row["tags"]),
        related_jaybrain_component=row["related_jaybrain_component"],
        source=row["source"],
        notes=row["notes"],
        mastery_level=row["mastery_level"],
        review_count=row["review_count"],
        correct_count=row["correct_count"],
        last_reviewed=datetime.fromisoformat(row["last_reviewed"]) if row["last_reviewed"] else None,
        next_review=datetime.fromisoformat(row["next_review"]) if row["next_review"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _parse_review_row(row) -> Review:
    """Convert a database row to a Review model."""
    return Review(
        id=row["id"],
        concept_id=row["concept_id"],
        outcome=ReviewOutcome(row["outcome"]),
        confidence=row["confidence"],
        time_spent_seconds=row["time_spent_seconds"],
        notes=row["notes"],
        reviewed_at=datetime.fromisoformat(row["reviewed_at"]),
    )


def _calculate_next_review(mastery: float) -> datetime:
    """Calculate next review datetime based on mastery level."""
    days = 1
    for threshold, interval in sorted(FORGE_INTERVALS.items()):
        if mastery >= threshold:
            days = interval
    return datetime.now(timezone.utc) + timedelta(days=days)


def _calculate_mastery_delta(outcome: str, confidence: int) -> float:
    """Calculate mastery change based on review outcome and confidence."""
    if outcome == "understood":
        if confidence >= 4:
            return FORGE_MASTERY_DELTAS["understood_high"]
        return FORGE_MASTERY_DELTAS["understood_low"]
    elif outcome == "reviewed":
        return FORGE_MASTERY_DELTAS["reviewed"]
    elif outcome == "struggled":
        return FORGE_MASTERY_DELTAS["struggled"]
    else:  # skipped
        return FORGE_MASTERY_DELTAS["skipped"]


def _fts5_safe_query(query: str) -> str:
    """Convert a natural language query into a safe FTS5 query."""
    words = query.split()
    safe_words = []
    for word in words:
        cleaned = "".join(c for c in word if c.isalnum() or c == "_")
        if cleaned:
            safe_words.append(f'"{cleaned}"')
    return " ".join(safe_words)


# --- Public API ---

def add_concept(
    term: str,
    definition: str,
    category: str = "general",
    difficulty: str = "beginner",
    tags: Optional[list[str]] = None,
    related_jaybrain_component: str = "",
    source: str = "",
    notes: str = "",
) -> Concept:
    """Add a new concept to the forge."""
    tags = tags or []
    concept_id = _generate_id()
    next_review = datetime.now(timezone.utc) + timedelta(days=1)

    # Generate embedding
    embedding = None
    try:
        from .search import embed_text
        embedding = embed_text(f"{term} {definition}")
    except Exception as e:
        logger.warning("Embedding generation failed for concept: %s", e)

    conn = get_connection()
    try:
        insert_forge_concept(
            conn, concept_id, term, definition, category, difficulty,
            tags, related_jaybrain_component, source, notes,
            next_review.isoformat(), embedding,
        )
        # Update streak
        upsert_forge_streak(conn, _today_str(), concepts_added=1)

        row = get_forge_concept(conn, concept_id)
        return _parse_concept_row(row)
    finally:
        conn.close()


def record_review(
    concept_id: str,
    outcome: str,
    confidence: int = 3,
    time_spent_seconds: int = 0,
    notes: str = "",
) -> Concept:
    """Record a review outcome and recalculate mastery + next review."""
    conn = get_connection()
    try:
        row = get_forge_concept(conn, concept_id)
        if not row:
            raise ValueError(f"Concept not found: {concept_id}")

        # Insert review record
        insert_forge_review(conn, concept_id, outcome, confidence, time_spent_seconds, notes)

        # Calculate new mastery
        current_mastery = row["mastery_level"]
        delta = _calculate_mastery_delta(outcome, confidence)
        new_mastery = max(0.0, min(1.0, current_mastery + delta))

        # Calculate next review
        if outcome == "skipped":
            next_review = datetime.now(timezone.utc) + timedelta(days=1)
        else:
            next_review = _calculate_next_review(new_mastery)

        # Update concept
        update_fields = {
            "mastery_level": new_mastery,
            "review_count": row["review_count"] + 1,
            "last_reviewed": datetime.now(timezone.utc).isoformat(),
            "next_review": next_review.isoformat(),
        }
        if outcome == "understood":
            update_fields["correct_count"] = row["correct_count"] + 1

        update_forge_concept(conn, concept_id, **update_fields)

        # Update streak
        upsert_forge_streak(
            conn, _today_str(),
            concepts_reviewed=1,
            time_spent_seconds=time_spent_seconds,
        )

        row = get_forge_concept(conn, concept_id)
        return _parse_concept_row(row)
    finally:
        conn.close()


def get_study_queue(
    category: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Get prioritized study queue: due > new > struggling > up_next."""
    conn = get_connection()
    try:
        due_rows = get_forge_concepts_due(conn, limit=limit)
        new_rows = get_forge_concepts_new(conn, limit=limit)
        struggling_rows = get_forge_concepts_struggling(conn, limit=limit)

        # Up next: due within 3 days but not yet due
        now = datetime.now(timezone.utc)
        three_days = (now + timedelta(days=3)).isoformat()
        up_next_rows = conn.execute(
            """SELECT * FROM forge_concepts
            WHERE next_review > ? AND next_review <= ? AND review_count > 0
            ORDER BY next_review ASC
            LIMIT ?""",
            (now.isoformat(), three_days, limit),
        ).fetchall()

        def filter_category(rows):
            if not category:
                return rows
            return [r for r in rows if r["category"] == category]

        due = [_parse_concept_row(r) for r in filter_category(due_rows)]
        new = [_parse_concept_row(r) for r in filter_category(new_rows)]
        struggling = [_parse_concept_row(r) for r in filter_category(struggling_rows)]
        up_next = [_parse_concept_row(r) for r in filter_category(up_next_rows)]

        # Remove duplicates: concepts in 'due' shouldn't appear in other lists
        due_ids = {c.id for c in due}
        new = [c for c in new if c.id not in due_ids]
        struggling_ids = due_ids | {c.id for c in new}
        struggling = [c for c in struggling if c.id not in struggling_ids]
        all_ids = struggling_ids | {c.id for c in struggling}
        up_next = [c for c in up_next if c.id not in all_ids]

        def serialize(concepts):
            return [
                {
                    "id": c.id,
                    "term": c.term,
                    "definition": c.definition,
                    "category": c.category.value,
                    "difficulty": c.difficulty.value,
                    "mastery_level": c.mastery_level,
                    "mastery_name": c.mastery_name,
                    "review_count": c.review_count,
                    "next_review": c.next_review.isoformat() if c.next_review else None,
                }
                for c in concepts
            ]

        return {
            "due_now": serialize(due),
            "new": serialize(new),
            "struggling": serialize(struggling),
            "up_next": serialize(up_next),
            "total_due": len(due),
            "total_new": len(new),
            "total_struggling": len(struggling),
            "total_up_next": len(up_next),
        }
    finally:
        conn.close()


def search_concepts(
    query: str,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict]:
    """Search concepts using hybrid vector + keyword search."""
    conn = get_connection()
    try:
        # Vector search
        vec_results = []
        try:
            from .search import embed_text, hybrid_search
            query_embedding = embed_text(query)
            vec_results = search_forge_vec(conn, query_embedding, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("Vector search failed for forge: %s", e)

        # Keyword search
        fts_results = []
        try:
            safe_query = _fts5_safe_query(query)
            if safe_query:
                fts_results = search_forge_fts(conn, safe_query, SEARCH_CANDIDATES)
        except Exception as e:
            logger.warning("FTS search failed for forge: %s", e)

        if not vec_results and not fts_results:
            return []

        from .search import hybrid_search
        merged = hybrid_search(vec_results, fts_results)

        results = []
        for cid, score in merged:
            row = get_forge_concept(conn, cid)
            if row is None:
                continue

            concept = _parse_concept_row(row)

            if category and concept.category.value != category:
                continue
            if difficulty and concept.difficulty.value != difficulty:
                continue

            results.append({
                "id": concept.id,
                "term": concept.term,
                "definition": concept.definition,
                "category": concept.category.value,
                "difficulty": concept.difficulty.value,
                "mastery_level": concept.mastery_level,
                "mastery_name": concept.mastery_name,
                "score": round(score, 4),
            })

        return results[:limit]
    finally:
        conn.close()


def update_concept(concept_id: str, **fields) -> Optional[Concept]:
    """Update a concept's fields. Re-embeds if term or definition changes."""
    conn = get_connection()
    try:
        row = get_forge_concept(conn, concept_id)
        if not row:
            return None

        # Re-embed if term or definition changed
        if "term" in fields or "definition" in fields:
            new_term = fields.get("term", row["term"])
            new_def = fields.get("definition", row["definition"])
            try:
                from .search import embed_text
                from .db import _serialize_f32
                embedding = embed_text(f"{new_term} {new_def}")
                conn.execute(
                    "INSERT OR REPLACE INTO forge_concepts_vec (id, embedding) VALUES (?, ?)",
                    (concept_id, _serialize_f32(embedding)),
                )
                conn.commit()
            except Exception as e:
                logger.warning("Failed to update concept embedding: %s", e)

        update_forge_concept(conn, concept_id, **fields)
        row = get_forge_concept(conn, concept_id)
        if not row:
            return None
        return _parse_concept_row(row)
    finally:
        conn.close()


def get_concept_detail(concept_id: str) -> Optional[dict]:
    """Get full concept with review history."""
    conn = get_connection()
    try:
        row = get_forge_concept(conn, concept_id)
        if not row:
            return None

        concept = _parse_concept_row(row)
        review_rows = get_forge_reviews(conn, concept_id)
        reviews = [_parse_review_row(r) for r in review_rows]

        return {
            "concept": {
                "id": concept.id,
                "term": concept.term,
                "definition": concept.definition,
                "category": concept.category.value,
                "difficulty": concept.difficulty.value,
                "tags": concept.tags,
                "related_jaybrain_component": concept.related_jaybrain_component,
                "source": concept.source,
                "notes": concept.notes,
                "mastery_level": concept.mastery_level,
                "mastery_name": concept.mastery_name,
                "review_count": concept.review_count,
                "correct_count": concept.correct_count,
                "last_reviewed": concept.last_reviewed.isoformat() if concept.last_reviewed else None,
                "next_review": concept.next_review.isoformat() if concept.next_review else None,
                "created_at": concept.created_at.isoformat(),
                "updated_at": concept.updated_at.isoformat(),
            },
            "reviews": [
                {
                    "id": r.id,
                    "outcome": r.outcome.value,
                    "confidence": r.confidence,
                    "time_spent_seconds": r.time_spent_seconds,
                    "notes": r.notes,
                    "reviewed_at": r.reviewed_at.isoformat(),
                }
                for r in reviews
            ],
            "review_count": len(reviews),
        }
    finally:
        conn.close()


def get_forge_stats() -> dict:
    """Get aggregate forge statistics."""
    conn = get_connection()
    try:
        total_concepts = conn.execute("SELECT COUNT(*) FROM forge_concepts").fetchone()[0]
        total_reviews = conn.execute("SELECT COUNT(*) FROM forge_reviews").fetchone()[0]

        # By category
        cat_rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM forge_concepts GROUP BY category"
        ).fetchall()
        by_category = {row["category"]: row["cnt"] for row in cat_rows}

        # By difficulty
        diff_rows = conn.execute(
            "SELECT difficulty, COUNT(*) as cnt FROM forge_concepts GROUP BY difficulty"
        ).fetchall()
        by_difficulty = {row["difficulty"]: row["cnt"] for row in diff_rows}

        # By mastery level bucket
        mastery_buckets = {"Spark": 0, "Ember": 0, "Flame": 0, "Blaze": 0, "Inferno": 0, "Forged": 0}
        all_concepts = conn.execute("SELECT mastery_level FROM forge_concepts").fetchall()
        for row in all_concepts:
            m = row["mastery_level"]
            if m >= 0.95:
                mastery_buckets["Forged"] += 1
            elif m >= 0.80:
                mastery_buckets["Inferno"] += 1
            elif m >= 0.60:
                mastery_buckets["Blaze"] += 1
            elif m >= 0.40:
                mastery_buckets["Flame"] += 1
            elif m >= 0.20:
                mastery_buckets["Ember"] += 1
            else:
                mastery_buckets["Spark"] += 1

        # Due count
        from .db import now_iso
        due_count = conn.execute(
            "SELECT COUNT(*) FROM forge_concepts WHERE next_review <= ?",
            (now_iso(),),
        ).fetchone()[0]

        # Average mastery
        avg_row = conn.execute(
            "SELECT AVG(mastery_level) as avg_m FROM forge_concepts"
        ).fetchone()
        avg_mastery = round(avg_row["avg_m"] or 0.0, 4)

        # Streak calculation
        streak_rows = get_forge_streak_data(conn, limit=90)
        current_streak, longest_streak = _calculate_streaks(streak_rows)

        return ForgeStats(
            total_concepts=total_concepts,
            total_reviews=total_reviews,
            concepts_by_category=by_category,
            concepts_by_difficulty=by_difficulty,
            concepts_by_mastery=mastery_buckets,
            due_count=due_count,
            avg_mastery=avg_mastery,
            current_streak=current_streak,
            longest_streak=longest_streak,
        ).model_dump()
    finally:
        conn.close()


def _calculate_streaks(streak_rows: list) -> tuple[int, int]:
    """Calculate current and longest streak from streak data."""
    if not streak_rows:
        return 0, 0

    # Streak rows come most recent first
    dates = sorted(
        [datetime.strptime(row["date"], "%Y-%m-%d").date() for row in streak_rows],
        reverse=True,
    )

    today = datetime.now(timezone.utc).date()

    # Current streak: consecutive days ending today or yesterday
    current_streak = 0
    expected = today
    for d in dates:
        if d == expected:
            current_streak += 1
            expected = d - timedelta(days=1)
        elif d == expected - timedelta(days=1):
            # Allow starting from yesterday if no activity today
            if current_streak == 0:
                expected = d
                current_streak = 1
                expected = d - timedelta(days=1)
            else:
                break
        else:
            if current_streak > 0:
                break

    # Longest streak
    longest_streak = 0
    if dates:
        run = 1
        sorted_asc = sorted(dates)
        for i in range(1, len(sorted_asc)):
            if sorted_asc[i] == sorted_asc[i - 1] + timedelta(days=1):
                run += 1
            else:
                longest_streak = max(longest_streak, run)
                run = 1
        longest_streak = max(longest_streak, run)

    return current_streak, longest_streak
