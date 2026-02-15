"""Tests for Pulse X-Ray (cross-session transcript reader)."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from jaybrain.pulse import (
    _extract_user_text,
    _extract_assistant_text,
    _parse_transcript,
    _find_jsonl,
    get_session_context,
    _CLAUDE_PROJECTS_DIR,
)


# -- Helpers --

def _make_user_line(text, timestamp="2026-02-14T10:00:00Z"):
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": timestamp,
    })


def _make_assistant_line(text, req_id="req_001", timestamp="2026-02-14T10:00:01Z"):
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
        "requestId": req_id,
        "timestamp": timestamp,
    })


def _make_thinking_line(req_id="req_001", timestamp="2026-02-14T10:00:01Z"):
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "internal thought"}],
        },
        "requestId": req_id,
        "timestamp": timestamp,
    })


def _make_tool_use_line(req_id="req_001", timestamp="2026-02-14T10:00:01Z"):
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_123", "name": "Read", "input": {}}],
        },
        "requestId": req_id,
        "timestamp": timestamp,
    })


def _make_tool_result_line(timestamp="2026-02-14T10:00:02Z"):
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "file contents"}],
        },
        "timestamp": timestamp,
    })


def _make_progress_line():
    return json.dumps({"type": "progress", "data": "streaming..."})


def _make_snapshot_line():
    return json.dumps({"type": "file-history-snapshot", "snapshot": {}})


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- Tests --

class TestExtractUserText:
    def test_string_content(self):
        obj = {"message": {"content": "Hello world"}}
        assert _extract_user_text(obj) == "Hello world"

    def test_string_whitespace_only(self):
        obj = {"message": {"content": "  "}}
        assert _extract_user_text(obj) is None

    def test_list_with_text_block(self):
        obj = {"message": {"content": [{"type": "text", "text": "Hi there"}]}}
        assert _extract_user_text(obj) == "Hi there"

    def test_list_with_tool_result_only(self):
        obj = {"message": {"content": [{"type": "tool_result", "content": "data"}]}}
        assert _extract_user_text(obj) is None

    def test_empty_message(self):
        assert _extract_user_text({}) is None
        assert _extract_user_text({"message": {}}) is None


class TestExtractAssistantText:
    def test_text_block(self):
        obj = {"message": {"content": [{"type": "text", "text": "Response here"}]}}
        assert _extract_assistant_text(obj) == "Response here"

    def test_thinking_only(self):
        obj = {"message": {"content": [{"type": "thinking", "thinking": "hmm"}]}}
        assert _extract_assistant_text(obj) is None

    def test_tool_use_only(self):
        obj = {"message": {"content": [{"type": "tool_use", "name": "Read"}]}}
        assert _extract_assistant_text(obj) is None

    def test_mixed_content(self):
        obj = {"message": {"content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "Visible response"},
            {"type": "tool_use", "name": "Bash"},
        ]}}
        assert _extract_assistant_text(obj) == "Visible response"

    def test_non_list_content(self):
        obj = {"message": {"content": "plain string"}}
        assert _extract_assistant_text(obj) is None


class TestParseTranscript:
    def test_basic_conversation(self, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        _write_jsonl(jsonl, [
            _make_user_line("What is Python?"),
            _make_assistant_line("Python is a programming language."),
        ])
        turns = _parse_transcript(jsonl)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[0]["text"] == "What is Python?"
        assert turns[1]["role"] == "assistant"
        assert turns[1]["text"] == "Python is a programming language."

    def test_filters_noise(self, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        _write_jsonl(jsonl, [
            _make_snapshot_line(),
            _make_user_line("Hello"),
            _make_thinking_line("req_001"),
            _make_tool_use_line("req_001"),
            _make_tool_result_line(),
            _make_assistant_line("Hi there", "req_001"),
            _make_progress_line(),
        ])
        turns = _parse_transcript(jsonl)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[0]["text"] == "Hello"
        assert turns[1]["role"] == "assistant"
        assert turns[1]["text"] == "Hi there"

    def test_deduplicates_assistant_by_request_id(self, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        _write_jsonl(jsonl, [
            _make_user_line("Question"),
            _make_assistant_line("Partial", "req_X"),
            _make_assistant_line("Partial answer with more detail", "req_X"),
        ])
        turns = _parse_transcript(jsonl)
        assert len(turns) == 2
        assert turns[1]["text"] == "Partial answer with more detail"

    def test_truncates_long_messages(self, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        long_text = "A" * 2000
        _write_jsonl(jsonl, [_make_user_line(long_text)])
        turns = _parse_transcript(jsonl)
        assert len(turns[0]["text"]) == 800

    def test_handles_malformed_json(self, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        _write_jsonl(jsonl, [
            "not valid json{{{",
            _make_user_line("Good line"),
            "",
        ])
        turns = _parse_transcript(jsonl)
        assert len(turns) == 1
        assert turns[0]["text"] == "Good line"

    def test_missing_file(self, tmp_path):
        turns = _parse_transcript(tmp_path / "nonexistent.jsonl")
        assert turns == []


class TestFindJsonl:
    def test_finds_exact_match(self, tmp_path):
        fake_projects = tmp_path / "projects"
        proj_dir = fake_projects / "C--Users-Test"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "abc123.jsonl"
        jsonl.write_text("{}", encoding="utf-8")

        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = _find_jsonl("abc123")
        assert result == jsonl

    def test_returns_none_for_missing(self, tmp_path):
        fake_projects = tmp_path / "projects"
        fake_projects.mkdir()

        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = _find_jsonl("nonexistent")
        assert result is None


class TestGetSessionContext:
    def _setup_session(self, tmp_path, session_id="test-session-123"):
        fake_projects = tmp_path / "projects"
        proj_dir = fake_projects / "C--Test-Project"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / f"{session_id}.jsonl"

        lines = []
        # Opening turns
        lines.append(_make_user_line("Let's build Splunk dashboards", "2026-02-14T09:00:00Z"))
        lines.append(_make_assistant_line(
            "Here's the plan for this session:\n\n3 Dashboards:\n"
            "1. Authentication Overview\n2. Kerberos Activity Monitor\n3. AD Object Access",
            "req_plan", "2026-02-14T09:00:01Z"
        ))
        # Middle turns
        for i in range(20):
            lines.append(_make_user_line(f"Question {i}", f"2026-02-14T09:{i+1:02d}:00Z"))
            lines.append(_make_assistant_line(f"Answer {i}", f"req_{i:03d}", f"2026-02-14T09:{i+1:02d}:01Z"))
        # Recent turns
        lines.append(_make_user_line("What about Kerberoasting?", "2026-02-14T10:00:00Z"))
        lines.append(_make_assistant_line("Kerberoasting targets service tickets.", "req_final", "2026-02-14T10:00:01Z"))

        _write_jsonl(jsonl, lines)
        return fake_projects

    def test_recent_mode(self, tmp_path):
        fake_projects = self._setup_session(tmp_path)
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("test-session-123", last_n=5)

        assert result["status"] == "ok"
        assert result["mode"] == "recent"
        assert result["total_turns"] == 44
        assert len(result["turns"]) == 5
        assert "session_opening" in result
        assert len(result["session_opening"]) == 3

    def test_snippet_mode(self, tmp_path):
        fake_projects = self._setup_session(tmp_path)
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("test-session-123", snippet="3 Dashboards")

        assert result["status"] == "ok"
        assert result["mode"] == "snippet"
        assert result["match_turn"] == 1  # second turn (assistant plan)
        assert any("3 Dashboards" in t["text"] for t in result["turns"])

    def test_snippet_not_found_fallback(self, tmp_path):
        fake_projects = self._setup_session(tmp_path)
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("test-session-123", snippet="XYZZY_NONEXISTENT")

        assert result["status"] == "snippet_not_found"
        assert len(result["turns"]) > 0

    def test_partial_session_id(self, tmp_path):
        fake_projects = self._setup_session(tmp_path)
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("test-session")

        assert result["status"] == "ok"
        assert result["session_id"] == "test-session-123"

    def test_session_not_found(self, tmp_path):
        fake_projects = tmp_path / "projects"
        fake_projects.mkdir()
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("nonexistent-id")

        assert result["status"] == "not_found"

    def test_ambiguous_partial_id(self, tmp_path):
        fake_projects = tmp_path / "projects"
        proj_dir = fake_projects / "C--Test"
        proj_dir.mkdir(parents=True)
        (proj_dir / "session-aaa-111.jsonl").write_text("{}", encoding="utf-8")
        (proj_dir / "session-aaa-222.jsonl").write_text("{}", encoding="utf-8")

        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("session-aaa")

        assert result["status"] == "ambiguous"
        assert len(result["matches"]) == 2

    def test_empty_transcript(self, tmp_path):
        fake_projects = tmp_path / "projects"
        proj_dir = fake_projects / "C--Test"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "empty-session.jsonl"
        # Only noise lines
        _write_jsonl(jsonl, [_make_snapshot_line(), _make_progress_line()])

        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("empty-session")

        assert result["status"] == "empty"

    def test_snippet_case_insensitive(self, tmp_path):
        fake_projects = self._setup_session(tmp_path)
        with patch("jaybrain.pulse._CLAUDE_PROJECTS_DIR", fake_projects):
            result = get_session_context("test-session-123", snippet="kerberoasting")

        assert result["status"] == "ok"
        assert result["mode"] == "snippet"
