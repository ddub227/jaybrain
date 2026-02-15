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
    FORGE_MASTERY_DELTAS_V2,
    FORGE_READINESS_WEIGHTS,
    SEARCH_CANDIDATES,
)
from .db import (
    get_connection,
    get_concepts_for_objective,
    get_error_patterns,
    get_forge_concept,
    get_forge_concepts_due,
    get_forge_concepts_new,
    get_forge_concepts_struggling,
    get_forge_objective_by_code,
    get_forge_objectives,
    get_forge_reviews,
    get_forge_reviews_for_subject,
    get_forge_streak_data,
    get_forge_subject,
    get_objectives_for_concept,
    insert_forge_concept,
    insert_forge_error_pattern,
    insert_forge_objective,
    insert_forge_review,
    insert_forge_subject,
    link_concept_objective,
    list_forge_subjects,
    search_forge_fts,
    search_forge_vec,
    update_forge_concept,
    upsert_forge_streak,
)
from .models import (
    CalibrationData,
    Concept,
    ConceptCategory,
    ConceptDifficulty,
    ForgeStats,
    Objective,
    ReadinessScore,
    Review,
    ReviewOutcome,
    Subject,
)

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
    """Calculate mastery change based on review outcome and confidence (v1 fallback)."""
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


def _calculate_mastery_delta_v2(was_correct: bool, confidence: int) -> float:
    """v2: Confidence-weighted mastery delta using 4 quadrants."""
    confident = confidence >= 4
    if was_correct and confident:
        return FORGE_MASTERY_DELTAS_V2["correct_confident"]
    elif was_correct and not confident:
        return FORGE_MASTERY_DELTAS_V2["correct_unsure"]
    elif not was_correct and confident:
        return FORGE_MASTERY_DELTAS_V2["incorrect_confident"]
    else:
        return FORGE_MASTERY_DELTAS_V2["incorrect_unsure"]


def _classify_error(
    was_correct: bool,
    confidence: int,
    current_mastery: float,
    correct_count: int,
    review_count: int,
) -> str:
    """Auto-classify error type when answer is wrong."""
    if was_correct:
        return ""
    if confidence >= 4:
        return "misconception"
    if current_mastery >= 0.6:
        return "lapse"
    if correct_count > 0 and review_count > 2:
        return "slip"
    return "mistake"


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
    subject_id: str = "",
    bloom_level: str = "remember",
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
        # Set v2 fields
        if subject_id or bloom_level != "remember":
            update_forge_concept(
                conn, concept_id,
                subject_id=subject_id,
                bloom_level=bloom_level,
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
    was_correct: Optional[bool] = None,
    error_type: str = "",
    bloom_level: str = "",
) -> Concept:
    """Record a review outcome and recalculate mastery + next review.

    v2 mode: when was_correct is provided, uses confidence-weighted 4-quadrant scoring.
    v1 fallback: when was_correct is None, uses outcome-based scoring.
    """
    conn = get_connection()
    try:
        row = get_forge_concept(conn, concept_id)
        if not row:
            raise ValueError(f"Concept not found: {concept_id}")

        current_mastery = row["mastery_level"]
        subject_id = row["subject_id"] if "subject_id" in row.keys() else ""

        # v2 scoring when was_correct is explicitly provided
        if was_correct is not None:
            delta = _calculate_mastery_delta_v2(was_correct, confidence)

            # Auto-classify error if not provided and answer was wrong
            if not error_type and not was_correct:
                error_type = _classify_error(
                    was_correct, confidence, current_mastery,
                    row["correct_count"], row["review_count"],
                )

            # Record error pattern
            if error_type and not was_correct:
                insert_forge_error_pattern(
                    conn, concept_id, error_type, notes, bloom_level,
                )
        else:
            # v1 fallback
            delta = _calculate_mastery_delta(outcome, confidence)

        new_mastery = max(0.0, min(1.0, current_mastery + delta))

        # Insert review record with v2 fields
        insert_forge_review(
            conn, concept_id, outcome, confidence,
            time_spent_seconds, notes,
            was_correct=was_correct,
            error_type=error_type,
            bloom_level=bloom_level,
            subject_id=subject_id,
        )

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
        if was_correct is not None:
            if was_correct:
                update_fields["correct_count"] = row["correct_count"] + 1
        elif outcome == "understood":
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
    subject_id: Optional[str] = None,
) -> dict:
    """Get prioritized study queue.

    When subject_id is provided, returns an interleaved queue weighted by
    exam_weight * (1 - mastery), spreading across objectives.
    Otherwise falls back to the original due > new > struggling > up_next order.
    """
    conn = get_connection()
    try:
        if subject_id:
            return _get_interleaved_queue(conn, subject_id, limit)

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

        # Remove duplicates
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


