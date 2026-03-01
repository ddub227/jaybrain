"""SQLite database initialization, schema, and CRUD operations."""

from __future__ import annotations

import json
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from typing import Optional

import sqlite_vec

from .config import DB_PATH, EMBEDDING_DIM, ensure_data_dirs

# Column allowlists for each updatable table (excludes id, created_at).
_UPDATABLE_COLUMNS: dict[str, frozenset[str]] = {
    "tasks": frozenset({
        "title", "description", "status", "priority", "project",
        "tags", "due_date", "updated_at",
    }),
    "knowledge": frozenset({
        "title", "content", "category", "tags", "source", "updated_at",
    }),
    "forge_concepts": frozenset({
        "term", "definition", "category", "difficulty", "tags",
        "related_jaybrain_component", "source", "notes", "mastery_level",
        "review_count", "correct_count", "last_reviewed", "next_review",
        "subject_id", "bloom_level", "updated_at",
    }),
    "job_boards": frozenset({
        "name", "url", "board_type", "tags", "active",
        "last_checked", "content_hash", "updated_at",
    }),
    "applications": frozenset({
        "job_id", "status", "resume_path", "cover_letter_path",
        "applied_date", "notes", "tags", "updated_at",
    }),
    "graph_entities": frozenset({
        "name", "entity_type", "description", "aliases",
        "memory_ids", "properties", "updated_at",
    }),
    "graph_relationships": frozenset({
        "source_entity_id", "target_entity_id", "rel_type", "weight",
        "evidence_ids", "properties", "updated_at",
    }),
    "telegram_bot_state": frozenset({
        "pid", "started_at", "last_heartbeat", "messages_in",
        "messages_out", "poll_offset", "last_error",
    }),
    "cram_topics": frozenset({
        "topic", "description", "source_question", "source_answer",
        "understanding", "review_count", "correct_count",
        "forge_concept_id", "last_reviewed", "updated_at",
    }),
    "news_feed_sources": frozenset({
        "name", "url", "source_type", "tags", "active",
        "last_polled", "last_error", "articles_total", "updated_at",
    }),
    "signalforge_articles": frozenset({
        "resolved_url", "content_path", "word_count", "char_count",
        "fetch_status", "fetch_error", "fetched_at", "expires_at",
        "updated_at",
    }),
    "signalforge_clusters": frozenset({
        "label", "article_count", "source_count", "avg_similarity",
        "significance", "updated_at",
    }),
    "signalforge_synthesis": frozenset({
        "title", "content", "cluster_ids", "cluster_count",
        "article_count", "word_count", "model_used",
        "input_tokens", "output_tokens",
        "gdoc_id", "gdoc_url", "updated_at",
    }),
}


def _validate_fields(table: str, fields: dict) -> None:
    """Raise ValueError if any field key is not in the table's column allowlist."""
    allowed = _UPDATABLE_COLUMNS.get(table)
    if allowed is None:
        raise ValueError(f"No column allowlist defined for table '{table}'")
    bad = set(fields.keys()) - allowed
    if bad:
        raise ValueError(
            f"Invalid column(s) for {table}: {sorted(bad)}. "
            f"Allowed: {sorted(allowed)}"
        )


def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a list of floats into bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def _deserialize_f32(data: bytes) -> list[float]:
    """Deserialize bytes back into a list of floats."""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def fts5_safe_query(query: str) -> str:
    """Convert a natural language query into a safe FTS5 query.

    Wraps individual words in quotes to avoid FTS5 syntax errors from
    special characters like AND, OR, NOT, -, etc.
    """
    words = query.split()
    safe_words = []
    for word in words:
        cleaned = "".join(c for c in word if c.isalnum() or c == "_")
        if cleaned:
            safe_words.append(f'"{cleaned}"')
    return " ".join(safe_words)


def get_connection() -> sqlite3.Connection:
    """Get a database connection with sqlite-vec loaded."""
    ensure_data_dirs()
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_db() -> None:
    """Initialize the database schema and run migrations."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _run_migrations(conn)
    finally:
        conn.close()


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version. Returns 0 if no versions applied."""
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return row[0] or 0
    except Exception:
        return 0


