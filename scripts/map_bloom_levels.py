"""Map Bloom's taxonomy levels to Security+ SY0-701 concepts based on objective type.

Bloom levels: remember, understand, apply, analyze (ascending complexity)

Mapping strategy:
- Domain 1 (General Security Concepts): mostly remember/understand -- foundational terms
- Domain 2 (Threats & Vulnerabilities): understand/apply -- need to recognize and identify
- Domain 3 (Security Architecture): apply/analyze -- design and evaluate architectures
- Domain 4 (Security Operations): apply/analyze -- operational procedures and investigations
- Domain 5 (Program Management): understand/analyze -- governance, risk, compliance

Within each domain, the objective code hints at depth:
- "Compare" / "Explain" / "Summarize" -> understand
- "Given a scenario" -> apply or analyze
- "Implement" / "Configure" -> apply
- "Analyze" / "Investigate" -> analyze
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jaybrain.config import DB_PATH
from jaybrain.db import get_connection, get_forge_objectives, update_forge_concept

# Objective code -> Bloom level mapping based on CompTIA SY0-701 objectives
# Reference: Official CompTIA SY0-701 exam objectives PDF
OBJECTIVE_BLOOM_MAP = {
    # Domain 1: General Security Concepts (12%)
    "1.1": "remember",     # Compare and contrast security controls
    "1.2": "understand",   # Summarize fundamental security concepts
    "1.3": "understand",   # Explain importance of change management
    "1.4": "understand",   # Explain importance of using cryptographic solutions

    # Domain 2: Threats, Vulnerabilities, and Mitigations (22%)
    "2.1": "understand",   # Compare and contrast threat actors
    "2.2": "understand",   # Explain common threat vectors
    "2.3": "understand",   # Explain various types of vulnerabilities
    "2.4": "apply",        # Given a scenario, analyze indicators of malicious activity
    "2.5": "apply",        # Explain the purpose of mitigation techniques

    # Domain 3: Security Architecture (18%)
    "3.1": "understand",   # Compare and contrast security implications of architectures
    "3.2": "apply",        # Given a scenario, apply security principles to secure enterprise
    "3.3": "understand",   # Compare and contrast data protection concepts
    "3.4": "apply",        # Explain resilience and recovery in security architecture

    # Domain 4: Security Operations (28%)
    "4.1": "apply",        # Given a scenario, apply common security techniques
    "4.2": "analyze",      # Explain security implications of proper hardware/software
    "4.3": "apply",        # Given a scenario, implement and maintain identity management
    "4.4": "analyze",      # Given a scenario, analyze and respond to security events
    "4.5": "apply",        # Given a scenario, modify enterprise capabilities
    "4.6": "apply",        # Given a scenario, implement automation and orchestration
    "4.7": "analyze",      # Explain alerting and monitoring concepts
    "4.8": "apply",        # Given a scenario, use vulnerability management
    "4.9": "analyze",      # Explain security concepts related to incident response

    # Domain 5: Security Program Management and Oversight (20%)
    "5.1": "understand",   # Summarize elements of governance
    "5.2": "understand",   # Explain risk management processes
    "5.3": "analyze",      # Explain third-party risk assessment
    "5.4": "understand",   # Summarize compliance and audit concepts
    "5.5": "understand",   # Explain types and purposes of assessments
    "5.6": "understand",   # Given a scenario, implement security awareness practices
}

# Difficulty-based overrides: advanced concepts get bumped up one level
# (e.g., an "understand" concept that's advanced difficulty becomes "apply")
BLOOM_UPGRADE = {
    "remember": "understand",
    "understand": "apply",
    "apply": "analyze",
    "analyze": "analyze",  # already at max
}


def extract_objective_code(tags: str) -> str:
    """Extract the objective code (e.g., '1.1') from concept tags JSON."""
    import json
    try:
        tag_list = json.loads(tags)
    except (json.JSONDecodeError, TypeError):
        return ""
    for tag in tag_list:
        # Match patterns like "1.1", "2.4", "5.6"
        if len(tag) <= 3 and "." in tag:
            parts = tag.split(".")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return tag
    return ""


def run_bloom_mapping(dry_run: bool = False) -> dict:
    """Map Bloom levels for all Security+ concepts based on their objective.

    Returns stats on what was changed.
    """
    conn = get_connection()
    try:
        # Get all concepts with their tags
        rows = conn.execute(
            "SELECT id, term, tags, difficulty, bloom_level FROM forge_concepts WHERE subject_id != ''"
        ).fetchall()

        stats = {"total": len(rows), "updated": 0, "skipped": 0, "already_correct": 0}
        changes = []

        for row in rows:
            obj_code = extract_objective_code(row["tags"])
            if not obj_code or obj_code not in OBJECTIVE_BLOOM_MAP:
                stats["skipped"] += 1
                continue

            base_bloom = OBJECTIVE_BLOOM_MAP[obj_code]

            # Upgrade advanced concepts one Bloom level
            if row["difficulty"] == "advanced":
                target_bloom = BLOOM_UPGRADE[base_bloom]
            else:
                target_bloom = base_bloom

            current = row["bloom_level"] or "remember"
            if current == target_bloom:
                stats["already_correct"] += 1
                continue

            changes.append({
                "id": row["id"],
                "term": row["term"],
                "old_bloom": current,
                "new_bloom": target_bloom,
                "objective": obj_code,
            })

            if not dry_run:
                update_forge_concept(conn, row["id"], bloom_level=target_bloom)

            stats["updated"] += 1

        return {
            **stats,
            "dry_run": dry_run,
            "sample_changes": changes[:20],
        }
    finally:
        conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    result = run_bloom_mapping(dry_run=dry_run)
    print(f"Bloom Level Mapping {'(DRY RUN)' if dry_run else ''}")
    print(f"  Total concepts: {result['total']}")
    print(f"  Updated: {result['updated']}")
    print(f"  Already correct: {result['already_correct']}")
    print(f"  Skipped (no objective): {result['skipped']}")
    if result["sample_changes"]:
        print("\nSample changes:")
        for c in result["sample_changes"][:10]:
            print(f"  {c['term']}: {c['old_bloom']} -> {c['new_bloom']} (obj {c['objective']})")
