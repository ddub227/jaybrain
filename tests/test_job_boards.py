"""Tests for the job_boards module."""

import pytest
from unittest.mock import patch, MagicMock

from jaybrain.db import init_db, get_connection, get_job_board, update_job_board
from jaybrain.config import ensure_data_dirs
from jaybrain.job_boards import add_board, get_boards, fetch_board, auto_fetch_boards


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


class TestAddBoard:
    def test_add_basic(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board("LinkedIn", "https://linkedin.com/jobs")
        assert board.name == "LinkedIn"
        assert board.url == "https://linkedin.com/jobs"
        assert board.board_type == "general"
        assert board.active is True
        assert board.tags == []
        assert len(board.id) == 12

    def test_add_with_fields(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board(
            "We Work Remotely",
            "https://weworkremotely.com",
            board_type="niche",
            tags=["remote", "tech"],
        )
        assert board.board_type == "niche"
        assert board.tags == ["remote", "tech"]


class TestGetBoards:
    def test_empty(self, temp_data_dir):
        _setup_db(temp_data_dir)
        boards = get_boards()
        assert boards == []

    def test_list_active(self, temp_data_dir):
        _setup_db(temp_data_dir)
        add_board("Board A", "https://a.com")
        add_board("Board B", "https://b.com")

        boards = get_boards()
        assert len(boards) == 2

    def test_list_includes_inactive(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board("Active", "https://active.com")
        add_board("Inactive", "https://inactive.com")

        # Deactivate one
        conn = get_connection()
        from jaybrain.db import update_job_board
        update_job_board(conn, boards[0].id if False else board.id, active=0)
        conn.close()

        active_boards = get_boards(active_only=True)
        all_boards = get_boards(active_only=False)
        assert len(all_boards) == 2
        assert len(active_boards) == 1


class TestFetchBoard:
    def test_fetch_not_found(self, temp_data_dir):
        _setup_db(temp_data_dir)
        with pytest.raises(ValueError, match="Job board not found"):
            fetch_board("nonexistent")

    def test_fetch_success(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board("Test Board", "https://example.com/jobs")

        mock_pages = [{
            "url": "https://example.com/jobs",
            "text": "Software Engineer at Acme Corp\nPython, SQL required",
            "text_length": 50,
            "rendered": False,
            "metadata": {"title": "Jobs Page"},
        }]

        with patch("jaybrain.scraping.fetch_pages", return_value=mock_pages):
            result = fetch_board(board.id)

        assert result["board_id"] == board.id
        assert result["board_name"] == "Test Board"
        assert "Software Engineer" in result["content"]
        assert result["pages_fetched"] == 1
        assert result["js_rendered"] is False

    def test_fetch_updates_last_checked(self, temp_data_dir):
        _setup_db(temp_data_dir)
        board = add_board("Check Board", "https://example.com")
        assert board.last_checked is None

        mock_pages = [{
            "url": "https://example.com",
            "text": "Jobs",
            "text_length": 4,
            "rendered": False,
            "metadata": {},
        }]

        with patch("jaybrain.scraping.fetch_pages", return_value=mock_pages):
            fetch_board(board.id)

        # Verify last_checked was updated
        conn = get_connection()
        row = get_job_board(conn, board.id)
        assert row["last_checked"] is not None
        conn.close()


class TestAutoFetchBoards:
    def _mock_pages(self, text="Job listing content"):
        return [{
            "url": "https://example.com",
            "text": text,
            "text_length": len(text),
            "rendered": False,
            "metadata": {},
        }]

    def test_no_boards(self, temp_data_dir):
        _setup_db(temp_data_dir)
        result = auto_fetch_boards()
        assert result["checked"] == 0
        assert result["changed"] == 0

    def test_first_fetch_detects_change(self, temp_data_dir):
        """First fetch always counts as a change (empty hash -> new hash)."""
        _setup_db(temp_data_dir)
        add_board("Test", "https://example.com")

        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages()):
            with patch("jaybrain.telegram.send_telegram_message"):
                result = auto_fetch_boards()

        assert result["checked"] == 1
        assert result["changed"] == 1
        assert len(result["changed_boards"]) == 1

    def test_no_change_on_same_content(self, temp_data_dir):
        """Second fetch with same content should not count as changed."""
        _setup_db(temp_data_dir)
        board = add_board("Test", "https://example.com")
        content = "Same content"

        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages(content)):
            with patch("jaybrain.telegram.send_telegram_message"):
                auto_fetch_boards()

        # Second fetch with identical content
        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages(content)):
            result = auto_fetch_boards()

        assert result["checked"] == 1
        assert result["changed"] == 0

    def test_change_detected_on_different_content(self, temp_data_dir):
        """Content change between fetches should be detected."""
        _setup_db(temp_data_dir)
        add_board("Test", "https://example.com")

        # First fetch
        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages("v1")):
            with patch("jaybrain.telegram.send_telegram_message"):
                auto_fetch_boards()

        # Second fetch with different content
        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages("v2")):
            with patch("jaybrain.telegram.send_telegram_message"):
                result = auto_fetch_boards()

        assert result["changed"] == 1

    def test_fetch_error_counted(self, temp_data_dir):
        """Boards that fail to fetch should increment the error count."""
        _setup_db(temp_data_dir)
        add_board("Bad Board", "https://broken.example.com")

        with patch("jaybrain.scraping.fetch_pages", side_effect=Exception("timeout")):
            result = auto_fetch_boards()

        assert result["errors"] == 1
        assert result["checked"] == 0

    def test_sends_telegram_on_change(self, temp_data_dir):
        """Should send a Telegram notification when boards change."""
        _setup_db(temp_data_dir)
        add_board("Board A", "https://a.com")

        mock_send = MagicMock()
        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages()):
            with patch("jaybrain.telegram.send_telegram_message", mock_send):
                auto_fetch_boards()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "1 job board(s) have new content" in msg
        assert "Board A" in msg

    def test_updates_content_hash(self, temp_data_dir):
        """content_hash should be stored after fetch."""
        _setup_db(temp_data_dir)
        board = add_board("Test", "https://example.com")

        with patch("jaybrain.scraping.fetch_pages", return_value=self._mock_pages()):
            with patch("jaybrain.telegram.send_telegram_message"):
                auto_fetch_boards()

        conn = get_connection()
        row = get_job_board(conn, board.id)
        assert row["content_hash"] != ""
        assert len(row["content_hash"]) == 64  # SHA-256 hex
        conn.close()
