"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from jaybrain.models import (
    MemoryCreate,
    MemoryCategory,
    TaskCreate,
    TaskStatus,
    TaskPriority,
    SessionEnd,
    KnowledgeCreate,
    UserProfile,
    SystemStats,
)


class TestMemoryCreate:
    def test_defaults(self):
        m = MemoryCreate(content="test fact")
        assert m.content == "test fact"
        assert m.category == MemoryCategory.SEMANTIC
        assert m.tags == []
        assert m.importance == 0.5

    def test_all_fields(self):
        m = MemoryCreate(
            content="JJ prefers Python",
            category=MemoryCategory.PREFERENCE,
            tags=["python", "preference"],
            importance=0.9,
        )
        assert m.category == MemoryCategory.PREFERENCE
        assert m.importance == 0.9
        assert "python" in m.tags

    def test_importance_bounds(self):
        with pytest.raises(ValidationError):
            MemoryCreate(content="test", importance=1.5)
        with pytest.raises(ValidationError):
            MemoryCreate(content="test", importance=-0.1)

    def test_empty_content_fails(self):
        with pytest.raises(ValidationError):
            MemoryCreate()


class TestTaskCreate:
    def test_defaults(self):
        t = TaskCreate(title="Fix bug")
        assert t.title == "Fix bug"
        assert t.priority == TaskPriority.MEDIUM
        assert t.project == ""
        assert t.tags == []
        assert t.due_date is None

    def test_all_fields(self):
        from datetime import date
        t = TaskCreate(
            title="Deploy",
            description="Deploy to prod",
            priority=TaskPriority.CRITICAL,
            project="jaybrain",
            tags=["deploy"],
            due_date=date(2026, 3, 1),
        )
        assert t.priority == TaskPriority.CRITICAL
        assert t.due_date == date(2026, 3, 1)


class TestSessionEnd:
    def test_minimal(self):
        s = SessionEnd(summary="Did stuff")
        assert s.summary == "Did stuff"
        assert s.decisions_made == []
        assert s.next_steps == []

    def test_full(self):
        s = SessionEnd(
            summary="Built memory system",
            decisions_made=["Use ONNX"],
            next_steps=["Add tests"],
        )
        assert len(s.decisions_made) == 1


class TestKnowledgeCreate:
    def test_defaults(self):
        k = KnowledgeCreate(title="SQLite Tips", content="Use WAL mode")
        assert k.category == "general"
        assert k.source == ""


class TestUserProfile:
    def test_defaults(self):
        p = UserProfile()
        assert p.name == "Joshua"
        assert p.nickname == "JJ"


class TestSystemStats:
    def test_all_fields(self):
        s = SystemStats(
            memory_count=10,
            task_count=5,
            active_tasks=3,
            session_count=2,
            knowledge_count=7,
            db_size_mb=0.5,
            memories_by_category={"semantic": 5, "decision": 5},
        )
        assert s.memory_count == 10
        assert s.memories_by_category["semantic"] == 5
