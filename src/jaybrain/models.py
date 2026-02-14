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
    session_id: Optional[str] = None


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


# --- SynapseForge Models ---

class ConceptDifficulty(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ConceptCategory(str, Enum):
    PYTHON = "python"
    NETWORKING = "networking"
    MCP = "mcp"
    DATABASES = "databases"
    SECURITY = "security"
    LINUX = "linux"
    GIT = "git"
    AI_ML = "ai_ml"
    WEB = "web"
    DEVOPS = "devops"
    GENERAL = "general"


class ReviewOutcome(str, Enum):
    REVIEWED = "reviewed"
    UNDERSTOOD = "understood"
    STRUGGLED = "struggled"
    SKIPPED = "skipped"


class Concept(BaseModel):
    id: str
    term: str
    definition: str
    category: ConceptCategory
    difficulty: ConceptDifficulty
    tags: list[str] = Field(default_factory=list)
    related_jaybrain_component: str = ""
    source: str = ""
    notes: str = ""
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)
    review_count: int = 0
    correct_count: int = 0
    last_reviewed: Optional[datetime] = None
    next_review: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())

    @property
    def mastery_name(self) -> str:
        """Return forge-themed mastery level name."""
        if self.mastery_level >= 0.95:
            return "Forged"
        elif self.mastery_level >= 0.80:
            return "Inferno"
        elif self.mastery_level >= 0.60:
            return "Blaze"
        elif self.mastery_level >= 0.40:
            return "Flame"
        elif self.mastery_level >= 0.20:
            return "Ember"
        else:
            return "Spark"


class Review(BaseModel):
    id: int
    concept_id: str
    outcome: ReviewOutcome
    confidence: int = Field(ge=1, le=5)
    time_spent_seconds: int = 0
    notes: str = ""
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now())


class ForgeStats(BaseModel):
    total_concepts: int = 0
    total_reviews: int = 0
    concepts_by_category: dict[str, int] = Field(default_factory=dict)
    concepts_by_difficulty: dict[str, int] = Field(default_factory=dict)
    concepts_by_mastery: dict[str, int] = Field(default_factory=dict)
    due_count: int = 0
    avg_mastery: float = 0.0
    current_streak: int = 0
    longest_streak: int = 0


# --- Job Hunt Enums ---

class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    PREPARING = "preparing"
    READY = "ready"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFERED = "offered"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class JobType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class InterviewPrepType(str, Enum):
    GENERAL = "general"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    COMPANY_RESEARCH = "company_research"


# --- Job Board Models ---

class JobBoardCreate(BaseModel):
    name: str = Field(..., description="Job board name")
    url: str = Field(..., description="URL to monitor")
    board_type: str = Field(default="general", description="Board type (general, niche, company)")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")


class JobBoard(BaseModel):
    id: str
    name: str
    url: str
    board_type: str
    tags: list[str]
    active: bool = True
    last_checked: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# --- Job Posting Models ---

class JobPostingCreate(BaseModel):
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    url: str = Field(default="", description="Job posting URL")
    description: str = Field(default="", description="Full job description")
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    job_type: JobType = Field(default=JobType.FULL_TIME)
    work_mode: WorkMode = Field(default=WorkMode.REMOTE)
    location: str = Field(default="")
    board_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class JobPosting(BaseModel):
    id: str
    title: str
    company: str
    url: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    job_type: JobType
    work_mode: WorkMode
    location: str
    board_id: Optional[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


# --- Application Models ---

class ApplicationCreate(BaseModel):
    job_id: str = Field(..., description="ID of the job posting")
    status: ApplicationStatus = Field(default=ApplicationStatus.DISCOVERED)
    notes: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    applied_date: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


class Application(BaseModel):
    id: str
    job_id: str
    status: ApplicationStatus
    resume_path: str = ""
    cover_letter_path: str = ""
    applied_date: Optional[str] = None
    notes: str = ""
    tags: list[str]
    created_at: datetime
    updated_at: datetime


# --- Interview Prep Models ---

class InterviewPrepCreate(BaseModel):
    application_id: str = Field(..., description="Application ID")
    prep_type: InterviewPrepType = Field(default=InterviewPrepType.GENERAL)
    content: str = Field(..., description="Prep content")
    tags: list[str] = Field(default_factory=list)


class InterviewPrep(BaseModel):
    id: str
    application_id: str
    prep_type: InterviewPrepType
    content: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
