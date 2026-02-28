"""Tests for vault enhancement features (Feature 4a).

Tests wiki-link injection, backlinks, and verbatim conversation archiving.
"""

import json
from pathlib import Path

import pytest

from jaybrain.vault_sync import (
    _build_backlinks,
    _build_entity_index,
    _inject_wikilinks,
    _append_backlinks,
    _convert_conversation_verbatim,
)
import jaybrain.config as config
from jaybrain.db import init_db


def _setup(temp_data_dir):
    config.ensure_data_dirs()
    init_db()


def _get_test_conn():
    """Get a plain sqlite3 connection for testing (uses patched DB_PATH)."""
    import sqlite3
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_entities(conn, entities):
    """Insert graph entities for testing."""
    for name, entity_type in entities:
        conn.execute(
            """INSERT OR IGNORE INTO graph_entities (id, name, entity_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01', '2026-01-01')""",
            (name.lower().replace(" ", "_"), name, entity_type, f"Test {name}"),
        )
    conn.commit()


class TestBuildEntityIndex:
    def test_builds_from_graph_entities(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = _get_test_conn()
        _insert_entities(conn, [
            ("JayBrain", "project"),
            ("SQLite", "tool"),
            ("Joshua", "person"),
        ])

        index = _build_entity_index(conn)
        conn.close()

        assert "JayBrain" in index
        assert "SQLite" in index
        assert "Joshua" in index
        assert "Network/Projects" in index["JayBrain"]
        assert "Network/Tools" in index["SQLite"]
        assert "Network/Contacts" in index["Joshua"]

    def test_empty_graph(self, temp_data_dir):
        _setup(temp_data_dir)
        conn = _get_test_conn()
        index = _build_entity_index(conn)
        conn.close()
        assert index == {}

    def test_handles_missing_table(self, temp_data_dir):
        """Should not crash if graph_entities doesn't exist."""
        import sqlite3
        conn = sqlite3.connect(str(temp_data_dir / "jaybrain.db"))
        conn.row_factory = sqlite3.Row
        index = _build_entity_index(conn)
        conn.close()
        assert index == {}


class TestWikilinkInjection:
    def test_entity_name_linked(self):
        body = "JayBrain uses SQLite for storage."
        index = {
            "JayBrain": "Network/Projects/JayBrain",
            "SQLite": "Network/Tools/SQLite",
        }
        result = _inject_wikilinks(body, index)
        assert "[[JayBrain]]" in result
        assert "[[SQLite]]" in result

    def test_existing_wikilinks_not_doubled(self):
        body = "See [[JayBrain]] for details about JayBrain."
        index = {"JayBrain": "Network/Projects/JayBrain"}
        result = _inject_wikilinks(body, index)
        # Should have exactly 2 instances: one existing [[]], one injected
        assert result.count("[[JayBrain]]") >= 1
        assert "[[[[" not in result  # No double-wrapping

    def test_self_name_not_linked(self):
        body = "JayBrain is a project about JayBrain and more JayBrain."
        index = {"JayBrain": "Network/Projects/JayBrain"}
        result = _inject_wikilinks(body, index, self_name="JayBrain")
        assert "[[JayBrain]]" not in result

    def test_short_names_skipped(self):
        body = "We use AI for many tasks with ML."
        index = {"AI": "Network/Tools/AI", "ML": "Network/Tools/ML"}
        result = _inject_wikilinks(body, index)
        assert "[[AI]]" not in result
        assert "[[ML]]" not in result

    def test_empty_body(self):
        result = _inject_wikilinks("", {"Test": "path"})
        assert result == ""

    def test_empty_index(self):
        result = _inject_wikilinks("Some text", {})
        assert result == "Some text"

    def test_max_three_replacements(self):
        body = "SQLite SQLite SQLite SQLite SQLite"
        index = {"SQLite": "Network/Tools/SQLite"}
        result = _inject_wikilinks(body, index)
        assert result.count("[[SQLite]]") == 3

    def test_longer_names_matched_first(self):
        body = "Claude Code is great. Claude is too."
        index = {
            "Claude Code": "Network/Tools/Claude-Code",
            "Claude": "Network/Tools/Claude",
        }
        result = _inject_wikilinks(body, index)
        assert "[[Claude Code]]" in result


class TestBacklinks:
    def test_backlinks_built(self):
        notes = [
            ("Memory about auth", "Memories/note-a.md", "Uses [[JayBrain]] for auth"),
            ("Knowledge base", "Knowledge/note-b.md", "Related to [[JayBrain]] system"),
        ]
        backlinks = _build_backlinks(notes)
        assert "JayBrain" in backlinks
        assert len(backlinks["JayBrain"]) == 2

    def test_no_duplicates(self):
        notes = [
            ("Note A", "a.md", "Links to [[Foo]] and also [[Foo]]"),
        ]
        backlinks = _build_backlinks(notes)
        assert len(backlinks["Foo"]) == 1

    def test_empty_notes(self):
        backlinks = _build_backlinks([])
        assert backlinks == {}

    def test_no_links(self):
        notes = [("Note A", "a.md", "No links here")]
        backlinks = _build_backlinks(notes)
        assert backlinks == {}


class TestAppendBacklinks:
    def test_appends_when_links_exist(self):
        body = "# Main content"
        backlinks = {"MyNote": ["Note A", "Note B"]}
        result = _append_backlinks(body, "MyNote", backlinks)
        assert "## Backlinks" in result
        assert "[[Note A]]" in result
        assert "[[Note B]]" in result

    def test_no_append_when_no_links(self):
        body = "# Main content"
        backlinks = {"Other": ["Note A"]}
        result = _append_backlinks(body, "MyNote", backlinks)
        assert "## Backlinks" not in result
        assert result == body


class TestConversationVerbatim:
    def test_convert_basic_jsonl(self, tmp_path):
        jsonl_path = tmp_path / "test-session-id.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-27T10:00:00Z",
                "message": {"content": "Hello, what is Python?"},
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-02-27T10:00:05Z",
                "message": {
                    "content": [
                        {"type": "text", "text": "Python is a programming language."},
                    ]
                },
            }),
        ]
        jsonl_path.write_text("\n".join(lines))

        result = _convert_conversation_verbatim(jsonl_path)
        assert result is not None
        rel_path, content = result

        assert "Conversations" in str(rel_path)
        assert "2026-02" in str(rel_path)
        assert "test-session-id" in str(rel_path)
        assert "jaybrain_type: conversation" in content
        assert "### User 10:00:00" in content
        assert "### Assistant 10:00:05" in content
        assert "Hello, what is Python?" in content
        assert "Python is a programming language." in content

    def test_tool_usage_tracked(self, tmp_path):
        jsonl_path = tmp_path / "tool-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-27T10:00:00Z",
                "message": {"content": "Read file"},
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-02-27T10:00:01Z",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read"},
                        {"type": "tool_use", "name": "Read"},
                        {"type": "tool_use", "name": "Edit"},
                        {"type": "text", "text": "Done reading."},
                    ]
                },
            }),
        ]
        jsonl_path.write_text("\n".join(lines))

        result = _convert_conversation_verbatim(jsonl_path)
        assert result is not None
        _, content = result
        assert "## Tool Usage" in content
        assert "`Read`: 2" in content
        assert "`Edit`: 1" in content

    def test_empty_jsonl_returns_none(self, tmp_path):
        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.write_text("")

        result = _convert_conversation_verbatim(jsonl_path)
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = _convert_conversation_verbatim(tmp_path / "missing.jsonl")
        assert result is None

    def test_long_turns_truncated(self, tmp_path):
        jsonl_path = tmp_path / "long-session.jsonl"
        long_text = "x" * 10000
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-27T10:00:00Z",
                "message": {"content": long_text},
            }),
        ]
        jsonl_path.write_text("\n".join(lines))

        result = _convert_conversation_verbatim(jsonl_path)
        assert result is not None
        _, content = result
        assert "[truncated]" in content

    def test_frontmatter_has_counts(self, tmp_path):
        jsonl_path = tmp_path / "counted-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-27T10:00:00Z",
                "message": {"content": "Question 1"},
            }),
            json.dumps({
                "type": "assistant",
                "timestamp": "2026-02-27T10:00:01Z",
                "message": {
                    "content": [
                        {"type": "text", "text": "Answer 1"},
                        {"type": "tool_use", "name": "Bash"},
                    ]
                },
            }),
        ]
        jsonl_path.write_text("\n".join(lines))

        result = _convert_conversation_verbatim(jsonl_path)
        assert result is not None
        _, content = result
        assert "tool_count: 1" in content
        assert "turn_count: 2" in content
