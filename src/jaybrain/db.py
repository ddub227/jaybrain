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


def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a list of floats into bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def _deserialize_f32(data: bytes) -> list[float]:
    """Deserialize bytes back into a list of floats."""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def get_connection() -> sqlite3.Connection:
    """Get a database connection with sqlite-vec loaded."""
    ensure_data_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


SCHEMA_SQL = f"""
-- Memories table
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'semantic',
    tags TEXT NOT NULL DEFAULT '[]',
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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
    embedding float[{EMBEDDING_DIM}]
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
    embedding float[{EMBEDDING_DIM}]
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forge_concepts_category ON forge_concepts(category);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_mastery ON forge_concepts(mastery_level);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_next_review ON forge_concepts(next_review);
CREATE INDEX IF NOT EXISTS idx_forge_concepts_difficulty ON forge_concepts(difficulty);

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
    embedding float[{EMBEDDING_DIM}]
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
"""


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
) -> None:
    """Insert a memory into all tables (memories, FTS, vec) atomically."""
    now = now_iso()
    tags_json = json.dumps(tags)
    conn.execute(
        """INSERT INTO memories (id, content, category, tags, importance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, content, category, tags_json, importance, now, now),
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
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    cursor = conn.execute(
        f"UPDATE tasks SET {set_clause} WHERE id = ?", values
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
        f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?", params
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
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [knowledge_id]
    cursor = conn.execute(
        f"UPDATE knowledge SET {set_clause} WHERE id = ?", values
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


def update_forge_concept(conn: sqlite3.Connection, concept_id: str, **fields) -> bool:
    """Update concept fields. Returns True if found."""
    if not fields:
        return False
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [concept_id]
    cursor = conn.execute(
        f"UPDATE forge_concepts SET {set_clause} WHERE id = ?", values
    )
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
) -> int:
    """Insert a review record. Returns the review ID."""
    now = now_iso()
    cursor = conn.execute(
        """INSERT INTO forge_reviews
        (concept_id, outcome, confidence, time_spent_seconds, notes, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (concept_id, outcome, confidence, time_spent_seconds, notes, now),
    )
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
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [board_id]
    cursor = conn.execute(
        f"UPDATE job_boards SET {set_clause} WHERE id = ?", values
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
        f"SELECT * FROM job_postings {where} ORDER BY created_at DESC LIMIT ?", params
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
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [app_id]
    cursor = conn.execute(
        f"UPDATE applications SET {set_clause} WHERE id = ?", values
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
