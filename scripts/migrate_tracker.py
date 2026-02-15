"""Migrate tracker.json data into SynapseForge v2.

Creates the SY0-701 subject, all 28 objectives, links existing forge concepts
to objectives, and imports question history + misconceptions from tracker.json.
"""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jaybrain.db import (
    get_connection,
    init_db,
    get_forge_objective_by_code,
    insert_forge_error_pattern,
    insert_forge_review,
    link_concept_objective,
    update_forge_concept,
)
from jaybrain.forge import create_subject, add_objective

TRACKER_PATH = Path.home() / "Documents" / "security_plus_prep" / "tracker.json"

DOMAIN_WEIGHTS = {
    "1": 0.12,
    "2": 0.22,
    "3": 0.18,
    "4": 0.28,
    "5": 0.20,
}

DOMAIN_NAMES = {
    "1": "1.0 - General Security Concepts",
    "2": "2.0 - Threats, Vulnerabilities & Mitigations",
    "3": "3.0 - Security Architecture",
    "4": "4.0 - Security Operations",
    "5": "5.0 - Security Program Management & Oversight",
}


def main():
    init_db()

    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        tracker = json.load(f)

    # 1. Create subject
    print("Creating SY0-701 subject...")
    subject = create_subject(
        name="CompTIA Security+ SY0-701",
        short_name="SY0-701",
        description="CompTIA Security+ certification exam, version SY0-701",
        pass_score=0.833,
        total_questions=90,
        time_limit_minutes=90,
    )
    subject_id = subject["id"]
    print(f"  Subject created: {subject_id}")

    # 2. Create all 28 objectives
    print("Creating objectives...")
    objectives_created = 0
    for code, obj_data in tracker["objectives"].items():
        domain_num = str(obj_data["domain"])
        weight = DOMAIN_WEIGHTS.get(domain_num, 0.0)
        domain_name = DOMAIN_NAMES.get(domain_num, f"Domain {domain_num}")

        add_objective(
            subject_id=subject_id,
            code=code,
            title=obj_data["title"],
            domain=domain_name,
            exam_weight=weight,
        )
        objectives_created += 1
    print(f"  {objectives_created} objectives created")

    # 3. Link existing forge concepts to objectives by parsing tags
    conn = get_connection()
    try:
        print("Linking forge concepts to objectives...")
        all_concepts = conn.execute("SELECT * FROM forge_concepts").fetchall()
        linked = 0
        for concept in all_concepts:
            tags = json.loads(concept["tags"])
            concept_id = concept["id"]

            # Update subject_id on concept
            update_forge_concept(conn, concept_id, subject_id=subject_id)

            # Parse objective codes from tags (e.g. "1.1", "2.3")
            for tag in tags:
                if "." in tag and len(tag) <= 3:
                    obj_row = get_forge_objective_by_code(conn, subject_id, tag)
                    if obj_row:
                        link_concept_objective(conn, concept_id, obj_row["id"])
                        linked += 1
        print(f"  {linked} concept-objective links created")

        # 4. Import question history from tracker terms
        print("Importing question history...")
        terms = tracker.get("terms", {})
        reviews_imported = 0
        errors_imported = 0
        terms_matched = 0
        terms_unmatched = []

        for term_name, term_data in terms.items():
            # Find matching concept by term name (case-insensitive)
            match = conn.execute(
                "SELECT * FROM forge_concepts WHERE LOWER(term) = LOWER(?)",
                (term_name,),
            ).fetchone()

            if not match:
                # Try partial match on term (e.g. "AES" in "Symmetric Encryption (AES)")
                match = conn.execute(
                    "SELECT * FROM forge_concepts WHERE LOWER(term) LIKE ?",
                    (f"%{term_name.lower()}%",),
                ).fetchone()

            if not match:
                # Try matching in tags JSON
                match = conn.execute(
                    "SELECT * FROM forge_concepts WHERE LOWER(tags) LIKE ?",
                    (f"%{term_name.lower()}%",),
                ).fetchone()

            if not match:
                # Try word boundary match: term contains the tracker name as a word
                all_rows = conn.execute("SELECT * FROM forge_concepts").fetchall()
                needle = term_name.lower()
                for row in all_rows:
                    term_lower = row["term"].lower()
                    # Check if needle appears as a standalone word or in parens
                    if (f"({needle})" in term_lower or
                        f" {needle} " in f" {term_lower} " or
                        term_lower.startswith(f"{needle} ") or
                        term_lower.endswith(f" {needle}")):
                        match = row
                        break

            if not match:
                terms_unmatched.append(term_name)
                continue

            terms_matched += 1
            concept_id = match["id"]

            # Set mastery from tracker
            tracker_mastery = term_data.get("mastery", 0.0)
            update_forge_concept(conn, concept_id, mastery_level=tracker_mastery)

            # Import question history as reviews
            for session in term_data.get("history", []):
                session_date = session.get("date", "")
                for q in session.get("questions", []):
                    was_correct = q.get("correct", False)
                    flagged_dk = q.get("flagged_dont_know", False)

                    if flagged_dk:
                        outcome = "skipped"
                        confidence = 1
                    elif was_correct:
                        outcome = "understood"
                        confidence = 4
                    else:
                        outcome = "struggled"
                        confidence = 3

                    insert_forge_review(
                        conn, concept_id, outcome, confidence,
                        notes=q.get("question", ""),
                        was_correct=was_correct,
                        subject_id=subject_id,
                    )
                    reviews_imported += 1

            # Import misconceptions as error patterns
            for misconception in term_data.get("misconceptions", []):
                insert_forge_error_pattern(
                    conn, concept_id, "misconception", misconception,
                )
                errors_imported += 1

            # Update review_count and correct_count to match
            total_q = sum(
                len(s.get("questions", []))
                for s in term_data.get("history", [])
            )
            correct_q = sum(
                sum(1 for q in s.get("questions", []) if q.get("correct", False))
                for s in term_data.get("history", [])
            )
            update_forge_concept(
                conn, concept_id,
                review_count=total_q,
                correct_count=correct_q,
            )

        print(f"  {terms_matched}/{len(terms)} terms matched to concepts")
        print(f"  {reviews_imported} reviews imported")
        print(f"  {errors_imported} error patterns imported")
        if terms_unmatched:
            print(f"  Unmatched terms: {', '.join(terms_unmatched[:10])}")
            if len(terms_unmatched) > 10:
                print(f"  ... and {len(terms_unmatched) - 10} more")

    finally:
        conn.close()

    print("\nMigration complete!")
    print(f"  Subject: {subject['name']} ({subject_id})")
    print(f"  Objectives: {objectives_created}")
    print(f"  Concepts linked: {linked}")
    print(f"  Reviews imported: {reviews_imported}")
    print(f"  Error patterns: {errors_imported}")


if __name__ == "__main__":
    main()