def _get_interleaved_queue(
    conn, subject_id: str, limit: int
) -> dict:
    """Build an interleaved study queue weighted by exam importance and inverse mastery."""
    objectives = get_forge_objectives(conn, subject_id)
    if not objectives:
        return {"interleaved": [], "total": 0, "study_strategy": "No objectives found."}

    now = datetime.now(timezone.utc)
    scored_concepts = []

    for obj in objectives:
        concepts = get_concepts_for_objective(conn, obj["id"])
        for row in concepts:
            is_due = row["next_review"] and row["next_review"] <= now.isoformat()
            due_boost = 0.3 if is_due else 0.0
            priority = obj["exam_weight"] * (1.0 - row["mastery_level"]) + due_boost
            scored_concepts.append({
                "concept": row,
                "objective_code": obj["code"],
                "domain": obj["domain"],
                "exam_weight": obj["exam_weight"],
                "priority": priority,
                "is_due": is_due,
            })

    # Sort by priority descending
    scored_concepts.sort(key=lambda x: x["priority"], reverse=True)

    # Interleave: don't let same objective appear consecutively
    interleaved = []
    remaining = list(scored_concepts)
    last_obj = None
    while remaining and len(interleaved) < limit:
        picked = None
        for i, item in enumerate(remaining):
            if item["objective_code"] != last_obj or len(remaining) == 1:
                picked = remaining.pop(i)
                break
        if picked is None:
            picked = remaining.pop(0)
        last_obj = picked["objective_code"]
        c = picked["concept"]
        interleaved.append({
            "id": c["id"],
            "term": c["term"],
            "definition": c["definition"],
            "mastery_level": c["mastery_level"],
            "review_count": c["review_count"],
            "objective_code": picked["objective_code"],
            "domain": picked["domain"],
            "exam_weight": picked["exam_weight"],
            "priority": round(picked["priority"], 4),
            "is_due": picked["is_due"],
        })

    # Generate strategy recommendation
    if interleaved:
        top = interleaved[0]
        strategy = f"Focus on {top['domain']} ({top['objective_code']}) - highest priority area."
    else:
        strategy = "All concepts reviewed. Great job!"

    return {
        "interleaved": interleaved,
        "total": len(interleaved),
        "study_strategy": strategy,
    }


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


# --- v2: Subject Management ---

def create_subject(
    name: str,
    short_name: str,
    description: str = "",
    pass_score: float = 0.0,
    total_questions: int = 0,
    time_limit_minutes: int = 0,
) -> dict:
    """Create a new learning subject."""
    subject_id = _generate_id()
    conn = get_connection()
    try:
        insert_forge_subject(
            conn, subject_id, name, short_name, description,
            pass_score, total_questions, time_limit_minutes,
        )
        row = get_forge_subject(conn, subject_id)
        return {
            "id": row["id"],
            "name": row["name"],
            "short_name": row["short_name"],
            "description": row["description"],
            "pass_score": row["pass_score"],
            "total_questions": row["total_questions"],
            "time_limit_minutes": row["time_limit_minutes"],
            "active": bool(row["active"]),
        }
    finally:
        conn.close()


