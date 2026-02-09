"""Pydantic data models for JayBrain."""

from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Enums ---

class MemoryCategory(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    DECISION = "decision"
    PREFERENCE = "preference"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- Memory Models ---

class MemoryCreate(BaseModel):
    content: str = Field(..., description="The memory content to store")
    category: MemoryCategory = Field(
        default=MemoryCategory.SEMANTIC,
        description="Memory type: episodic, semantic, procedural, decision, or preference",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Importance score from 0.0 to 1.0",
    )


class Memory(BaseModel):
    id: str
    content: str
    category: MemoryCategory
    tags: list[str]
    importance: float
    created_at: datetime
    updated_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None


class MemorySearchResult(BaseModel):
    memory: Memory
    score: float = Field(description="Combined relevance score")
    vector_score: float = Field(default=0.0, description="Vector similarity score")
    keyword_score: float = Field(default=0.0, description="BM25 keyword score")


# --- Task Models ---

class TaskCreate(BaseModel):
    title: str = Field(..., description="Task title")
    description: str = Field(default="", description="Task description")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM)
    project: str = Field(default="", description="Project this task belongs to")
    tags: list[str] = Field(default_factory=list)
    due_date: Optional[date] = Field(default=None, description="Due date (YYYY-MM-DD)")


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    project: Optional[str] = None
    tags: Optional[list[str]] = None
    due_date: Optional[date] = None


class Task(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    project: str
    tags: list[str]
    due_date: Optional[date]
    created_at: datetime
    updated_at: datetime


# --- Session Models ---

class SessionStart(BaseModel):
    title: str = Field(default="", description="Optional session title")


class SessionEnd(BaseModel):
    summary: str = Field(..., description="Summary of what was accomplished")
    decisions_made: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class Session(BaseModel):
    id: str
    title: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    summary: str = ""
    decisions_made: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# --- Knowledge Models ---

class KnowledgeCreate(BaseModel):
    title: str = Field(..., description="Knowledge entry title")
    content: str = Field(..., description="The knowledge content")
    category: str = Field(default="general", description="Knowledge category")
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="", description="Where this knowledge came from")


class KnowledgeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class Knowledge(BaseModel):
    id: str
    title: str
    content: str
    category: str
    tags: list[str]
    source: str
    created_at: datetime
    updated_at: datetime


class KnowledgeSearchResult(BaseModel):
    knowledge: Knowledge
    score: float


# --- Profile Models ---

class UserProfile(BaseModel):
    name: str = "Joshua"
    nickname: str = "JJ"
    preferences: dict[str, str] = Field(default_factory=dict)
    projects: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)


# --- System Models ---

class SystemStats(BaseModel):
    memory_count: int
    task_count: int
    active_tasks: int
    session_count: int
    knowledge_count: int
    db_size_mb: float
    memories_by_category: dict[str, int]
