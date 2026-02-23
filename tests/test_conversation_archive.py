"""Tests for the conversation archive module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection


class TestParseConversation:
    def test_parse_basic_conversation(self, temp_data_dir, tmp_path):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import parse_conversation

        jsonl = tmp_path / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "message": {"content": "Hello, how are you?"},
                "timestamp": "2026-02-20T10:00:00Z",
            }),
            json.dumps({
                "type": "assistant",
                "requestId": "req1",
                "message": {"content": [{"type": "text", "text": "I'm doing well!"}]},
                "timestamp": "2026-02-20T10:00:05Z",
            }),
        ]
        jsonl.write_text("\n".join(lines))

        result = parse_conversation(jsonl)
        assert result["session_id"] == "test-session"
        assert len(result["turns"]) == 2
        assert result["turns"][0]["role"] == "user"
        assert result["turns"][0]["text"] == "Hello, how are you?"
        assert result["turns"][1]["role"] == "assistant"
        assert result["turns"][1]["text"] == "I'm doing well!"

    def test_parse_with_tool_calls(self, temp_data_dir, tmp_path):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import parse_conversation

        jsonl = tmp_path / "tool-session.jsonl"
        lines = [
            json.dumps({
                "type": "assistant",
                "requestId": "req1",
                "message": {"content": [
                    {"type": "tool_use", "name": "remember"},
                    {"type": "text", "text": "Stored your memory."},
                ]},
                "timestamp": "2026-02-20T10:00:00Z",
            }),
        ]
        jsonl.write_text("\n".join(lines))

        result = parse_conversation(jsonl)
        assert "remember" in result["tool_calls"]

    def test_parse_empty_file(self, temp_data_dir, tmp_path):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import parse_conversation

        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")

        result = parse_conversation(jsonl)
        assert result["turns"] == []

    def test_parse_invalid_json(self, temp_data_dir, tmp_path):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import parse_conversation

        jsonl = tmp_path / "bad.jsonl"
        jsonl.write_text("not json\n{also bad\n")

        result = parse_conversation(jsonl)
        assert result["turns"] == []

    def test_parse_user_content_list(self, temp_data_dir, tmp_path):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import parse_conversation

        jsonl = tmp_path / "list-content.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "message": {"content": [
                    {"type": "text", "text": "Part one"},
                    {"type": "text", "text": "Part two"},
                ]},
                "timestamp": "2026-02-20T10:00:00Z",
            }),
        ]
        jsonl.write_text("\n".join(lines))

        result = parse_conversation(jsonl)
        assert "Part one" in result["turns"][0]["text"]
        assert "Part two" in result["turns"][0]["text"]


class TestDiscoverConversations:
    def test_discover_finds_jsonl_files(self, temp_data_dir, tmp_path, monkeypatch):
        ensure_data_dirs()
        init_db()

        import jaybrain.conversation_archive as ca
        projects_dir = tmp_path / "claude_projects"
        project = projects_dir / "test-project"
        project.mkdir(parents=True)
        (project / "session1.jsonl").write_text("{}")
        (project / "session2.jsonl").write_text("{}")

        monkeypatch.setattr(ca, "CLAUDE_PROJECTS_DIR", projects_dir)

        result = ca.discover_conversations(max_age_days=30)
        assert len(result) == 2

    def test_discover_filters_old_files(self, temp_data_dir, tmp_path, monkeypatch):
        ensure_data_dirs()
        init_db()

        import jaybrain.conversation_archive as ca
        projects_dir = tmp_path / "claude_projects"
        project = projects_dir / "test-project"
        project.mkdir(parents=True)
        old_file = project / "old-session.jsonl"
        old_file.write_text("{}")
        # Set mtime to 30 days ago
        import time
        old_time = time.time() - (31 * 86400)
        os.utime(old_file, (old_time, old_time))

        monkeypatch.setattr(ca, "CLAUDE_PROJECTS_DIR", projects_dir)

        result = ca.discover_conversations(max_age_days=7)
        assert len(result) == 0

    def test_discover_nonexistent_dir(self, temp_data_dir, tmp_path, monkeypatch):
        ensure_data_dirs()
        init_db()

        import jaybrain.conversation_archive as ca
        monkeypatch.setattr(ca, "CLAUDE_PROJECTS_DIR", tmp_path / "nonexistent")

        result = ca.discover_conversations()
        assert result == []


class TestSummarizeConversation:
    def test_summarize_empty_conversation(self, temp_data_dir):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import summarize_conversation

        result = summarize_conversation({"turns": [], "tool_calls": []})
        assert result == "(empty conversation)"

    def test_summarize_fallback_on_claude_failure(self, temp_data_dir):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import summarize_conversation

        with patch("subprocess.run", side_effect=FileNotFoundError("claude not found")):
            result = summarize_conversation({
                "turns": [{"role": "user", "text": "Hello"}],
                "tool_calls": ["remember", "recall"],
            })
        assert "2 tool calls" in result
        assert "remember" in result


class TestRunArchive:
    def test_run_archive_no_conversations(self, temp_data_dir, tmp_path, monkeypatch):
        ensure_data_dirs()
        init_db()

        import jaybrain.conversation_archive as ca
        monkeypatch.setattr(ca, "CLAUDE_PROJECTS_DIR", tmp_path / "empty_projects")

        result = ca.run_archive()
        assert result["conversations_found"] == 0
        assert result["conversations_archived"] == 0

    def test_run_archive_idempotent(self, temp_data_dir, tmp_path, monkeypatch):
        ensure_data_dirs()
        init_db()

        import jaybrain.conversation_archive as ca
        projects_dir = tmp_path / "projects"
        project = projects_dir / "test"
        project.mkdir(parents=True)

        jsonl = project / "session-abc.jsonl"
        jsonl.write_text(json.dumps({
            "type": "user",
            "message": {"content": "Hello"},
            "timestamp": "2026-02-20T10:00:00Z",
        }))

        monkeypatch.setattr(ca, "CLAUDE_PROJECTS_DIR", projects_dir)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result1 = ca.run_archive()
            result2 = ca.run_archive()

        assert result1["conversations_archived"] == 1
        assert result2["conversations_archived"] == 0  # Already archived


class TestArchiveStatus:
    def test_status_empty(self, temp_data_dir):
        ensure_data_dirs()
        init_db()

        from jaybrain.conversation_archive import get_archive_status

        result = get_archive_status()
        assert result["total_archived_sessions"] == 0
        assert result["recent_runs"] == []


class TestMigration8:
    def test_archive_tables_exist(self, temp_data_dir):
        ensure_data_dirs()
        init_db()

        conn = get_connection()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "conversation_archive_runs" in tables
            assert "conversation_archive_sessions" in tables
        finally:
            conn.close()