def get_subjects() -> list[dict]:
    """List all learning subjects with summary stats."""
    conn = get_connection()
    try:
        rows = list_forge_subjects(conn)
        results = []
        for row in rows:
            concept_count = conn.execute(
                """SELECT COUNT(DISTINCT fco.concept_id) FROM forge_concept_objectives fco
                JOIN forge_objectives fo ON fo.id = fco.objective_id
                WHERE fo.subject_id = ?""",
                (row["id"],),
            ).fetchone()[0]
            objective_count = conn.execute(
                "SELECT COUNT(*) FROM forge_objectives WHERE subject_id = ?",
                (row["id"],),
            ).fetchone()[0]
            results.append({
                "id": row["id"],
                "name": row["name"],
                "short_name": row["short_name"],
                "pass_score": row["pass_score"],
                "active": bool(row["active"]),
                "concept_count": concept_count,
                "objective_count": objective_count,
            })
        return results
    finally:
        conn.close()


def add_objective(
    subject_id: str,
    code: str,
    title: str,
    domain: str = "",
    exam_weight: float = 0.0,
) -> dict:
    """Add an exam objective to a subject."""
    objective_id = _generate_id()
    conn = get_connection()
    try:
        insert_forge_objective(
            conn, objective_id, subject_id, code, title, domain, exam_weight,
        )
        row = get_forge_objective_by_code(conn, subject_id, code)
        return {
            "id": row["id"],
            "subject_id": row["subject_id"],
            "code": row["code"],
            "title": row["title"],
            "domain": row["domain"],
            "exam_weight": row["exam_weight"],
        }
    finally:
        conn.close()


def link_concept_to_objective(
    concept_id: str,
    objective_code: str,
    subject_id: str,
) -> bool:
    """Link a concept to an objective by code. Returns True if linked."""
    conn = get_connection()
    try:
        obj = get_forge_objective_by_code(conn, subject_id, objective_code)
        if not obj:
            return False
        link_concept_objective(conn, concept_id, obj["id"])
        # Also set subject_id on the concept
        update_forge_concept(conn, concept_id, subject_id=subject_id)
        return True
    finally:
        conn.close()


# --- v2: Readiness Score ---

def calculate_readiness(subject_id: str) -> dict:
    """Calculate exam readiness score for a subject."""
    conn = get_connection()
    try:
        subject = get_forge_subject(conn, subject_id)
        if not subject:
            return {"error": f"Subject not found: {subject_id}"}

        objectives = get_forge_objectives(conn, subject_id)
        if not objectives:
            return {"error": "No objectives found for subject"}

        by_objective = {}
        by_domain = {}
        domain_weights = {}
        total_concepts = 0
        reviewed_concepts = 0
        mastery_sum = 0.0
        now = datetime.now(timezone.utc)

        for obj in objectives:
            concepts = get_concepts_for_objective(conn, obj["id"])
            if not concepts:
                by_objective[obj["code"]] = 0.0
                continue

            obj_mastery_sum = 0.0
            obj_count = 0
            for c in concepts:
                total_concepts += 1
                obj_mastery_sum += c["mastery_level"]
                mastery_sum += c["mastery_level"]
                obj_count += 1
                if c["review_count"] > 0:
                    reviewed_concepts += 1

            obj_avg = obj_mastery_sum / obj_count if obj_count > 0 else 0.0
            by_objective[obj["code"]] = round(obj_avg, 4)

            domain = obj["domain"]
            if domain not in by_domain:
                by_domain[domain] = 0.0
                domain_weights[domain] = 0.0
            by_domain[domain] += obj_avg * obj["exam_weight"]
            domain_weights[domain] += obj["exam_weight"]

        # Normalize domain scores
        for domain in by_domain:
            if domain_weights[domain] > 0:
                by_domain[domain] = round(
                    by_domain[domain] / domain_weights[domain], 4
                )

        avg_mastery = mastery_sum / total_concepts if total_concepts > 0 else 0.0
        coverage = reviewed_concepts / total_concepts if total_concepts > 0 else 0.0

        # Get calibration
        cal = _calculate_calibration(conn, subject_id)
        cal_score = cal.calibration_score

        # Recency: fraction of reviewed concepts reviewed in last 7 days
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        recent_count = conn.execute(
            """SELECT COUNT(DISTINCT concept_id) FROM forge_reviews
            WHERE subject_id = ? AND reviewed_at >= ?""",
            (subject_id, seven_days_ago),
        ).fetchone()[0]
        recency = recent_count / total_concepts if total_concepts > 0 else 0.0

        # Weighted overall score
        w = FORGE_READINESS_WEIGHTS
        overall = (
            w["mastery"] * avg_mastery
            + w["coverage"] * coverage
            + w["calibration"] * cal_score
            + w["recency"] * recency
        )

        # Weakest objectives
        weakest = sorted(by_objective.items(), key=lambda x: x[1])[:5]
        weakest_areas = [code for code, _ in weakest]

        # Recommendation
        if weakest_areas:
            weakest_obj = None
            for obj in objectives:
                if obj["code"] == weakest_areas[0]:
                    weakest_obj = obj
                    break
            if weakest_obj:
                recommendation = (
                    f"Focus on {weakest_obj['domain']} - "
                    f"objective {weakest_obj['code']}: {weakest_obj['title']} "
                    f"(mastery: {by_objective.get(weakest_areas[0], 0):.0%})"
                )
            else:
                recommendation = f"Focus on objective {weakest_areas[0]}"
        else:
            recommendation = "Looking strong across all objectives!"

        return ReadinessScore(
            overall=round(overall, 4),
            by_domain=by_domain,
            by_objective=by_objective,
            weakest_areas=weakest_areas,
            total_concepts=total_concepts,
            reviewed_concepts=reviewed_concepts,
            coverage=round(coverage, 4),
            avg_mastery=round(avg_mastery, 4),
            calibration_score=round(cal_score, 4),
            recommendation=recommendation,
        ).model_dump()
    finally:
        conn.close()


