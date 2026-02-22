"""SynapseForge full backup: export all tables to JSON + upload to Google Docs.

Usage:
    python scripts/backup_forge.py              # Full backup (local + Google Docs)
    python scripts/backup_forge.py --local-only # Local JSON only, skip Google Docs
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure jaybrain package is importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jaybrain.config import DB_PATH, DATA_DIR


BACKUP_DIR = DATA_DIR / "backups"

# All SynapseForge tables to export
FORGE_TABLES = [
    "forge_subjects",
    "forge_objectives",
    "forge_concepts",
    "forge_concept_objectives",
    "forge_reviews",
    "forge_streaks",
    "forge_error_patterns",
    "forge_prerequisites",
]


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return {k: row[k] for k in row.keys()}


def export_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Export all rows from a table as a list of dicts."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_table_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def run_backup(local_only: bool = False) -> dict:
    """Run full SynapseForge backup.

    Returns dict with local_path, and optionally gdoc URLs.
    """
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    backup_data = {
        "backup_timestamp": datetime.now(timezone.utc).isoformat(),
        "db_path": str(DB_PATH),
        "db_size_bytes": DB_PATH.stat().st_size,
        "tables": {},
    }

    # Export each table
    print("Exporting SynapseForge tables...")
    for table in FORGE_TABLES:
        try:
            count = get_table_count(conn, table)
            rows = export_table(conn, table)
            backup_data["tables"][table] = {
                "count": count,
                "rows": rows,
            }
            print(f"  {table}: {count} rows")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")
            backup_data["tables"][table] = {"count": 0, "rows": [], "error": str(e)}

    conn.close()

    # Save locally
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = BACKUP_DIR / f"synapseforge_backup_{timestamp}.json"
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)
    local_size = local_path.stat().st_size
    print(f"\nLocal backup saved: {local_path} ({local_size:,} bytes)")

    result = {"local_path": str(local_path), "local_size_bytes": local_size}

    if local_only:
        return result

    # Upload to Google Docs
    print("\nUploading to Google Docs...")
    try:
        from jaybrain.gdocs import create_google_doc, find_or_create_folder

        # Find or create 'Homelab Backups' folder
        parent_result = find_or_create_folder("Homelab Backups")
        if "error" in parent_result:
            print(f"  Failed to find/create 'Homelab Backups': {parent_result['error']}")
            return result
        parent_id = parent_result["folder_id"]
        print(f"  Homelab Backups folder: {parent_id} (created={parent_result['created']})")

        # Create dated subfolder
        date_folder_name = f"SynapseForge Backup {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        sub_result = find_or_create_folder(date_folder_name, parent_id=parent_id)
        if "error" in sub_result:
            print(f"  Failed to create subfolder: {sub_result['error']}")
            return result
        folder_id = sub_result["folder_id"]
        print(f"  Subfolder: {date_folder_name} ({folder_id})")

        # Build summary doc
        summary_md = _build_summary_markdown(backup_data)
        summary_result = create_google_doc(
            f"SynapseForge Backup Summary - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            summary_md,
            folder_id=folder_id,
        )
        if "error" not in summary_result:
            print(f"  Summary doc: {summary_result['doc_url']}")
            result["summary_doc_url"] = summary_result["doc_url"]
        else:
            print(f"  Summary doc error: {summary_result['error']}")

        # Build concepts data doc
        concepts_md = _build_concepts_markdown(backup_data)
        concepts_result = create_google_doc(
            f"SynapseForge Concepts Data - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            concepts_md,
            folder_id=folder_id,
        )
        if "error" not in concepts_result:
            print(f"  Concepts doc: {concepts_result['doc_url']}")
            result["concepts_doc_url"] = concepts_result["doc_url"]
        else:
            print(f"  Concepts doc error: {concepts_result['error']}")

        # Build reviews + error patterns doc
        reviews_md = _build_reviews_markdown(backup_data)
        reviews_result = create_google_doc(
            f"SynapseForge Reviews Data - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            reviews_md,
            folder_id=folder_id,
        )
        if "error" not in reviews_result:
            print(f"  Reviews doc: {reviews_result['doc_url']}")
            result["reviews_doc_url"] = reviews_result["doc_url"]
        else:
            print(f"  Reviews doc error: {reviews_result['error']}")

        print("\nGoogle Docs backup complete.")

    except ImportError as e:
        print(f"  Google Docs libraries not available: {e}")
    except Exception as e:
        print(f"  Google Docs upload failed: {e}")

    return result


def _build_summary_markdown(data: dict) -> str:
    """Build a markdown summary of the backup."""
    lines = [
        "# SynapseForge Backup Summary",
        "",
        f"**Backup timestamp:** {data['backup_timestamp']}",
        f"**Database size:** {data['db_size_bytes']:,} bytes",
        "",
        "## Table Counts",
        "",
        "| Table | Rows |",
        "|-------|------|",
    ]

    for table, info in data["tables"].items():
        lines.append(f"| {table} | {info['count']} |")

    # Subject details
    subjects = data["tables"].get("forge_subjects", {}).get("rows", [])
    if subjects:
        lines += ["", "## Subjects", ""]
        for s in subjects:
            lines.append(f"- **{s['name']}** ({s['short_name']}): pass={s['pass_score']}, "
                         f"questions={s['total_questions']}, time={s['time_limit_minutes']}min")

    # Objective breakdown
    objectives = data["tables"].get("forge_objectives", {}).get("rows", [])
    if objectives:
        lines += ["", "## Objectives by Domain", ""]
        domains = {}
        for o in objectives:
            d = o.get("domain", "Unknown")
            domains.setdefault(d, []).append(o)
        for domain, objs in sorted(domains.items()):
            total_weight = sum(o.get("exam_weight", 0) for o in objs)
            lines.append(f"### {domain} (weight: {total_weight:.0%})")
            lines.append("")
            for o in sorted(objs, key=lambda x: x.get("code", "")):
                lines.append(f"- **{o['code']}** {o['title']} (weight: {o['exam_weight']:.2%})")
            lines.append("")

    # Concept stats
    concepts = data["tables"].get("forge_concepts", {}).get("rows", [])
    if concepts:
        lines += ["", "## Concept Statistics", ""]
        total = len(concepts)
        reviewed = sum(1 for c in concepts if c.get("review_count", 0) > 0)
        avg_mastery = sum(c.get("mastery_level", 0) for c in concepts) / total if total else 0
        lines.append(f"- **Total concepts:** {total}")
        lines.append(f"- **Reviewed at least once:** {reviewed}")
        lines.append(f"- **Average mastery:** {avg_mastery:.1%}")
        lines.append("")

        # Mastery distribution
        buckets = {"Spark (0-20%)": 0, "Ember (20-40%)": 0, "Flame (40-60%)": 0,
                   "Blaze (60-80%)": 0, "Inferno (80-95%)": 0, "Forged (95%+)": 0}
        for c in concepts:
            m = c.get("mastery_level", 0)
            if m >= 0.95:
                buckets["Forged (95%+)"] += 1
            elif m >= 0.80:
                buckets["Inferno (80-95%)"] += 1
            elif m >= 0.60:
                buckets["Blaze (60-80%)"] += 1
            elif m >= 0.40:
                buckets["Flame (40-60%)"] += 1
            elif m >= 0.20:
                buckets["Ember (20-40%)"] += 1
            else:
                buckets["Spark (0-20%)"] += 1

        lines.append("| Mastery Level | Count |")
        lines.append("|---------------|-------|")
        for name, count in buckets.items():
            lines.append(f"| {name} | {count} |")

    # Streak summary
    streaks = data["tables"].get("forge_streaks", {}).get("rows", [])
    if streaks:
        lines += ["", "## Study Streak History", ""]
        total_reviewed = sum(s.get("concepts_reviewed", 0) for s in streaks)
        total_added = sum(s.get("concepts_added", 0) for s in streaks)
        total_time = sum(s.get("time_spent_seconds", 0) for s in streaks)
        lines.append(f"- **Days with activity:** {len(streaks)}")
        lines.append(f"- **Total concepts reviewed:** {total_reviewed}")
        lines.append(f"- **Total concepts added:** {total_added}")
        lines.append(f"- **Total study time:** {total_time // 3600}h {(total_time % 3600) // 60}m")

    # Error patterns summary
    errors = data["tables"].get("forge_error_patterns", {}).get("rows", [])
    if errors:
        lines += ["", "## Error Patterns", ""]
        by_type = {}
        for e in errors:
            t = e.get("error_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        lines.append("| Error Type | Count |")
        lines.append("|------------|-------|")
        for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"| {t} | {count} |")

    return "\n".join(lines)


def _build_concepts_markdown(data: dict) -> str:
    """Build a markdown doc with all concept data."""
    concepts = data["tables"].get("forge_concepts", {}).get("rows", [])
    mappings = data["tables"].get("forge_concept_objectives", {}).get("rows", [])

    # Build concept->objectives lookup
    concept_objs = {}
    for m in mappings:
        concept_objs.setdefault(m["concept_id"], []).append(m["objective_id"])

    lines = [
        "# SynapseForge Concepts Data",
        "",
        f"**Total concepts:** {len(concepts)}",
        f"**Backup date:** {data['backup_timestamp']}",
        "",
    ]

    # Sort by subject_id, then category, then term
    concepts.sort(key=lambda c: (c.get("subject_id", ""), c.get("category", ""), c.get("term", "")))

    for c in concepts:
        lines.append(f"## {c['term']}")
        lines.append("")
        lines.append(f"- **ID:** {c['id']}")
        lines.append(f"- **Definition:** {c['definition']}")
        lines.append(f"- **Category:** {c.get('category', 'general')}")
        lines.append(f"- **Difficulty:** {c.get('difficulty', 'beginner')}")
        lines.append(f"- **Bloom Level:** {c.get('bloom_level', 'remember')}")
        lines.append(f"- **Subject ID:** {c.get('subject_id', '')}")
        lines.append(f"- **Tags:** {c.get('tags', '[]')}")
        lines.append(f"- **Mastery:** {c.get('mastery_level', 0):.2f}")
        lines.append(f"- **Reviews:** {c.get('review_count', 0)} (correct: {c.get('correct_count', 0)})")
        lines.append(f"- **Last Reviewed:** {c.get('last_reviewed', 'never')}")
        lines.append(f"- **Next Review:** {c.get('next_review', 'N/A')}")
        lines.append(f"- **Created:** {c.get('created_at', '')}")
        obj_ids = concept_objs.get(c["id"], [])
        if obj_ids:
            lines.append(f"- **Objectives:** {', '.join(obj_ids)}")
        if c.get("notes"):
            lines.append(f"- **Notes:** {c['notes']}")
        if c.get("source"):
            lines.append(f"- **Source:** {c['source']}")
        if c.get("related_jaybrain_component"):
            lines.append(f"- **JayBrain Component:** {c['related_jaybrain_component']}")
        lines.append("")

    return "\n".join(lines)


def _build_reviews_markdown(data: dict) -> str:
    """Build a markdown doc with reviews, streaks, and error data."""
    reviews = data["tables"].get("forge_reviews", {}).get("rows", [])
    errors = data["tables"].get("forge_error_patterns", {}).get("rows", [])
    streaks = data["tables"].get("forge_streaks", {}).get("rows", [])

    lines = [
        "# SynapseForge Reviews and Activity Data",
        "",
        f"**Total reviews:** {len(reviews)}",
        f"**Total error patterns:** {len(errors)}",
        f"**Total streak days:** {len(streaks)}",
        f"**Backup date:** {data['backup_timestamp']}",
        "",
    ]

    # Reviews table (recent first, cap display at 500 for doc size)
    lines += ["## Reviews (most recent first)", ""]
    lines.append("| # | Concept ID | Outcome | Confidence | Correct | Error Type | Date |")
    lines.append("|---|------------|---------|------------|---------|------------|------|")
    reviews_sorted = sorted(reviews, key=lambda r: r.get("reviewed_at", ""), reverse=True)
    for i, r in enumerate(reviews_sorted[:500]):
        correct_str = "Y" if r.get("was_correct") == 1 else ("N" if r.get("was_correct") == 0 else "-")
        lines.append(
            f"| {i+1} | {r.get('concept_id', '')} | {r.get('outcome', '')} | "
            f"{r.get('confidence', '')} | {correct_str} | {r.get('error_type', '')} | "
            f"{r.get('reviewed_at', '')[:10]} |"
        )
    if len(reviews) > 500:
        lines.append(f"| ... | *{len(reviews) - 500} more rows in local JSON backup* | | | | | |")
    lines.append("")

    # Error patterns
    if errors:
        lines += ["## Error Patterns", ""]
        lines.append("| Concept ID | Error Type | Bloom Level | Details | Date |")
        lines.append("|------------|------------|-------------|---------|------|")
        for e in errors:
            details = (e.get("details", "") or "")[:80]
            lines.append(
                f"| {e.get('concept_id', '')} | {e.get('error_type', '')} | "
                f"{e.get('bloom_level', '')} | {details} | {e.get('created_at', '')[:10]} |"
            )
        lines.append("")

    # Streaks
    if streaks:
        lines += ["## Daily Activity Streaks", ""]
        lines.append("| Date | Reviewed | Added | Time (sec) |")
        lines.append("|------|----------|-------|------------|")
        streaks_sorted = sorted(streaks, key=lambda s: s.get("date", ""), reverse=True)
        for s in streaks_sorted:
            lines.append(
                f"| {s.get('date', '')} | {s.get('concepts_reviewed', 0)} | "
                f"{s.get('concepts_added', 0)} | {s.get('time_spent_seconds', 0)} |"
            )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    local_only = "--local-only" in sys.argv
    result = run_backup(local_only=local_only)
    print(f"\nBackup result: {json.dumps(result, indent=2)}")
