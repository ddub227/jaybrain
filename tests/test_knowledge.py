"""Tests for the knowledge module (store, search, update)."""

import pytest
from unittest.mock import patch

from jaybrain.db import init_db, get_connection, insert_knowledge
from jaybrain.config import ensure_data_dirs
from jaybrain.db import fts5_safe_query
from jaybrain.knowledge import (
    store_knowledge,
    search_knowledge_entries,
    modify_knowledge,
)


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


# Mock embedding to avoid loading the ONNX model during tests
FAKE_EMBEDDING = [0.1] * 384


@pytest.fixture(autouse=True)
def mock_embed():
    with patch("jaybrain.knowledge.embed_text", return_value=FAKE_EMBEDDING):
        yield


class TestFts5SafeQuery:
    def test_simple_query(self):
        assert fts5_safe_query("hello world") == '"hello" "world"'

    def test_special_characters_stripped(self):
        result = fts5_safe_query("python3.12 c++ node.js")
        assert '"python312"' in result
        assert '"c"' in result
        assert '"nodejs"' in result

    def test_empty_query(self):
        assert fts5_safe_query("") == ""

    def test_only_special_chars(self):
        assert fts5_safe_query("!@#$%") == ""


class TestStoreKnowledge:
    def test_store_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("Python GIL", "The GIL limits threading in CPython")
        assert k.title == "Python GIL"
        assert k.content == "The GIL limits threading in CPython"
        assert k.category == "general"
        assert k.tags == []
        assert len(k.id) == 12

    def test_store_with_all_fields(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge(
            title="Docker Networking",
            content="Bridge, host, overlay modes",
            category="devops",
            tags=["docker", "networking"],
            source="Docker docs",
        )
        assert k.category == "devops"
        assert k.tags == ["docker", "networking"]
        assert k.source == "Docker docs"

    def test_store_persists_to_db(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("Persistent", "Should be in DB")

        conn = get_connection()
        from jaybrain.db import get_knowledge
        row = get_knowledge(conn, k.id)
        assert row is not None
        assert row["title"] == "Persistent"
        conn.close()


class TestSearchKnowledge:
    def test_search_empty_db(self, temp_data_dir):
        _setup_db(temp_data_dir)
        results = search_knowledge_entries("anything")
        assert results == []

    def test_search_by_keyword(self, temp_data_dir):
        _setup_db(temp_data_dir)
        store_knowledge("Python threading", "GIL prevents true parallelism")
        store_knowledge("JavaScript async", "Event loop based concurrency")

        results = search_knowledge_entries("Python")
        # FTS should find the Python entry
        assert len(results) >= 1
        titles = [r.knowledge.title for r in results]
        assert "Python threading" in titles

    def test_search_with_category_filter(self, temp_data_dir):
        _setup_db(temp_data_dir)
        store_knowledge("Python types", "Static typing with mypy", category="python")
        store_knowledge("Python web", "Flask and Django", category="web")

        results = search_knowledge_entries("Python", category="python")
        for r in results:
            assert r.knowledge.category == "python"

    def test_search_limit(self, temp_data_dir):
        _setup_db(temp_data_dir)
        for i in range(5):
            store_knowledge(f"Topic {i}", f"Content about topic {i}")

        results = search_knowledge_entries("topic", limit=2)
        assert len(results) <= 2


class TestModifyKnowledge:
    def test_modify_title(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("Original", "Content")
        updated = modify_knowledge(k.id, title="Updated Title")
        assert updated is not None
        assert updated.title == "Updated Title"

    def test_modify_content(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("Title", "Old content")
        updated = modify_knowledge(k.id, content="New content")
        assert updated.content == "New content"

    def test_modify_tags(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("Tagged", "Content")
        updated = modify_knowledge(k.id, tags=["new", "tags"])
        assert updated.tags == ["new", "tags"]

    def test_modify_nonexistent(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = modify_knowledge("nonexistent", title="Nope")
        assert result is None

    def test_modify_category(self, temp_data_dir):
        _setup_db(temp_data_dir)
        k = store_knowledge("General", "Content", category="general")
        updated = modify_knowledge(k.id, category="python")
        assert updated.category == "python"