# --- v2: Calibration Analytics ---

def _calculate_calibration(conn, subject_id: str = "") -> CalibrationData:
    """Internal calibration calculation (needs open connection)."""
    if subject_id:
        reviews = get_forge_reviews_for_subject(conn, subject_id)
    else:
        reviews = conn.execute(
            "SELECT * FROM forge_reviews ORDER BY reviewed_at DESC LIMIT 1000"
        ).fetchall()

    cc = ci = uc = ui = 0
    for r in reviews:
        was_correct = r["was_correct"] if "was_correct" in r.keys() else None
        if was_correct is None:
            # Infer from v1 outcome
            was_correct = 1 if r["outcome"] in ("understood", "reviewed") else 0
        confident = r["confidence"] >= 4
        if was_correct and confident:
            cc += 1
        elif not was_correct and confident:
            ci += 1
        elif was_correct and not confident:
            uc += 1
        else:
            ui += 1

    total = cc + ci + uc + ui
    if total == 0:
        return CalibrationData()

    confident_total = cc + ci
    unsure_total = uc + ui

    overconfidence = ci / confident_total if confident_total > 0 else 0.0
    underconfidence = uc / unsure_total if unsure_total > 0 else 0.0

    # Calibration: 1 - mean absolute error between confidence and accuracy
    actual_accuracy = (cc + uc) / total
    predicted_accuracy = confident_total / total
    cal_score = 1.0 - abs(predicted_accuracy - actual_accuracy)

    return CalibrationData(
        total_reviews=total,
        confident_correct=cc,
        confident_incorrect=ci,
        unsure_correct=uc,
        unsure_incorrect=ui,
        calibration_score=round(max(0.0, cal_score), 4),
        overconfidence_rate=round(overconfidence, 4),
        underconfidence_rate=round(underconfidence, 4),
    )


def get_calibration(subject_id: str = "") -> dict:
    """Get calibration analytics for reviews."""
    conn = get_connection()
    try:
        return _calculate_calibration(conn, subject_id).model_dump()
    finally:
        conn.close()


# --- v2: Knowledge Map Generator ---