def _set_schema_version(
    conn: sqlite3.Connection, version: int, description: str
) -> None:
    """Record a migration as applied."""
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
        (version, description, datetime.now(timezone.utc).isoformat()),
    )


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for existing databases.

    Each migration is guarded by both a version check and a column-existence
    check so it is safe to run on databases created before version tracking.
    """
    current = _get_schema_version(conn)

    # --- Migration 1: memories.session_id + backfill ---
    if current < 1:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "session_id" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN session_id TEXT")

        orphans = conn.execute(
            "SELECT id, created_at FROM memories WHERE session_id IS NULL"
        ).fetchall()
        if orphans:
            sessions = conn.execute(
                "SELECT id, started_at FROM sessions ORDER BY started_at DESC"
            ).fetchall()
            if sessions:
                for mem in orphans:
                    best_sid = sessions[0]["id"]
                    best_diff = float("inf")
                    for s in sessions:
                        try:
                            m_dt = datetime.fromisoformat(mem["created_at"])
                            s_dt = datetime.fromisoformat(s["started_at"])
                            diff = abs((m_dt - s_dt).total_seconds())
                            if diff < best_diff:
                                best_diff = diff
                                best_sid = s["id"]
                        except (ValueError, TypeError):
                            continue
                    conn.execute(
                        "UPDATE memories SET session_id = ? WHERE id = ?",
                        (best_sid, mem["id"]),
                    )

        _set_schema_version(conn, 1, "Add memories.session_id and backfill orphans")
        conn.commit()

    # --- Migration 2: forge_concepts v2 columns ---
    if current < 2:
        forge_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(forge_concepts)").fetchall()
        }
        if forge_cols:
            if "subject_id" not in forge_cols:
                conn.execute("ALTER TABLE forge_concepts ADD COLUMN subject_id TEXT DEFAULT ''")
            if "bloom_level" not in forge_cols:
                conn.execute("ALTER TABLE forge_concepts ADD COLUMN bloom_level TEXT DEFAULT 'remember'")

        _set_schema_version(conn, 2, "Add forge_concepts subject_id and bloom_level")
        conn.commit()

    # --- Migration 3: forge_reviews v2 columns ---
    if current < 3:
        review_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(forge_reviews)").fetchall()
        }
        if review_cols:
            if "was_correct" not in review_cols:
                conn.execute("ALTER TABLE forge_reviews ADD COLUMN was_correct INTEGER DEFAULT NULL")
            if "error_type" not in review_cols:
                conn.execute("ALTER TABLE forge_reviews ADD COLUMN error_type TEXT DEFAULT ''")
            if "bloom_level" not in review_cols:
                conn.execute("ALTER TABLE forge_reviews ADD COLUMN bloom_level TEXT DEFAULT ''")
            if "subject_id" not in review_cols:
                conn.execute("ALTER TABLE forge_reviews ADD COLUMN subject_id TEXT DEFAULT ''")

        _set_schema_version(conn, 3, "Add forge_reviews v2 columns")
        conn.commit()

    # --- Migration 4: tasks.queue_position ---
    if current < 4:
        task_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "queue_position" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN queue_position INTEGER DEFAULT NULL")

        _set_schema_version(conn, 4, "Add tasks.queue_position")
        conn.commit()

    # --- Migration 5: session checkpoint columns ---
    if current < 5:
        session_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "checkpoint_summary" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN checkpoint_summary TEXT NOT NULL DEFAULT ''")
        if "checkpoint_decisions" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN checkpoint_decisions TEXT NOT NULL DEFAULT '[]'")
        if "checkpoint_next_steps" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN checkpoint_next_steps TEXT NOT NULL DEFAULT '[]'")
        if "checkpoint_at" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN checkpoint_at TEXT")

        _set_schema_version(conn, 5, "Add session checkpoint columns")
        conn.commit()

    # --- Migration 6: forge_concepts subject_id index ---
    if current < 6:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_forge_concepts_subject_id ON forge_concepts(subject_id)"
        )
        _set_schema_version(conn, 6, "Add forge_concepts subject_id index")
        conn.commit()

    # --- Migration 7: daemon_state table ---
    if current < 7:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daemon_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                pid INTEGER,
                started_at TEXT,
                last_heartbeat TEXT,
                modules TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'stopped'
            );
        """)
        _set_schema_version(conn, 7, "Add daemon_state table")
        conn.commit()

    # --- Migration 8: conversation archive tables ---
    if current < 8:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversation_archive_runs (
                id TEXT PRIMARY KEY,
                run_at TEXT NOT NULL,
                conversations_found INTEGER DEFAULT 0,
                conversations_archived INTEGER DEFAULT 0,
                gdoc_id TEXT DEFAULT '',
                gdoc_url TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_archive_sessions (
                session_id TEXT PRIMARY KEY,
                project_dir TEXT DEFAULT '',
                jsonl_path TEXT DEFAULT '',
                summary_preview TEXT DEFAULT '',
                archived_in_run TEXT DEFAULT '',
                archived_at TEXT NOT NULL
            );
        """)
        _set_schema_version(conn, 8, "Add conversation archive tables")
        conn.commit()

    # --- Migration 9: life domains tables ---
    if current < 9:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS life_domains (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT '',
                hours_per_week REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_life_domains_priority ON life_domains(priority);

            CREATE TABLE IF NOT EXISTS life_goals (
                id TEXT PRIMARY KEY,
                domain_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                target_date TEXT,
                progress REAL NOT NULL DEFAULT 0.0,
                auto_metric_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (domain_id) REFERENCES life_domains(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_life_goals_domain ON life_goals(domain_id);
            CREATE INDEX IF NOT EXISTS idx_life_goals_status ON life_goals(status);

            CREATE TABLE IF NOT EXISTS life_sub_goals (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                progress REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES life_goals(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_life_sub_goals_goal ON life_sub_goals(goal_id);

            CREATE TABLE IF NOT EXISTS life_goal_dependencies (
                goal_id TEXT NOT NULL,
                depends_on_goal_id TEXT NOT NULL,
                PRIMARY KEY (goal_id, depends_on_goal_id),
                FOREIGN KEY (goal_id) REFERENCES life_goals(id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_goal_id) REFERENCES life_goals(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS life_goal_metrics (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL DEFAULT 'manual',
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES life_goals(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_life_goal_metrics_goal ON life_goal_metrics(goal_id);
            CREATE INDEX IF NOT EXISTS idx_life_goal_metrics_date ON life_goal_metrics(recorded_at);
        """)
        _set_schema_version(conn, 9, "Add life domains tables")
        conn.commit()

    # --- Migration 10: heartbeat_log table ---
    if current < 10:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS heartbeat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_name TEXT NOT NULL,
                triggered INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                notified INTEGER NOT NULL DEFAULT 0,
                checked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_heartbeat_log_check ON heartbeat_log(check_name);
            CREATE INDEX IF NOT EXISTS idx_heartbeat_log_date ON heartbeat_log(checked_at);
        """)
        _set_schema_version(conn, 10, "Add heartbeat_log table")
        conn.commit()

    # --- Migration 11: Phase 4 tables (events, onboarding, personality) ---
    if current < 11:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS discovered_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                event_date TEXT,
                location TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                relevance_score REAL NOT NULL DEFAULT 0.0,
                tags TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON discovered_events(event_date);
            CREATE INDEX IF NOT EXISTS idx_events_status ON discovered_events(status);

            CREATE TABLE IF NOT EXISTS onboarding_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_step INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 0,
                responses TEXT NOT NULL DEFAULT '{}',
                completed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS personality_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                style TEXT NOT NULL DEFAULT 'default',
                energy_level REAL NOT NULL DEFAULT 0.7,
                humor_level REAL NOT NULL DEFAULT 0.5,
                traits TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
        """)
        _set_schema_version(conn, 11, "Add events, onboarding, personality tables")
        conn.commit()

    # --- Migration 12: Add content_hash to job_boards for change detection ---
    if current < 12:
        try:
            conn.execute("ALTER TABLE job_boards ADD COLUMN content_hash TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        _set_schema_version(conn, 12, "Add job_boards.content_hash for auto-fetch")
        conn.commit()

    # --- Migration 13: Trash manifest table ---
    if current < 13:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trash_manifest (
                id TEXT PRIMARY KEY,
                original_path TEXT NOT NULL,
                trash_path TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                is_dir INTEGER NOT NULL DEFAULT 0,
                auto_deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_trash_expires
                ON trash_manifest(expires_at);
            CREATE INDEX IF NOT EXISTS idx_trash_category
                ON trash_manifest(category);
        """)
        _set_schema_version(conn, 13, "Add trash_manifest table for soft-delete recycle bin")
        conn.commit()

    # --- Migration 14: Cram topics and reviews tables ---
    if current < 14:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cram_topics (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_question TEXT NOT NULL DEFAULT '',
                source_answer TEXT NOT NULL DEFAULT '',
                understanding REAL NOT NULL DEFAULT 0.0,
                review_count INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                forge_concept_id TEXT,
                last_reviewed TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (forge_concept_id) REFERENCES forge_concepts(id)
                    ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cram_topics_understanding
                ON cram_topics(understanding);
            CREATE INDEX IF NOT EXISTS idx_cram_topics_forge_link
                ON cram_topics(forge_concept_id);

            CREATE TABLE IF NOT EXISTS cram_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                was_correct INTEGER NOT NULL,
                confidence INTEGER NOT NULL DEFAULT 3,
                notes TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES cram_topics(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_cram_reviews_topic
                ON cram_reviews(topic_id);
            CREATE INDEX IF NOT EXISTS idx_cram_reviews_date
                ON cram_reviews(reviewed_at);
        """)
        _set_schema_version(conn, 14, "Add cram_topics and cram_reviews tables")
        conn.commit()

    # --- Migration 15: Full daemon instrumentation (Mistakes #011-#015) ---
    if current < 15:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daemon_execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                result_summary TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                telegram_sent INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_daemon_exec_module
                ON daemon_execution_log(module_name);
            CREATE INDEX IF NOT EXISTS idx_daemon_exec_date
                ON daemon_execution_log(started_at);

            CREATE TABLE IF NOT EXISTS daemon_lifecycle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                pid INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                modules_registered TEXT NOT NULL DEFAULT '[]',
                trigger TEXT NOT NULL DEFAULT 'manual',
                error_message TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_daemon_lifecycle_date
                ON daemon_lifecycle_log(timestamp);

            CREATE TABLE IF NOT EXISTS telegram_send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                caller TEXT NOT NULL DEFAULT 'unknown',
                chat_id TEXT NOT NULL DEFAULT '',
                message_preview TEXT NOT NULL DEFAULT '',
                chunks_sent INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'unknown',
                error_message TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_telegram_send_date
                ON telegram_send_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_telegram_send_caller
                ON telegram_send_log(caller);
        """)
        _set_schema_version(conn, 15, "Add daemon execution, lifecycle, and telegram send logs")
        conn.commit()

    # --- Migration 16: File deletion log + git shadow log ---
    if current < 16:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS file_deletion_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'file_deleted',
                file_size INTEGER,
                source_context TEXT NOT NULL DEFAULT '',
                pid INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_file_deletion_timestamp
                ON file_deletion_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_file_deletion_path
                ON file_deletion_log(file_path);

            CREATE TABLE IF NOT EXISTS git_shadow_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                stash_hash TEXT NOT NULL,
                changed_files TEXT NOT NULL DEFAULT '[]',
                repo_path TEXT NOT NULL,
                branch TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_git_shadow_timestamp
                ON git_shadow_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_git_shadow_repo
                ON git_shadow_log(repo_path);
        """)
        _set_schema_version(conn, 16, "Add file_deletion_log and git_shadow_log tables")
        conn.commit()

    # --- Migration 17: Feedly article dedup tracking ---
    if current < 17:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feedly_articles (
                feedly_id TEXT PRIMARY KEY,
                knowledge_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feedly_articles_fetched
                ON feedly_articles(fetched_at);
        """)
        _set_schema_version(conn, 17, "Add feedly_articles dedup tracking table")
        conn.commit()

    # --- Migration 18: News feed sources and article dedup ---
    if current < 18:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS news_feed_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'rss',
                tags TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                last_polled TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                articles_total INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_feed_sources_active
                ON news_feed_sources(active);

            CREATE TABLE IF NOT EXISTS news_feed_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_article_id TEXT NOT NULL,
                knowledge_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES news_feed_sources(id)
                    ON DELETE CASCADE,
                UNIQUE(source_id, source_article_id)
            );
            CREATE INDEX IF NOT EXISTS idx_news_feed_articles_source
                ON news_feed_articles(source_id);
            CREATE INDEX IF NOT EXISTS idx_news_feed_articles_url
                ON news_feed_articles(url);
            CREATE INDEX IF NOT EXISTS idx_news_feed_articles_fetched
                ON news_feed_articles(fetched_at);
        """)
        _set_schema_version(conn, 18, "Add news_feed_sources and news_feed_articles tables")
        conn.commit()

    # --- Migration 19: SignalForge articles (full-text fetch tracking) ---
    if current < 19:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signalforge_articles (
                id TEXT PRIMARY KEY,
                knowledge_id TEXT NOT NULL,
                resolved_url TEXT NOT NULL DEFAULT '',
                content_path TEXT NOT NULL DEFAULT '',
                word_count INTEGER NOT NULL DEFAULT 0,
                char_count INTEGER NOT NULL DEFAULT 0,
                fetch_status TEXT NOT NULL DEFAULT 'pending',
                fetch_error TEXT NOT NULL DEFAULT '',
                fetched_at TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (knowledge_id) REFERENCES knowledge(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_signalforge_articles_status
                ON signalforge_articles(fetch_status);
            CREATE INDEX IF NOT EXISTS idx_signalforge_articles_knowledge
                ON signalforge_articles(knowledge_id);
            CREATE INDEX IF NOT EXISTS idx_signalforge_articles_expires
                ON signalforge_articles(expires_at);
        """)
        _set_schema_version(conn, 19, "Add signalforge_articles table for full-text fetch tracking")
        conn.commit()

    # --- Migration 20: SignalForge story clusters ---
    if current < 20:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signalforge_clusters (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL DEFAULT '',
                article_count INTEGER NOT NULL DEFAULT 0,
                source_count INTEGER NOT NULL DEFAULT 0,
                avg_similarity REAL NOT NULL DEFAULT 0.0,
                significance REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_signalforge_clusters_significance
                ON signalforge_clusters(significance DESC);
            CREATE INDEX IF NOT EXISTS idx_signalforge_clusters_created
                ON signalforge_clusters(created_at);

            CREATE TABLE IF NOT EXISTS signalforge_cluster_articles (
                cluster_id TEXT NOT NULL,
                knowledge_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (cluster_id, knowledge_id),
                FOREIGN KEY (cluster_id) REFERENCES signalforge_clusters(id) ON DELETE CASCADE,
                FOREIGN KEY (knowledge_id) REFERENCES knowledge(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_signalforge_ca_knowledge
                ON signalforge_cluster_articles(knowledge_id);
        """)
        _set_schema_version(conn, 20, "Add signalforge_clusters and cluster_articles tables")
        conn.commit()

    # --- Migration 21: SignalForge synthesis ---
    if current < 21:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signalforge_synthesis (
                id TEXT PRIMARY KEY,
                synthesis_date TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                cluster_ids TEXT NOT NULL DEFAULT '[]',
                cluster_count INTEGER NOT NULL DEFAULT 0,
                article_count INTEGER NOT NULL DEFAULT 0,
                word_count INTEGER NOT NULL DEFAULT 0,
                model_used TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                gdoc_id TEXT NOT NULL DEFAULT '',
                gdoc_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signalforge_synthesis_date
                ON signalforge_synthesis(synthesis_date);
            CREATE INDEX IF NOT EXISTS idx_signalforge_synthesis_created
                ON signalforge_synthesis(created_at);
        """)
        _set_schema_version(conn, 21, "Add signalforge_synthesis table")
        conn.commit()


_SCHEMA_SQL_TEMPLATE = """
-- Memories table
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'semantic',
    tags TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Memories indexes
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
CREATE INDEX IF NOT EXISTS idx_memories_session_id ON memories(session_id);

-- Memories FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    tags,
    content=memories,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.rowid, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.rowid, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tags)
    VALUES ('delete', old.rowid, old.content, old.tags);
    INSERT INTO memories_fts(rowid, content, tags)
    VALUES (new.rowid, new.content, new.tags);
END;

-- Memories vector table for semantic search
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[__EMBEDDING_DIM__]
);

