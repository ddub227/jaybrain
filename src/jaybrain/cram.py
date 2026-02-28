"""CramForge - Exam cram tool powered by SynapseForge intelligence.

Focused, last-minute study tool for topics from wrong practice exam questions.
Stores topics separately from forge_concepts but cross-references SynapseForge
mastery data to calibrate teaching and question generation.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import FORGE_MASTERY_DELTAS_V2
from .db import (
    delete_cram_topic,
    get_connection,
    get_cram_reviews,
    get_cram_stats,
    get_cram_topic,
    get_forge_concept,
    insert_cram_review,
    insert_cram_topic,
    list_cram_topics,
    search_forge_fts,
    update_cram_topic,
)

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _mastery_name(level: float) -> str:
    """Return forge-themed mastery level name for understanding score."""
    if level >= 0.95:
        return "Forged"
    elif level >= 0.80:
        return "Inferno"
    elif level >= 0.60:
        return "Blaze"
    elif level >= 0.40:
        return "Flame"
    elif level >= 0.20:
        return "Ember"
    else:
        return "Spark"


def _find_forge_link(conn, topic: str) -> Optional[dict]:
    """Search SynapseForge for a matching concept. Returns match info or None."""
    try:
        from .forge import _fts5_safe_query
        safe_q = _fts5_safe_query(topic)
        if not safe_q:
            return None
        results = search_forge_fts(conn, safe_q, limit=3)
        if not results:
            return None
        best_id, score = results[0]
        row = get_forge_concept(conn, best_id)
        if row:
            return {
                "concept_id": row["id"],
                "term": row["term"],
                "mastery_level": row["mastery_level"],
                "review_count": row["review_count"],
            }
    except Exception as e:
        logger.warning("Forge cross-reference failed: %s", e)
    return None


def add_topic(
    topic: str,
    description: str = "",
    source_question: str = "",
    source_answer: str = "",
) -> dict:
    """Add a cram topic. Auto-links to SynapseForge if a match exists."""
    topic_id = _generate_id()
    conn = get_connection()
    try:
        forge_link = _find_forge_link(conn, topic)
        forge_concept_id = forge_link["concept_id"] if forge_link else None

        insert_cram_topic(
            conn, topic_id, topic, description,
            source_question, source_answer,
            forge_concept_id=forge_concept_id,
        )

        result = {
            "topic_id": topic_id,
            "topic": topic,
            "understanding": 0.0,
            "understanding_name": "Spark",
        }
        if forge_link:
            result["forge_link"] = forge_link
        return result
    finally:
        conn.close()


def list_topics(sort_by: str = "understanding") -> dict:
    """List all cram topics with understanding levels."""
    conn = get_connection()
    try:
        rows = list_cram_topics(conn, sort_by)
        topics = []
        for row in rows:
            t = {
                "id": row["id"],
                "topic": row["topic"],
                "description": row["description"],
                "understanding": row["understanding"],
                "understanding_name": _mastery_name(row["understanding"]),
                "review_count": row["review_count"],
                "correct_count": row["correct_count"],
                "forge_concept_id": row["forge_concept_id"],
            }
            if row["source_question"]:
                t["has_source_question"] = True
            topics.append(t)
        return {
            "count": len(topics),
            "topics": topics,
        }
    finally:
        conn.close()


def record_review(
    topic_id: str,
    was_correct: bool,
    confidence: int = 3,
    notes: str = "",
) -> dict:
    """Record a cram review and update understanding level.

    Uses SynapseForge v2 confidence-weighted scoring.
    """
    conn = get_connection()
    try:
        row = get_cram_topic(conn, topic_id)
        if not row:
            raise ValueError(f"Cram topic not found: {topic_id}")

        current = row["understanding"]

        # v2 confidence-weighted delta (same as SynapseForge)
        confident = confidence >= 4
        if was_correct and confident:
            delta = FORGE_MASTERY_DELTAS_V2["correct_confident"]
        elif was_correct and not confident:
            delta = FORGE_MASTERY_DELTAS_V2["correct_unsure"]
        elif not was_correct and confident:
            delta = FORGE_MASTERY_DELTAS_V2["incorrect_confident"]
        else:
            delta = FORGE_MASTERY_DELTAS_V2["incorrect_unsure"]

        new_understanding = max(0.0, min(1.0, current + delta))

        # Atomic: insert review + update topic
        insert_cram_review(conn, topic_id, was_correct, confidence, notes, commit=False)
        update_cram_topic(
            conn, topic_id, commit=False,
            understanding=new_understanding,
            review_count=row["review_count"] + 1,
            correct_count=row["correct_count"] + (1 if was_correct else 0),
            last_reviewed=datetime.now(timezone.utc).isoformat(),
        )
        conn.commit()

        return {
            "topic_id": topic_id,
            "topic": row["topic"],
            "was_correct": was_correct,
            "confidence": confidence,
            "understanding": new_understanding,
            "understanding_name": _mastery_name(new_understanding),
            "delta": delta,
            "review_count": row["review_count"] + 1,
        }
    finally:
        conn.close()


def get_study_queue(limit: int = 10) -> dict:
    """Get prioritized cram study queue.

    Priority: lowest understanding first, with ties broken by fewer reviews.
    Cross-references SynapseForge data for each topic.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM cram_topics
            ORDER BY understanding ASC, review_count ASC
            LIMIT ?""",
            (limit,),
        ).fetchall()

        queue = []
        for row in rows:
            item = {
                "id": row["id"],
                "topic": row["topic"],
                "description": row["description"],
                "understanding": row["understanding"],
                "understanding_name": _mastery_name(row["understanding"]),
                "review_count": row["review_count"],
                "correct_count": row["correct_count"],
            }
            if row["source_question"]:
                item["source_question"] = row["source_question"]
                item["source_answer"] = row["source_answer"]

            # Pull forge intelligence if linked
            if row["forge_concept_id"]:
                forge_row = get_forge_concept(conn, row["forge_concept_id"])
                if forge_row:
                    item["forge_intel"] = {
                        "term": forge_row["term"],
                        "definition": forge_row["definition"],
                        "mastery_level": forge_row["mastery_level"],
                        "mastery_name": _mastery_name(forge_row["mastery_level"]),
                        "review_count": forge_row["review_count"],
                    }

            queue.append(item)

        return {
            "count": len(queue),
            "queue": queue,
        }
    finally:
        conn.close()


def remove_topic(topic_id: str) -> dict:
    """Remove a cram topic (graduated or added by mistake)."""
    conn = get_connection()
    try:
        row = get_cram_topic(conn, topic_id)
        if not row:
            raise ValueError(f"Cram topic not found: {topic_id}")
        topic_name = row["topic"]
        delete_cram_topic(conn, topic_id)
        return {"removed": topic_name, "topic_id": topic_id}
    finally:
        conn.close()


def get_stats() -> dict:
    """Get cram dashboard statistics."""
    conn = get_connection()
    try:
        stats = get_cram_stats(conn)

        # Add understanding distribution
        rows = conn.execute(
            """SELECT
                SUM(CASE WHEN understanding < 0.2 THEN 1 ELSE 0 END) as spark,
                SUM(CASE WHEN understanding >= 0.2 AND understanding < 0.4 THEN 1 ELSE 0 END) as ember,
                SUM(CASE WHEN understanding >= 0.4 AND understanding < 0.6 THEN 1 ELSE 0 END) as flame,
                SUM(CASE WHEN understanding >= 0.6 AND understanding < 0.8 THEN 1 ELSE 0 END) as blaze,
                SUM(CASE WHEN understanding >= 0.8 THEN 1 ELSE 0 END) as inferno_plus
            FROM cram_topics"""
        ).fetchone()

        stats["distribution"] = {
            "Spark (0-20%)": rows["spark"] or 0,
            "Ember (20-40%)": rows["ember"] or 0,
            "Flame (40-60%)": rows["flame"] or 0,
            "Blaze (60-80%)": rows["blaze"] or 0,
            "Inferno+ (80%+)": rows["inferno_plus"] or 0,
        }

        return stats
    finally:
        conn.close()
