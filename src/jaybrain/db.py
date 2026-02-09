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