-- Tasks table
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    priority TEXT NOT NULL DEFAULT 'medium',
    project TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    due_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT NOT NULL DEFAULT '',
    decisions_made TEXT NOT NULL DEFAULT '[]',
    next_steps TEXT NOT NULL DEFAULT '[]'
);

-- Knowledge table
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Knowledge indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_created_at ON knowledge(created_at);

-- Knowledge FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title,
    content,
    tags,
    content=knowledge,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
    INSERT INTO knowledge_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;

-- Knowledge vector table
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[__EMBEDDING_DIM__]
);

-- SynapseForge: Concepts table
CREATE TABLE IF NOT EXISTS forge_concepts (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL,
    definition TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    difficulty TEXT NOT NULL DEFAULT 'beginner',
    tags TEXT NOT NULL DEFAULT '[]',
    related_jaybrain_component TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    mastery_level REAL NOT NULL DEFAULT 0.0,
    review_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed TEXT,
    next_review TEXT,
    subject_id TEXT NOT NULL DEFAULT '',
    bloom_level TEXT NOT NULL DEFAULT 'remember',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forge_concepts_category ON forge_concepts(category);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_mastery ON forge_concepts(mastery_level);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_next_review ON forge_concepts(next_review);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_difficulty ON forge_concepts(difficulty);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_subject_id ON forge_concepts(subject_id);

-- SynapseForge: Concepts FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS forge_concepts_fts USING fts5(
    term,
    definition,
    notes,
    tags,
    content=forge_concepts,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS forge_concepts_ai AFTER INSERT ON forge_concepts BEGIN
    INSERT INTO forge_concepts_fts(rowid, term, definition, notes, tags)
    VALUES (new.rowid, new.term, new.definition, new.notes, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS forge_concepts_ad AFTER DELETE ON forge_concepts BEGIN
    INSERT INTO forge_concepts_fts(forge_concepts_fts, rowid, term, definition, notes, tags)
    VALUES ('delete', old.rowid, old.term, old.definition, old.notes, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS forge_concepts_au AFTER UPDATE ON forge_concepts BEGIN
    INSERT INTO forge_concepts_fts(forge_concepts_fts, rowid, term, definition, notes, tags)
    VALUES ('delete', old.rowid, old.term, old.definition, old.notes, old.tags);
    INSERT INTO forge_concepts_fts(rowid, term, definition, notes, tags)
    VALUES (new.rowid, new.term, new.definition, new.notes, new.tags);
END;

-- SynapseForge: Concepts vector table
CREATE VIRTUAL TABLE IF NOT EXISTS forge_concepts_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[__EMBEDDING_DIM__]
);

-- SynapseForge: Reviews table
CREATE TABLE IF NOT EXISTS forge_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 3,
    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL,
    was_correct INTEGER DEFAULT NULL,
    error_type TEXT NOT NULL DEFAULT '',
    bloom_level TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (concept_id) REFERENCES forge_concepts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_forge_reviews_concept ON forge_reviews(concept_id);
CREATE INDEX IF NOT EXISTS idx_forge_reviews_date ON forge_reviews(reviewed_at);

-- SynapseForge: Streaks table
CREATE TABLE IF NOT EXISTS forge_streaks (
    date TEXT PRIMARY KEY,
    concepts_reviewed INTEGER NOT NULL DEFAULT 0,
    concepts_added INTEGER NOT NULL DEFAULT 0,
    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forge_streaks_date ON forge_streaks(date);

-- Job boards table
CREATE TABLE IF NOT EXISTS job_boards (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    board_type TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    last_checked TEXT,
    content_hash TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Job postings table
CREATE TABLE IF NOT EXISTS job_postings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    required_skills TEXT NOT NULL DEFAULT '[]',
    preferred_skills TEXT NOT NULL DEFAULT '[]',
    salary_min INTEGER,
    salary_max INTEGER,
    job_type TEXT NOT NULL DEFAULT 'full_time',
    work_mode TEXT NOT NULL DEFAULT 'remote',
    location TEXT NOT NULL DEFAULT '',
    board_id TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (board_id) REFERENCES job_boards(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings(company);
CREATE INDEX IF NOT EXISTS idx_job_postings_work_mode ON job_postings(work_mode);

-- Job postings FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS job_postings_fts USING fts5(
    title,
    company,
    description,
    required_skills,
    preferred_skills,
    content=job_postings,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS job_postings_ai AFTER INSERT ON job_postings BEGIN
    INSERT INTO job_postings_fts(rowid, title, company, description, required_skills, preferred_skills)
    VALUES (new.rowid, new.title, new.company, new.description, new.required_skills, new.preferred_skills);
END;

CREATE TRIGGER IF NOT EXISTS job_postings_ad AFTER DELETE ON job_postings BEGIN
    INSERT INTO job_postings_fts(job_postings_fts, rowid, title, company, description, required_skills, preferred_skills)
    VALUES ('delete', old.rowid, old.title, old.company, old.description, old.required_skills, old.preferred_skills);
END;

CREATE TRIGGER IF NOT EXISTS job_postings_au AFTER UPDATE ON job_postings BEGIN
    INSERT INTO job_postings_fts(job_postings_fts, rowid, title, company, description, required_skills, preferred_skills)
    VALUES ('delete', old.rowid, old.title, old.company, old.description, old.required_skills, old.preferred_skills);
    INSERT INTO job_postings_fts(rowid, title, company, description, required_skills, preferred_skills)
    VALUES (new.rowid, new.title, new.company, new.description, new.required_skills, new.preferred_skills);
END;

-- Applications table
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    resume_path TEXT NOT NULL DEFAULT '',
    cover_letter_path TEXT NOT NULL DEFAULT '',
    applied_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES job_postings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);

-- Interview prep table
CREATE TABLE IF NOT EXISTS interview_prep (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    prep_type TEXT NOT NULL DEFAULT 'general',
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_interview_prep_app ON interview_prep(application_id);
CREATE INDEX IF NOT EXISTS idx_interview_prep_type ON interview_prep(prep_type);

-- SynapseForge v2: Subjects
CREATE TABLE IF NOT EXISTS forge_subjects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    pass_score REAL NOT NULL DEFAULT 0.0,
    total_questions INTEGER NOT NULL DEFAULT 0,
    time_limit_minutes INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- SynapseForge v2: Objectives
CREATE TABLE IF NOT EXISTS forge_objectives (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    exam_weight REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (subject_id) REFERENCES forge_subjects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_forge_objectives_subject ON forge_objectives(subject_id);

-- SynapseForge v2: Concept-to-Objective mapping
CREATE TABLE IF NOT EXISTS forge_concept_objectives (
    concept_id TEXT NOT NULL,
    objective_id TEXT NOT NULL,
    PRIMARY KEY (concept_id, objective_id),
    FOREIGN KEY (concept_id) REFERENCES forge_concepts(id) ON DELETE CASCADE,
    FOREIGN KEY (objective_id) REFERENCES forge_objectives(id) ON DELETE CASCADE
);

-- SynapseForge v2: Prerequisites DAG
CREATE TABLE IF NOT EXISTS forge_prerequisites (
    concept_id TEXT NOT NULL,
    prerequisite_id TEXT NOT NULL,
    PRIMARY KEY (concept_id, prerequisite_id),
    FOREIGN KEY (concept_id) REFERENCES forge_concepts(id) ON DELETE CASCADE,
    FOREIGN KEY (prerequisite_id) REFERENCES forge_concepts(id) ON DELETE CASCADE
);

-- SynapseForge v2: Error patterns
CREATE TABLE IF NOT EXISTS forge_error_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    error_type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    bloom_level TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES forge_concepts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_forge_errors_concept ON forge_error_patterns(concept_id);
CREATE INDEX IF NOT EXISTS idx_forge_errors_type ON forge_error_patterns(error_type);

-- Memory archive (soft-deleted memories preserved for audit)
CREATE TABLE IF NOT EXISTS memory_archive (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'semantic',
    tags TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archive_reason TEXT NOT NULL DEFAULT '',
    merged_into_id TEXT,
    consolidation_run_id TEXT,
    archived_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_archive_reason ON memory_archive(archive_reason);
CREATE INDEX IF NOT EXISTS idx_memory_archive_merged ON memory_archive(merged_into_id);
CREATE INDEX IF NOT EXISTS idx_memory_archive_date ON memory_archive(archived_at);

-- Consolidation log (audit trail for merge/archive operations)
CREATE TABLE IF NOT EXISTS consolidation_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    source_memory_ids TEXT NOT NULL DEFAULT '[]',
    result_memory_id TEXT,
    merged_content_preview TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consolidation_log_action ON consolidation_log(action);
CREATE INDEX IF NOT EXISTS idx_consolidation_log_date ON consolidation_log(created_at);

-- Knowledge graph: entities
CREATE TABLE IF NOT EXISTS graph_entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '[]',
    memory_ids TEXT NOT NULL DEFAULT '[]',
    properties TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(name);
CREATE INDEX IF NOT EXISTS idx_graph_entities_type ON graph_entities(entity_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_entities_name_type ON graph_entities(name, entity_type);

-- Knowledge graph: relationships
CREATE TABLE IF NOT EXISTS graph_relationships (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    properties TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_entity_id) REFERENCES graph_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_entity_id) REFERENCES graph_entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_graph_rel_source ON graph_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_rel_target ON graph_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_rel_type ON graph_relationships(rel_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_rel_unique ON graph_relationships(source_entity_id, target_entity_id, rel_type);

-- GramCracker: Telegram messages
CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_messages_role ON telegram_messages(role);
CREATE INDEX IF NOT EXISTS idx_telegram_messages_created ON telegram_messages(created_at);

-- GramCracker: Bot state (single-row, id=1 enforced)
CREATE TABLE IF NOT EXISTS telegram_bot_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pid INTEGER,
    started_at TEXT,
    last_heartbeat TEXT,
    messages_in INTEGER NOT NULL DEFAULT 0,
    messages_out INTEGER NOT NULL DEFAULT 0,
    poll_offset INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);

-- Trash manifest (soft-delete recycle bin)
CREATE TABLE IF NOT EXISTS trash_manifest (
    id TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    trash_path TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    is_dir INTEGER NOT NULL DEFAULT 0,
    auto_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trash_expires ON trash_manifest(expires_at);
CREATE INDEX IF NOT EXISTS idx_trash_category ON trash_manifest(category);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

SCHEMA_SQL = _SCHEMA_SQL_TEMPLATE.replace("__EMBEDDING_DIM__", str(EMBEDDING_DIM))


# --- CRUD Helpers ---

def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def insert_memory(
    conn: sqlite3.Connection,
    memory_id: str,
    content: str,
    category: str,
    tags: list[str],
    importance: float,
    embedding: Optional[list[float]] = None,
    session_id: Optional[str] = None,
) -> None:
    """Insert a memory into all tables (memories, FTS, vec) atomically."""
    now = now_iso()
    tags_json = json.dumps(tags)
    conn.execute(
        """INSERT INTO memories (id, content, category, tags, importance, session_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, content, category, tags_json, importance, session_id, now, now),
    )
    if embedding is not None:
        conn.execute(
            "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
            (memory_id, _serialize_f32(embedding)),
        )
    conn.commit()


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> bool:
    """Delete a memory from all tables. Returns True if found."""
    cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    if cursor.rowcount == 0:
        return False
    conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))
    conn.commit()
    return True


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Optional[sqlite3.Row]:
    """Get a single memory by ID."""
    return conn.execute(
        "SELECT * FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()


def get_memories_batch(
    conn: sqlite3.Connection, ids: list[str]
) -> dict[str, sqlite3.Row]:
    """Fetch multiple memories in a single query. Returns {id: row} dict."""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM memories WHERE id IN ({placeholders})", ids  # nosec B608
    ).fetchall()
    return {row["id"]: row for row in rows}


def update_memory_access(conn: sqlite3.Connection, memory_id: str) -> None:
    """Increment access count and update last_accessed timestamp."""
    conn.execute(
        """UPDATE memories SET access_count = access_count + 1,
        last_accessed = ? WHERE id = ?""",
        (now_iso(), memory_id),
    )
    conn.commit()


def search_memories_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[tuple[str, float]]:
    """Full-text search on memories. Returns (id, bm25_score) pairs."""
    rows = conn.execute(
        """SELECT m.id, bm25(memories_fts) as score
        FROM memories_fts
        JOIN memories m ON m.rowid = memories_fts.rowid
        WHERE memories_fts MATCH ?
        ORDER BY score
        LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [(row["id"], row["score"]) for row in rows]


def search_memories_vec(
    conn: sqlite3.Connection,
    embedding: list[float],
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Vector similarity search on memories. Returns (id, distance) pairs."""
    rows = conn.execute(
        """SELECT id, distance
        FROM memories_vec
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?""",
        (_serialize_f32(embedding), limit),
    ).fetchall()
    return [(row["id"], row["distance"]) for row in rows]


def get_all_memories(
    conn: sqlite3.Connection,
    category: Optional[str] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Get all memories, optionally filtered by category."""
    if category:
        return conn.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC LIMIT ?",
            (category, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


# --- Task CRUD ---

def insert_task(
    conn: sqlite3.Connection,
    task_id: str,
    title: str,
    description: str,
    status: str,
    priority: str,
    project: str,
    tags: list[str],
    due_date: Optional[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO tasks (id, title, description, status, priority, project, tags, due_date, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, title, description, status, priority, project, json.dumps(tags), due_date, now, now),
    )
    conn.commit()


def update_task(conn: sqlite3.Connection, task_id: str, **fields) -> bool:
    """Update task fields. Returns True if found."""
    if not fields:
        return False
    _validate_fields("tasks", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    cursor = conn.execute(
        f"UPDATE tasks SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def list_tasks(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    conditions = []
    params: list = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if project:
        conditions.append("project = ?")
        params.append(project)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?", params  # nosec B608
    ).fetchall()


# --- Session CRUD ---

def insert_session(conn: sqlite3.Connection, session_id: str, title: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, started_at) VALUES (?, ?, ?)",
        (session_id, title, now_iso()),
    )
    conn.commit()


def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    summary: str,
    decisions_made: list[str],
    next_steps: list[str],
) -> bool:
    cursor = conn.execute(
        """UPDATE sessions SET ended_at = ?, summary = ?, decisions_made = ?, next_steps = ?
        WHERE id = ?""",
        (now_iso(), summary, json.dumps(decisions_made), json.dumps(next_steps), session_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_latest_session(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()


def get_open_sessions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all sessions that were started but never ended (orphans)."""
    return conn.execute(
        "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC"
    ).fetchall()


def update_session_checkpoint(
    conn: sqlite3.Connection,
    session_id: str,
    checkpoint_summary: str,
    checkpoint_decisions: list[str],
    checkpoint_next_steps: list[str],
) -> bool:
    """Save a rolling checkpoint on an open session. Returns True if found."""
    cursor = conn.execute(
        """UPDATE sessions
        SET checkpoint_summary = ?, checkpoint_decisions = ?,
            checkpoint_next_steps = ?, checkpoint_at = ?
        WHERE id = ? AND ended_at IS NULL""",
        (checkpoint_summary, json.dumps(checkpoint_decisions),
         json.dumps(checkpoint_next_steps), now_iso(), session_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_memories_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Get memories created during a specific session."""
    return conn.execute(
        "SELECT * FROM memories WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()


# --- Knowledge CRUD ---

def insert_knowledge(
    conn: sqlite3.Connection,
    knowledge_id: str,
    title: str,
    content: str,
    category: str,
    tags: list[str],
    source: str,
    embedding: Optional[list[float]] = None,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO knowledge (id, title, content, category, tags, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (knowledge_id, title, content, category, json.dumps(tags), source, now, now),
    )
    if embedding is not None:
        conn.execute(
            "INSERT INTO knowledge_vec (id, embedding) VALUES (?, ?)",
            (knowledge_id, _serialize_f32(embedding)),
        )
    conn.commit()


def update_knowledge(conn: sqlite3.Connection, knowledge_id: str, **fields) -> bool:
    if not fields:
        return False
    _validate_fields("knowledge", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [knowledge_id]
    cursor = conn.execute(
        f"UPDATE knowledge SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


def get_knowledge(conn: sqlite3.Connection, knowledge_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM knowledge WHERE id = ?", (knowledge_id,)
    ).fetchone()


def search_knowledge_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[tuple[str, float]]:
    rows = conn.execute(
        """SELECT k.id, bm25(knowledge_fts) as score
        FROM knowledge_fts
        JOIN knowledge k ON k.rowid = knowledge_fts.rowid
        WHERE knowledge_fts MATCH ?
        ORDER BY score
        LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [(row["id"], row["score"]) for row in rows]


def search_knowledge_vec(
    conn: sqlite3.Connection,
    embedding: list[float],
    limit: int = 20,
) -> list[tuple[str, float]]:
    rows = conn.execute(
        """SELECT id, distance
        FROM knowledge_vec
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?""",
        (_serialize_f32(embedding), limit),
    ).fetchall()
    return [(row["id"], row["distance"]) for row in rows]


# --- Stats ---

def get_stats(conn: sqlite3.Connection) -> dict:
    memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    active_tasks = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE status IN ('todo', 'in_progress', 'blocked')"
    ).fetchone()[0]
    session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    knowledge_count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

    categories = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"
    ).fetchall()
    memories_by_category = {row["category"]: row["cnt"] for row in categories}

    # DB file size
    db_size_mb = 0.0
    try:
        db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    except OSError:
        pass

    return {
        "memory_count": memory_count,
        "task_count": task_count,
        "active_tasks": active_tasks,
        "session_count": session_count,
        "knowledge_count": knowledge_count,
        "db_size_mb": round(db_size_mb, 2),
        "memories_by_category": memories_by_category,
    }


# --- SynapseForge CRUD ---

def insert_forge_concept(
    conn: sqlite3.Connection,
    concept_id: str,
    term: str,
    definition: str,
    category: str,
    difficulty: str,
    tags: list[str],
    related_jaybrain_component: str = "",
    source: str = "",
    notes: str = "",
    next_review: Optional[str] = None,
    embedding: Optional[list[float]] = None,
) -> None:
    """Insert a concept into forge_concepts, FTS, and vec tables."""
    now = now_iso()
    conn.execute(
        """INSERT INTO forge_concepts
        (id, term, definition, category, difficulty, tags,
         related_jaybrain_component, source, notes, next_review, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (concept_id, term, definition, category, difficulty,
         json.dumps(tags), related_jaybrain_component, source, notes,
         next_review or now, now, now),
    )
    if embedding is not None:
        conn.execute(
            "INSERT INTO forge_concepts_vec (id, embedding) VALUES (?, ?)",
            (concept_id, _serialize_f32(embedding)),
        )
    conn.commit()


def update_forge_concept(
    conn: sqlite3.Connection, concept_id: str, commit: bool = True, **fields
) -> bool:
    """Update concept fields. Returns True if found."""
    if not fields:
        return False
    _validate_fields("forge_concepts", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [concept_id]
    cursor = conn.execute(
        f"UPDATE forge_concepts SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    if commit:
        conn.commit()
    return cursor.rowcount > 0


def get_forge_concept(conn: sqlite3.Connection, concept_id: str) -> Optional[sqlite3.Row]:
    """Get a single concept by ID."""
    return conn.execute(
        "SELECT * FROM forge_concepts WHERE id = ?", (concept_id,)
    ).fetchone()


def get_forge_concepts_due(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    """Get concepts due for review (next_review <= now)."""
    now = now_iso()
    return conn.execute(
        """SELECT * FROM forge_concepts
        WHERE next_review <= ?
        ORDER BY next_review ASC
        LIMIT ?""",
        (now, limit),
    ).fetchall()


def get_forge_concepts_new(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    """Get concepts that have never been reviewed."""
    return conn.execute(
        """SELECT * FROM forge_concepts
        WHERE review_count = 0
        ORDER BY created_at ASC
        LIMIT ?""",
        (limit,),
    ).fetchall()


def get_forge_concepts_struggling(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    """Get concepts with low mastery (< 0.3) that have been reviewed at least once."""
    return conn.execute(
        """SELECT * FROM forge_concepts
        WHERE mastery_level < 0.3 AND review_count > 0
        ORDER BY mastery_level ASC
        LIMIT ?""",
        (limit,),
    ).fetchall()


def search_forge_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[tuple[str, float]]:
    """Full-text search on forge concepts. Returns (id, bm25_score) pairs."""
    rows = conn.execute(
        """SELECT c.id, bm25(forge_concepts_fts) as score
        FROM forge_concepts_fts
        JOIN forge_concepts c ON c.rowid = forge_concepts_fts.rowid
        WHERE forge_concepts_fts MATCH ?
        ORDER BY score
        LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [(row["id"], row["score"]) for row in rows]


def search_forge_vec(
    conn: sqlite3.Connection,
    embedding: list[float],
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Vector similarity search on forge concepts. Returns (id, distance) pairs."""
    rows = conn.execute(
        """SELECT id, distance
        FROM forge_concepts_vec
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?""",
        (_serialize_f32(embedding), limit),
    ).fetchall()
    return [(row["id"], row["distance"]) for row in rows]


def insert_forge_review(
    conn: sqlite3.Connection,
    concept_id: str,
    outcome: str,
    confidence: int,
    time_spent_seconds: int = 0,
    notes: str = "",
    was_correct: Optional[int | bool] = None,
    error_type: str = "",
    bloom_level: str = "",
    subject_id: str = "",
    commit: bool = True,
) -> int:
    """Insert a review record. Returns the review ID."""
    now = now_iso()
    was_correct_int = None
    if was_correct is not None:
        was_correct_int = 1 if was_correct else 0
    cursor = conn.execute(
        """INSERT INTO forge_reviews
        (concept_id, outcome, confidence, time_spent_seconds, notes, reviewed_at,
         was_correct, error_type, bloom_level, subject_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (concept_id, outcome, confidence, time_spent_seconds, notes, now,
         was_correct_int, error_type, bloom_level, subject_id),
    )
    if commit:
        conn.commit()
    return cursor.lastrowid


def get_forge_reviews(
    conn: sqlite3.Connection,
    concept_id: str,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """Get reviews for a concept, most recent first."""
    return conn.execute(
        """SELECT * FROM forge_reviews
        WHERE concept_id = ?
        ORDER BY reviewed_at DESC
        LIMIT ?""",
        (concept_id, limit),
    ).fetchall()


def upsert_forge_streak(
    conn: sqlite3.Connection,
    date_str: str,
    concepts_reviewed: int = 0,
    concepts_added: int = 0,
    time_spent_seconds: int = 0,
    commit: bool = True,
) -> None:
    """Upsert a streak record for a given date."""
    now = now_iso()
    conn.execute(
        """INSERT INTO forge_streaks (date, concepts_reviewed, concepts_added, time_spent_seconds, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            concepts_reviewed = concepts_reviewed + excluded.concepts_reviewed,
            concepts_added = concepts_added + excluded.concepts_added,
            time_spent_seconds = time_spent_seconds + excluded.time_spent_seconds""",
        (date_str, concepts_reviewed, concepts_added, time_spent_seconds, now),
    )
    if commit:
        conn.commit()


def get_forge_streak_data(
    conn: sqlite3.Connection, limit: int = 90
) -> list[sqlite3.Row]:
    """Get streak data for the last N days, most recent first."""
    return conn.execute(
        """SELECT * FROM forge_streaks
        ORDER BY date DESC
        LIMIT ?""",
        (limit,),
    ).fetchall()


# --- SynapseForge v2 CRUD ---

def insert_forge_subject(
    conn: sqlite3.Connection,
    subject_id: str,
    name: str,
    short_name: str,
    description: str = "",
    pass_score: float = 0.0,
    total_questions: int = 0,
    time_limit_minutes: int = 0,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO forge_subjects
        (id, name, short_name, description, pass_score, total_questions,
         time_limit_minutes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, name, short_name, description, pass_score,
         total_questions, time_limit_minutes, now, now),
    )
    conn.commit()


def get_forge_subject(conn: sqlite3.Connection, subject_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM forge_subjects WHERE id = ?", (subject_id,)
    ).fetchone()


def list_forge_subjects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM forge_subjects ORDER BY created_at DESC"
    ).fetchall()


def insert_forge_objective(
    conn: sqlite3.Connection,
    objective_id: str,
    subject_id: str,
    code: str,
    title: str,
    domain: str = "",
    exam_weight: float = 0.0,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT OR IGNORE INTO forge_objectives
        (id, subject_id, code, title, domain, exam_weight, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (objective_id, subject_id, code, title, domain, exam_weight, now),
    )
    conn.commit()


def get_forge_objectives(
    conn: sqlite3.Connection, subject_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM forge_objectives WHERE subject_id = ? ORDER BY code",
        (subject_id,),
    ).fetchall()


def get_forge_objective_by_code(
    conn: sqlite3.Connection, subject_id: str, code: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM forge_objectives WHERE subject_id = ? AND code = ?",
        (subject_id, code),
    ).fetchone()


def link_concept_objective(
    conn: sqlite3.Connection, concept_id: str, objective_id: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO forge_concept_objectives (concept_id, objective_id) VALUES (?, ?)",
        (concept_id, objective_id),
    )
    conn.commit()


def get_concepts_for_objective(
    conn: sqlite3.Connection, objective_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT fc.* FROM forge_concepts fc
        JOIN forge_concept_objectives fco ON fc.id = fco.concept_id
        WHERE fco.objective_id = ?
        ORDER BY fc.mastery_level ASC""",
        (objective_id,),
    ).fetchall()


def get_objectives_for_concept(
    conn: sqlite3.Connection, concept_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT fo.* FROM forge_objectives fo
        JOIN forge_concept_objectives fco ON fo.id = fco.objective_id
        WHERE fco.concept_id = ?
        ORDER BY fo.code""",
        (concept_id,),
    ).fetchall()


def insert_forge_prerequisite(
    conn: sqlite3.Connection, concept_id: str, prerequisite_id: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO forge_prerequisites (concept_id, prerequisite_id) VALUES (?, ?)",
        (concept_id, prerequisite_id),
    )
    conn.commit()


def get_prerequisites(
    conn: sqlite3.Connection, concept_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT fc.* FROM forge_concepts fc
        JOIN forge_prerequisites fp ON fc.id = fp.prerequisite_id
        WHERE fp.concept_id = ?""",
        (concept_id,),
    ).fetchall()


def insert_forge_error_pattern(
    conn: sqlite3.Connection,
    concept_id: str,
    error_type: str,
    details: str = "",
    bloom_level: str = "",
    commit: bool = True,
) -> int:
    now = now_iso()
    cursor = conn.execute(
        """INSERT INTO forge_error_patterns
        (concept_id, error_type, details, bloom_level, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (concept_id, error_type, details, bloom_level, now),
    )
    if commit:
        conn.commit()
    return cursor.lastrowid


def get_error_patterns(
    conn: sqlite3.Connection,
    concept_id: str = "",
    error_type: str = "",
    subject_id: str = "",
    limit: int = 100,
) -> list[sqlite3.Row]:
    conditions = []
    params: list = []
    if concept_id:
        conditions.append("ep.concept_id = ?")
        params.append(concept_id)
    if error_type:
        conditions.append("ep.error_type = ?")
        params.append(error_type)
    if subject_id:
        conditions.append("""ep.concept_id IN (
            SELECT concept_id FROM forge_concept_objectives fco
            JOIN forge_objectives fo ON fo.id = fco.objective_id
            WHERE fo.subject_id = ?)""")
        params.append(subject_id)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    return conn.execute(
        f"""SELECT ep.* FROM forge_error_patterns ep
        {where}
        ORDER BY ep.created_at DESC LIMIT ?""",  # nosec B608
        params,
    ).fetchall()


def get_forge_reviews_for_subject(
    conn: sqlite3.Connection,
    subject_id: str,
    limit: int = 1000,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT fr.* FROM forge_reviews fr
        WHERE fr.subject_id = ?
        ORDER BY fr.reviewed_at DESC LIMIT ?""",
        (subject_id, limit),
    ).fetchall()


# --- Job Board CRUD ---

def insert_job_board(
    conn: sqlite3.Connection,
    board_id: str,
    name: str,
    url: str,
    board_type: str,
    tags: list[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO job_boards (id, name, url, board_type, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (board_id, name, url, board_type, json.dumps(tags), now, now),
    )
    conn.commit()


def get_job_board(conn: sqlite3.Connection, board_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_boards WHERE id = ?", (board_id,)
    ).fetchone()


def list_job_boards(
    conn: sqlite3.Connection, active_only: bool = True
) -> list[sqlite3.Row]:
    if active_only:
        return conn.execute(
            "SELECT * FROM job_boards WHERE active = 1 ORDER BY created_at DESC"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM job_boards ORDER BY created_at DESC"
    ).fetchall()


def update_job_board(conn: sqlite3.Connection, board_id: str, **fields) -> bool:
    if not fields:
        return False
    _validate_fields("job_boards", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [board_id]
    cursor = conn.execute(
        f"UPDATE job_boards SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


# --- News Feed Source CRUD ---


def insert_news_feed_source(
    conn: sqlite3.Connection,
    source_id: str,
    name: str,
    url: str,
    source_type: str,
    tags: list[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO news_feed_sources
        (id, name, url, source_type, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_id, name, url, source_type, json.dumps(tags), now, now),
    )
    conn.commit()


def get_news_feed_source(
    conn: sqlite3.Connection, source_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM news_feed_sources WHERE id = ?", (source_id,)
    ).fetchone()


def list_news_feed_sources(
    conn: sqlite3.Connection, active_only: bool = True
) -> list[sqlite3.Row]:
    if active_only:
        return conn.execute(
            "SELECT * FROM news_feed_sources WHERE active = 1 ORDER BY created_at"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM news_feed_sources ORDER BY created_at"
    ).fetchall()


def update_news_feed_source(
    conn: sqlite3.Connection, source_id: str, **fields
) -> bool:
    if not fields:
        return False
    _validate_fields("news_feed_sources", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [source_id]
    cursor = conn.execute(
        f"UPDATE news_feed_sources SET {set_clause} WHERE id = ?",  # nosec B608
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_news_feed_source(
    conn: sqlite3.Connection, source_id: str
) -> bool:
    """Delete a source and its dedup articles (CASCADE)."""
    cursor = conn.execute(
        "DELETE FROM news_feed_sources WHERE id = ?", (source_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


# --- SignalForge Article CRUD ---

def insert_signalforge_article(
    conn: sqlite3.Connection,
    article_id: str,
    knowledge_id: str,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO signalforge_articles
        (id, knowledge_id, created_at, updated_at)
        VALUES (?, ?, ?, ?)""",
        (article_id, knowledge_id, now, now),
    )
    conn.commit()


def get_signalforge_article(
    conn: sqlite3.Connection, article_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_articles WHERE id = ?", (article_id,)
    ).fetchone()


def get_signalforge_article_by_knowledge_id(
    conn: sqlite3.Connection, knowledge_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_articles WHERE knowledge_id = ?",
        (knowledge_id,),
    ).fetchone()


def list_signalforge_pending(
    conn: sqlite3.Connection, limit: int = 50
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_articles WHERE fetch_status = 'pending' "
        "ORDER BY created_at LIMIT ?",
        (limit,),
    ).fetchall()


def list_signalforge_expired(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    now = now_iso()
    return conn.execute(
        "SELECT * FROM signalforge_articles "
        "WHERE fetch_status = 'fetched' AND expires_at < ?",
        (now,),
    ).fetchall()


def update_signalforge_article(
    conn: sqlite3.Connection, article_id: str, **fields
) -> bool:
    if not fields:
        return False
    _validate_fields("signalforge_articles", fields)
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [article_id]
    cursor = conn.execute(
        f"UPDATE signalforge_articles SET {set_clause} WHERE id = ?",  # nosec B608
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def count_signalforge_by_status(
    conn: sqlite3.Connection,
) -> dict[str, int]:
    rows = conn.execute(
        "SELECT fetch_status, COUNT(*) as cnt FROM signalforge_articles "
        "GROUP BY fetch_status"
    ).fetchall()
    return {row["fetch_status"]: row["cnt"] for row in rows}


# --- SignalForge Cluster CRUD ---

def insert_signalforge_cluster(
    conn: sqlite3.Connection,
    cluster_id: str,
    label: str,
    article_count: int,
    source_count: int,
    avg_similarity: float,
    significance: float,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO signalforge_clusters
        (id, label, article_count, source_count, avg_similarity,
         significance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (cluster_id, label, article_count, source_count,
         avg_similarity, significance, now, now),
    )
    conn.commit()


def get_signalforge_cluster(
    conn: sqlite3.Connection, cluster_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_clusters WHERE id = ?", (cluster_id,)
    ).fetchone()


def list_signalforge_clusters(
    conn: sqlite3.Connection, limit: int = 20, min_significance: float = 0.0
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_clusters "
        "WHERE significance >= ? "
        "ORDER BY significance DESC LIMIT ?",
        (min_significance, limit),
    ).fetchall()


def update_signalforge_cluster(
    conn: sqlite3.Connection, cluster_id: str, **fields
) -> bool:
    if not fields:
        return False
    _validate_fields("signalforge_clusters", fields)
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [cluster_id]
    cursor = conn.execute(
        f"UPDATE signalforge_clusters SET {set_clause} WHERE id = ?",  # nosec B608
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def insert_cluster_article(
    conn: sqlite3.Connection, cluster_id: str, knowledge_id: str
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO signalforge_cluster_articles
        (cluster_id, knowledge_id, added_at)
        VALUES (?, ?, ?)""",
        (cluster_id, knowledge_id, now_iso()),
    )
    conn.commit()


def get_cluster_articles(
    conn: sqlite3.Connection, cluster_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT k.id, k.title, k.source, k.created_at,
                  ca.added_at
           FROM signalforge_cluster_articles ca
           JOIN knowledge k ON k.id = ca.knowledge_id
           WHERE ca.cluster_id = ?
           ORDER BY k.created_at""",
        (cluster_id,),
    ).fetchall()


# --- SignalForge Synthesis CRUD ---


def insert_signalforge_synthesis(
    conn: sqlite3.Connection,
    synthesis_id: str,
    synthesis_date: str,
    title: str,
    content: str,
    cluster_ids: str,
    cluster_count: int,
    article_count: int,
    word_count: int,
    model_used: str,
    input_tokens: int,
    output_tokens: int,
    gdoc_id: str = "",
    gdoc_url: str = "",
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO signalforge_synthesis
        (id, synthesis_date, title, content, cluster_ids, cluster_count,
         article_count, word_count, model_used, input_tokens, output_tokens,
         gdoc_id, gdoc_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (synthesis_id, synthesis_date, title, content, cluster_ids,
         cluster_count, article_count, word_count, model_used,
         input_tokens, output_tokens, gdoc_id, gdoc_url, now, now),
    )
    conn.commit()


def get_signalforge_synthesis(
    conn: sqlite3.Connection, synthesis_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_synthesis WHERE id = ?",
        (synthesis_id,),
    ).fetchone()


def get_signalforge_synthesis_by_date(
    conn: sqlite3.Connection, synthesis_date: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_synthesis WHERE synthesis_date = ?",
        (synthesis_date,),
    ).fetchone()


def list_signalforge_syntheses(
    conn: sqlite3.Connection, limit: int = 10
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signalforge_synthesis ORDER BY synthesis_date DESC LIMIT ?",
        (limit,),
    ).fetchall()


def update_signalforge_synthesis(
    conn: sqlite3.Connection, synthesis_id: str, **fields
) -> bool:
    if not fields:
        return False
    _validate_fields("signalforge_synthesis", fields)
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [synthesis_id]
    cursor = conn.execute(
        f"UPDATE signalforge_synthesis SET {set_clause} WHERE id = ?",  # nosec B608
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


# --- Job Posting CRUD ---

def insert_job_posting(
    conn: sqlite3.Connection,
    job_id: str,
    title: str,
    company: str,
    url: str,
    description: str,
    required_skills: list[str],
    preferred_skills: list[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    job_type: str,
    work_mode: str,
    location: str,
    board_id: Optional[str],
    tags: list[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO job_postings
        (id, title, company, url, description, required_skills, preferred_skills,
         salary_min, salary_max, job_type, work_mode, location, board_id, tags,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, title, company, url, description,
         json.dumps(required_skills), json.dumps(preferred_skills),
         salary_min, salary_max, job_type, work_mode, location,
         board_id, json.dumps(tags), now, now),
    )
    conn.commit()


def get_job_posting(conn: sqlite3.Connection, job_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM job_postings WHERE id = ?", (job_id,)
    ).fetchone()


def search_job_postings_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[tuple[str, float]]:
    rows = conn.execute(
        """SELECT j.id, bm25(job_postings_fts) as score
        FROM job_postings_fts
        JOIN job_postings j ON j.rowid = job_postings_fts.rowid
        WHERE job_postings_fts MATCH ?
        ORDER BY score
        LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [(row["id"], row["score"]) for row in rows]


def list_job_postings(
    conn: sqlite3.Connection,
    company: Optional[str] = None,
    work_mode: Optional[str] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    conditions = []
    params: list = []
    if company:
        conditions.append("company = ?")
        params.append(company)
    if work_mode:
        conditions.append("work_mode = ?")
        params.append(work_mode)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM job_postings {where} ORDER BY created_at DESC LIMIT ?", params  # nosec B608
    ).fetchall()


# --- Application CRUD ---

def insert_application(
    conn: sqlite3.Connection,
    app_id: str,
    job_id: str,
    status: str,
    notes: str,
    tags: list[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO applications (id, job_id, status, notes, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (app_id, job_id, status, notes, json.dumps(tags), now, now),
    )
    conn.commit()


def get_application(conn: sqlite3.Connection, app_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM applications WHERE id = ?", (app_id,)
    ).fetchone()


def update_application(conn: sqlite3.Connection, app_id: str, **fields) -> bool:
    if not fields:
        return False
    _validate_fields("applications", fields)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [app_id]
    cursor = conn.execute(
        f"UPDATE applications SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


def list_applications(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM applications WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM applications ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()


def get_application_pipeline(conn: sqlite3.Connection) -> dict[str, int]:
    """Get counts of applications by status."""
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
    ).fetchall()
    return {row["status"]: row["cnt"] for row in rows}


# --- Interview Prep CRUD ---

def insert_interview_prep(
    conn: sqlite3.Connection,
    prep_id: str,
    application_id: str,
    prep_type: str,
    content: str,
    tags: list[str],
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO interview_prep (id, application_id, prep_type, content, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (prep_id, application_id, prep_type, content, json.dumps(tags), now, now),
    )
    conn.commit()


def get_interview_prep_for_app(
    conn: sqlite3.Connection, application_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM interview_prep WHERE application_id = ? ORDER BY created_at DESC",
        (application_id,),
    ).fetchall()


# --- Memory Archive CRUD ---

def archive_memory(
    conn: sqlite3.Connection,
    memory_id: str,
    archive_reason: str,
    merged_into_id: Optional[str] = None,
    consolidation_run_id: Optional[str] = None,
) -> bool:
    """Move a memory from memories to memory_archive. Returns True if found."""
    row = get_memory(conn, memory_id)
    if row is None:
        return False

    now = now_iso()
    conn.execute(
        """INSERT INTO memory_archive
        (id, content, category, tags, importance, access_count, last_accessed,
         session_id, created_at, updated_at,
         archive_reason, merged_into_id, consolidation_run_id, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row["id"], row["content"], row["category"], row["tags"],
         row["importance"], row["access_count"], row["last_accessed"],
         row["session_id"], row["created_at"], row["updated_at"],
         archive_reason, merged_into_id, consolidation_run_id, now),
    )
    delete_memory(conn, memory_id)
    return True


def get_archived_memories(
    conn: sqlite3.Connection,
    reason: Optional[str] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """List archived memories, optionally filtered by reason."""
    if reason:
        return conn.execute(
            "SELECT * FROM memory_archive WHERE archive_reason = ? ORDER BY archived_at DESC LIMIT ?",
            (reason, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM memory_archive ORDER BY archived_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def get_all_memory_embeddings(
    conn: sqlite3.Connection,
    category: Optional[str] = None,
    max_age_days: Optional[int] = None,
) -> list[tuple[str, bytes]]:
    """Fetch all (id, embedding_bytes) pairs from memories_vec.

    Optionally filter by category and age via joins.
    """
    conditions = []
    params: list = []
    joins = ""

    if category or max_age_days is not None:
        joins = "JOIN memories m ON mv.id = m.id"
        if category:
            conditions.append("m.category = ?")
            params.append(category)
        if max_age_days is not None:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
            conditions.append("m.created_at >= ?")
            params.append(cutoff)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT mv.id, mv.embedding FROM memories_vec mv {joins} {where}",  # nosec B608
        params,
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


# --- Consolidation Log CRUD ---

def insert_consolidation_log(
    conn: sqlite3.Connection,
    log_id: str,
    action: str,
    source_memory_ids: list[str],
    result_memory_id: Optional[str] = None,
    merged_content_preview: str = "",
    reason: str = "",
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO consolidation_log
        (id, action, source_memory_ids, result_memory_id, merged_content_preview, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (log_id, action, json.dumps(source_memory_ids), result_memory_id,
         merged_content_preview, reason, now),
    )
    conn.commit()


def get_consolidation_log(
    conn: sqlite3.Connection,
    action: Optional[str] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    if action:
        return conn.execute(
            "SELECT * FROM consolidation_log WHERE action = ? ORDER BY created_at DESC LIMIT ?",
            (action, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


# --- Graph Entity CRUD ---

def insert_graph_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    name: str,
    entity_type: str,
    description: str = "",
    aliases: Optional[list[str]] = None,
    memory_ids: Optional[list[str]] = None,
    properties: Optional[dict] = None,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO graph_entities
        (id, name, entity_type, description, aliases, memory_ids, properties, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entity_id, name, entity_type, description,
         json.dumps(aliases or []), json.dumps(memory_ids or []),
         json.dumps(properties or {}), now, now),
    )
    conn.commit()


def update_graph_entity(conn: sqlite3.Connection, entity_id: str, **fields) -> bool:
    if not fields:
        return False
    _validate_fields("graph_entities", fields)
    for json_field in ("aliases", "memory_ids", "properties"):
        if json_field in fields:
            fields[json_field] = json.dumps(fields[json_field])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [entity_id]
    cursor = conn.execute(
        f"UPDATE graph_entities SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


def get_graph_entity(conn: sqlite3.Connection, entity_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM graph_entities WHERE id = ?", (entity_id,)
    ).fetchone()


def get_graph_entity_by_name(
    conn: sqlite3.Connection,
    name: str,
    entity_type: Optional[str] = None,
) -> Optional[sqlite3.Row]:
    """Find an entity by name (and optionally type). Case-insensitive."""
    if entity_type:
        return conn.execute(
            "SELECT * FROM graph_entities WHERE LOWER(name) = LOWER(?) AND entity_type = ?",
            (name, entity_type),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM graph_entities WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()


def search_graph_entities(
    conn: sqlite3.Connection,
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    conditions = ["(LOWER(name) LIKE LOWER(?) OR LOWER(aliases) LIKE LOWER(?))"]
    params: list = [f"%{query}%", f"%{query}%"]
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM graph_entities {where} ORDER BY updated_at DESC LIMIT ?",  # nosec B608
        params,
    ).fetchall()


def list_graph_entities(
    conn: sqlite3.Connection,
    entity_type: Optional[str] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    if entity_type:
        return conn.execute(
            "SELECT * FROM graph_entities WHERE entity_type = ? ORDER BY name ASC LIMIT ?",
            (entity_type, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM graph_entities ORDER BY name ASC LIMIT ?",
        (limit,),
    ).fetchall()


def delete_graph_entity(conn: sqlite3.Connection, entity_id: str) -> bool:
    cursor = conn.execute("DELETE FROM graph_entities WHERE id = ?", (entity_id,))
    conn.commit()
    return cursor.rowcount > 0


# --- Graph Relationship CRUD ---

def insert_graph_relationship(
    conn: sqlite3.Connection,
    rel_id: str,
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    weight: float = 1.0,
    evidence_ids: Optional[list[str]] = None,
    properties: Optional[dict] = None,
) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO graph_relationships
        (id, source_entity_id, target_entity_id, rel_type, weight, evidence_ids, properties,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rel_id, source_entity_id, target_entity_id, rel_type, weight,
         json.dumps(evidence_ids or []), json.dumps(properties or {}), now, now),
    )
    conn.commit()


def update_graph_relationship(conn: sqlite3.Connection, rel_id: str, **fields) -> bool:
    if not fields:
        return False
    _validate_fields("graph_relationships", fields)
    for json_field in ("evidence_ids", "properties"):
        if json_field in fields:
            fields[json_field] = json.dumps(fields[json_field])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [rel_id]
    cursor = conn.execute(
        f"UPDATE graph_relationships SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    conn.commit()
    return cursor.rowcount > 0


def get_graph_relationship_by_triple(
    conn: sqlite3.Connection,
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM graph_relationships
        WHERE source_entity_id = ? AND target_entity_id = ? AND rel_type = ?""",
        (source_entity_id, target_entity_id, rel_type),
    ).fetchone()


def get_entity_relationships(
    conn: sqlite3.Connection,
    entity_id: str,
    direction: str = "both",
) -> list[sqlite3.Row]:
    """Get all relationships involving an entity.

    direction: 'outgoing', 'incoming', or 'both'.
    """
    if direction == "outgoing":
        return conn.execute(
            "SELECT * FROM graph_relationships WHERE source_entity_id = ?",
            (entity_id,),
        ).fetchall()
    elif direction == "incoming":
        return conn.execute(
            "SELECT * FROM graph_relationships WHERE target_entity_id = ?",
            (entity_id,),
        ).fetchall()
    return conn.execute(
        """SELECT * FROM graph_relationships
        WHERE source_entity_id = ? OR target_entity_id = ?""",
        (entity_id, entity_id),
    ).fetchall()


# --- Task Queue CRUD ---

def get_queue_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all queued tasks ordered by queue_position.

    Only returns tasks with a queue_position that are not done/cancelled.
    """
    return conn.execute(
        """SELECT * FROM tasks
        WHERE queue_position IS NOT NULL
          AND status NOT IN ('done', 'cancelled')
        ORDER BY queue_position ASC""",
    ).fetchall()


def get_next_queue_task(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the task with the lowest queue_position (not done/cancelled)."""
    return conn.execute(
        """SELECT * FROM tasks
        WHERE queue_position IS NOT NULL
          AND status NOT IN ('done', 'cancelled')
        ORDER BY queue_position ASC
        LIMIT 1""",
    ).fetchone()


def get_max_queue_position(conn: sqlite3.Connection) -> int:
    """Get the current maximum queue_position. Returns 0 if queue is empty."""
    row = conn.execute(
        """SELECT MAX(queue_position) as max_pos FROM tasks
        WHERE queue_position IS NOT NULL
          AND status NOT IN ('done', 'cancelled')"""
    ).fetchone()
    return row["max_pos"] or 0


def set_queue_position(
    conn: sqlite3.Connection, task_id: str, position: int
) -> bool:
    """Set a task's queue_position. Returns True if task was found."""
    cursor = conn.execute(
        "UPDATE tasks SET queue_position = ?, updated_at = ? WHERE id = ?",
        (position, now_iso(), task_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def clear_queue_position(conn: sqlite3.Connection, task_id: str) -> bool:
    """Remove a task from the queue by setting queue_position to NULL."""
    cursor = conn.execute(
        "UPDATE tasks SET queue_position = NULL, updated_at = ? WHERE id = ?",
        (now_iso(), task_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def shift_queue_positions(
    conn: sqlite3.Connection, from_position: int, delta: int = 1
) -> None:
    """Shift all queue positions >= from_position by delta.

    Used to make room when inserting at a specific position.
    """
    conn.execute(
        """UPDATE tasks
        SET queue_position = queue_position + ?,
            updated_at = ?
        WHERE queue_position IS NOT NULL
          AND queue_position >= ?
          AND status NOT IN ('done', 'cancelled')""",
        (delta, now_iso(), from_position),
    )
    conn.commit()


def reindex_queue(conn: sqlite3.Connection) -> None:
    """Reindex queue positions to be sequential (1, 2, 3, ...).

    Eliminates gaps from removed or completed tasks.
    """
    rows = get_queue_tasks(conn)
    for i, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE tasks SET queue_position = ? WHERE id = ?",
            (i, row["id"]),
        )
    conn.commit()


# --- GramCracker (Telegram) CRUD ---

def insert_telegram_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    token_count: int = 0,
    telegram_message_id: Optional[int] = None,
) -> int:
    """Insert a Telegram message. Returns the row ID."""
    now = now_iso()
    cursor = conn.execute(
        """INSERT INTO telegram_messages
        (telegram_message_id, role, content, token_count, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (telegram_message_id, role, content, token_count, now),
    )
    conn.commit()
    return cursor.lastrowid


def get_telegram_history(
    conn: sqlite3.Connection, limit: int = 30
) -> list[sqlite3.Row]:
    """Get recent Telegram messages, oldest first (for Claude context)."""
    rows = conn.execute(
        """SELECT * FROM telegram_messages
        ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return list(reversed(rows))


def get_telegram_message_count(
    conn: sqlite3.Connection, role: Optional[str] = None
) -> int:
    """Count Telegram messages, optionally filtered by role."""
    if role:
        return conn.execute(
            "SELECT COUNT(*) FROM telegram_messages WHERE role = ?",
            (role,),
        ).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM telegram_messages").fetchone()[0]


def upsert_telegram_bot_state(conn: sqlite3.Connection, **fields) -> None:
    """Upsert the single-row bot state. Creates row 1 if missing."""
    conn.execute(
        """INSERT INTO telegram_bot_state (id) VALUES (1)
        ON CONFLICT(id) DO NOTHING"""
    )
    if fields:
        _validate_fields("telegram_bot_state", fields)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values())
        conn.execute(
            f"UPDATE telegram_bot_state SET {set_clause} WHERE id = 1",  # nosec B608
            values,
        )
    conn.commit()


def get_telegram_bot_state(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the current bot state row."""
    return conn.execute(
        "SELECT * FROM telegram_bot_state WHERE id = 1"
    ).fetchone()


def clear_telegram_history(conn: sqlite3.Connection) -> int:
    """Delete all Telegram messages. Returns count deleted."""
    cursor = conn.execute("DELETE FROM telegram_messages")
    conn.commit()
    return cursor.rowcount


# --- Cram CRUD ---


def insert_cram_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    topic: str,
    description: str = "",
    source_question: str = "",
    source_answer: str = "",
    forge_concept_id: Optional[str] = None,
    commit: bool = True,
) -> None:
    """Insert a cram topic."""
    now = now_iso()
    conn.execute(
        """INSERT INTO cram_topics
        (id, topic, description, source_question, source_answer,
         forge_concept_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (topic_id, topic, description, source_question, source_answer,
         forge_concept_id, now, now),
    )
    if commit:
        conn.commit()


def get_cram_topic(conn: sqlite3.Connection, topic_id: str) -> Optional[sqlite3.Row]:
    """Get a single cram topic by ID."""
    return conn.execute(
        "SELECT * FROM cram_topics WHERE id = ?", (topic_id,)
    ).fetchone()


def list_cram_topics(
    conn: sqlite3.Connection,
    sort_by: str = "understanding",
) -> list[sqlite3.Row]:
    """List all cram topics sorted by given field."""
    valid_sorts = {
        "understanding": "understanding ASC",
        "recent": "updated_at DESC",
        "topic": "topic ASC",
        "reviews": "review_count DESC",
    }
    order = valid_sorts.get(sort_by, "understanding ASC")
    return conn.execute(
        f"SELECT * FROM cram_topics ORDER BY {order}"  # nosec B608
    ).fetchall()


def update_cram_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    commit: bool = True,
    **fields,
) -> bool:
    """Update cram topic fields. Returns True if found."""
    if not fields:
        return False
    _validate_fields("cram_topics", fields)
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [topic_id]
    cursor = conn.execute(
        f"UPDATE cram_topics SET {set_clause} WHERE id = ?", values  # nosec B608
    )
    if commit:
        conn.commit()
    return cursor.rowcount > 0


def delete_cram_topic(conn: sqlite3.Connection, topic_id: str) -> bool:
    """Delete a cram topic and its reviews (cascade). Returns True if found."""
    cursor = conn.execute("DELETE FROM cram_topics WHERE id = ?", (topic_id,))
    conn.commit()
    return cursor.rowcount > 0


def insert_cram_review(
    conn: sqlite3.Connection,
    topic_id: str,
    was_correct: bool,
    confidence: int = 3,
    notes: str = "",
    commit: bool = True,
) -> None:
    """Insert a cram review record."""
    conn.execute(
        """INSERT INTO cram_reviews (topic_id, was_correct, confidence, notes, reviewed_at)
        VALUES (?, ?, ?, ?, ?)""",
        (topic_id, 1 if was_correct else 0, confidence, notes, now_iso()),
    )
    if commit:
        conn.commit()


def get_cram_reviews(
    conn: sqlite3.Connection,
    topic_id: str,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Get recent reviews for a cram topic."""
    return conn.execute(
        """SELECT * FROM cram_reviews
        WHERE topic_id = ?
        ORDER BY reviewed_at DESC LIMIT ?""",
        (topic_id, limit),
    ).fetchall()


def get_cram_stats(conn: sqlite3.Connection) -> dict:
    """Get aggregate cram statistics."""
    topics = conn.execute(
        "SELECT COUNT(*) as total, AVG(understanding) as avg_understanding FROM cram_topics"
    ).fetchone()
    reviews = conn.execute(
        "SELECT COUNT(*) as total FROM cram_reviews"
    ).fetchone()
    correct = conn.execute(
        "SELECT COUNT(*) as total FROM cram_reviews WHERE was_correct = 1"
    ).fetchone()
    weak = conn.execute(
        """SELECT COUNT(*) as total FROM cram_topics
        WHERE understanding < 0.4"""
    ).fetchone()
    strong = conn.execute(
        """SELECT COUNT(*) as total FROM cram_topics
        WHERE understanding >= 0.8"""
    ).fetchone()
    return {
        "total_topics": topics["total"],
        "avg_understanding": round(topics["avg_understanding"] or 0.0, 3),
        "total_reviews": reviews["total"],
        "correct_reviews": correct["total"],
        "accuracy": round(correct["total"] / reviews["total"], 3) if reviews["total"] > 0 else 0.0,
        "weak_topics": weak["total"],
        "strong_topics": strong["total"],
    }
