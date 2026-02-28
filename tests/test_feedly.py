"""Tests for the Feedly AI Feed monitor module."""

from unittest.mock import patch, MagicMock

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db


FAKE_EMBEDDING = [0.1] * 384


@pytest.fixture(autouse=True)
def mock_embed():
    """Mock embed_text to avoid loading ONNX model during tests."""
    with patch("jaybrain.knowledge.embed_text", return_value=FAKE_EMBEDDING):
        yield


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


SAMPLE_FEEDLY_ITEM = {
    "id": "feedly_article_001",
    "title": "New Ransomware Variant Targets Critical Infrastructure",
    "summary": {
        "content": "<p>A new ransomware strain has been <b>detected</b> targeting SCADA systems.</p>",
    },
    "canonicalUrl": "https://example.com/article1",
    "published": 1709136000000,
    "author": "Jane Security",
    "origin": {"title": "SecurityWeek"},
    "keywords": ["ransomware", "SCADA", "critical infrastructure"],
    "entities": [{"label": "CISA"}],
}

SAMPLE_FEEDLY_RESPONSE = {
    "items": [SAMPLE_FEEDLY_ITEM],
}


class TestStripHtml:
    def test_strip_basic(self):
        from jaybrain.feedly import _strip_html

        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_empty(self):
        from jaybrain.feedly import _strip_html

        assert _strip_html("") == ""


class TestParseArticle:
    def test_parse_basic(self, temp_data_dir):
        from jaybrain.feedly import _parse_article

        article = _parse_article(SAMPLE_FEEDLY_ITEM)
        assert article["feedly_id"] == "feedly_article_001"
        assert article["title"] == "New Ransomware Variant Targets Critical Infrastructure"
        assert "SCADA" in article["summary_text"]
        assert "<p>" not in article["summary_text"]
        assert article["source_url"] == "https://example.com/article1"
        assert "ransomware" in article["tags"]
        assert "cisa" in article["tags"]

    def test_parse_missing_fields(self, temp_data_dir):
        from jaybrain.feedly import _parse_article

        article = _parse_article({"id": "minimal", "title": "Minimal"})
        assert article["feedly_id"] == "minimal"
        assert article["title"] == "Minimal"


class TestDedup:
    def test_not_seen_initially(self, temp_data_dir):
        _setup(temp_data_dir)
        from jaybrain.feedly import _is_seen

        conn = get_connection()
        try:
            assert not _is_seen(conn, "new_article_id")
        finally:
            conn.close()

    def test_mark_and_check_seen(self, temp_data_dir):
        _setup(temp_data_dir)
        from jaybrain.feedly import _is_seen, _mark_seen

        conn = get_connection()
        try:
            _mark_seen(conn, "article_123", "knowledge_456", "Title", "http://example.com", None)
            assert _is_seen(conn, "article_123")
            assert not _is_seen(conn, "article_999")
        finally:
            conn.close()


class TestRunFeedlyMonitor:
    @pytest.fixture(autouse=True)
    def _mock_config(self, monkeypatch):
        """Ensure feedly config is set for monitor tests."""
        import jaybrain.feedly as feedly_mod
        monkeypatch.setattr(feedly_mod, "FEEDLY_ACCESS_TOKEN", "fake_token")
        monkeypatch.setattr(feedly_mod, "FEEDLY_STREAM_ID", "feed/test")

    @patch("jaybrain.feedly.fetch_stream")
    def test_stores_new_articles(self, mock_fetch, temp_data_dir):
        _setup(temp_data_dir)
        mock_fetch.return_value = SAMPLE_FEEDLY_RESPONSE

        from jaybrain.feedly import run_feedly_monitor

        with patch("jaybrain.telegram.send_telegram_message"):
            result = run_feedly_monitor()

        assert result["status"] == "ok"
        assert result["new"] == 1

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM knowledge WHERE category = 'feedly'"
            ).fetchone()
            assert row is not None
            assert "Ransomware" in row["title"]
        finally:
            conn.close()

    @patch("jaybrain.feedly.fetch_stream")
    def test_dedup_prevents_double_store(self, mock_fetch, temp_data_dir):
        _setup(temp_data_dir)
        mock_fetch.return_value = SAMPLE_FEEDLY_RESPONSE

        from jaybrain.feedly import run_feedly_monitor

        with patch("jaybrain.telegram.send_telegram_message"):
            result1 = run_feedly_monitor()
            result2 = run_feedly_monitor()

        assert result1["new"] == 1
        assert result2["new"] == 0

    def test_skips_when_unconfigured(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir)
        import jaybrain.feedly as feedly_mod
        monkeypatch.setattr(feedly_mod, "FEEDLY_ACCESS_TOKEN", "")
        from jaybrain.feedly import run_feedly_monitor

        result = run_feedly_monitor()
        assert result["status"] == "skipped"

    @patch("jaybrain.feedly.fetch_stream")
    def test_handles_empty_response(self, mock_fetch, temp_data_dir):
        _setup(temp_data_dir)
        mock_fetch.return_value = {"items": []}

        from jaybrain.feedly import run_feedly_monitor

        result = run_feedly_monitor()
        assert result["status"] == "ok"
        assert result["new"] == 0


class TestFeedlyStatus:
    def test_status_empty(self, temp_data_dir):
        _setup(temp_data_dir)
        from jaybrain.feedly import get_feedly_status

        status = get_feedly_status()
        assert status["total_articles"] == 0
        assert status["last_fetch"] is None
        assert status["recent"] == []