def generate_knowledge_map(subject_id: str) -> str:
    """Generate a markdown knowledge map for a subject."""
    conn = get_connection()
    try:
        subject = get_forge_subject(conn, subject_id)
        if not subject:
            return f"Subject not found: {subject_id}"

        objectives = get_forge_objectives(conn, subject_id)
        if not objectives:
            return "No objectives found."

        # Group objectives by domain
        domains: dict[str, list] = {}
        for obj in objectives:
            domain = obj["domain"] or "Uncategorized"
            if domain not in domains:
                domains[domain] = []
            domains[domain].append(obj)

        lines = [
            f"# Knowledge Map: {subject['name']}",
            "",
        ]

        # Quick readiness summary
        readiness = calculate_readiness(subject_id)
        if isinstance(readiness, dict) and "overall" in readiness:
            lines.append(f"**Readiness: {readiness['overall']:.0%}** | "
                         f"Coverage: {readiness['coverage']:.0%} | "
                         f"Avg Mastery: {readiness['avg_mastery']:.0%}")
            lines.append("")

        for domain_name in sorted(domains.keys()):
            domain_objs = domains[domain_name]
            weight = domain_objs[0]["exam_weight"] if domain_objs else 0
            lines.append(f"## {domain_name} (Weight: {weight:.0%})")
            lines.append("")

            for obj in sorted(domain_objs, key=lambda o: o["code"]):
                concepts = get_concepts_for_objective(conn, obj["id"])
                if not concepts:
                    lines.append(f"### {obj['code']} - {obj['title']}")
                    lines.append("*No concepts linked*")
                    lines.append("")
                    continue

                avg_m = sum(c["mastery_level"] for c in concepts) / len(concepts)
                reviewed = sum(1 for c in concepts if c["review_count"] > 0)
                lines.append(
                    f"### {obj['code']} - {obj['title']} "
                    f"({avg_m:.0%} avg | {reviewed}/{len(concepts)} reviewed)"
                )
                lines.append("")

                for c in concepts:
                    m = c["mastery_level"]
                    filled = int(m * 10)
                    bar = "#" * filled + "-" * (10 - filled)
                    status = "!!" if m < 0.2 and c["review_count"] > 0 else ""
                    lines.append(
                        f"- [{bar}] {m:.0%} {c['term']} "
                        f"(reviews: {c['review_count']}) {status}"
                    )

                    # Show error patterns for this concept
                    errors = get_error_patterns(conn, concept_id=c["id"], limit=3)
                    for e in errors:
                        lines.append(f"  ^ {e['error_type']}: {e['details']}" if e["details"] else f"  ^ {e['error_type']}")

                lines.append("")

        return "\n".join(lines)
    finally:
        conn.close()


# --- v2: Error Pattern Analysis ---

def get_error_analysis(subject_id: str = "", concept_id: str = "") -> dict:
    """Analyze error patterns across concepts."""
    conn = get_connection()
    try:
        errors = get_error_patterns(
            conn, concept_id=concept_id, subject_id=subject_id,
        )

        by_type: dict[str, int] = {}
        by_concept: dict[str, list] = {}
        for e in errors:
            etype = e["error_type"]
            by_type[etype] = by_type.get(etype, 0) + 1

            cid = e["concept_id"]
            if cid not in by_concept:
                by_concept[cid] = []
            by_concept[cid].append({
                "error_type": etype,
                "details": e["details"],
                "bloom_level": e["bloom_level"],
                "created_at": e["created_at"],
            })

        # Find concepts with most errors
        recurring = sorted(
            by_concept.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:10]

        recurring_details = []
        for cid, errs in recurring:
            concept_row = get_forge_concept(conn, cid)
            term = concept_row["term"] if concept_row else cid
            recurring_details.append({
                "concept_id": cid,
                "term": term,
                "error_count": len(errs),
                "errors": errs[:5],
            })

        return {
            "total_errors": len(errors),
            "by_type": by_type,
            "recurring_concepts": recurring_details,
        }
    finally:
        conn.close()
