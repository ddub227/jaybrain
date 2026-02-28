"""Tests for SignalForge full-text article fetching and lifecycle."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import SIGNALFORGE_MAX_ARTICLE_CHARS
from jaybrain.db import (
    get_connection,
    init_db,
    insert_signalforge_article,
    get_signalforge_article,
    get_signalforge_article_by_knowledge_id,
    list_signalforge_pending,
    list_signalforge_expired,
    update_signalforge_article,
    count_signalforge_by_status,
    now_iso,
)


FAKE_EMBEDDING = [0.1] * 384


@pytest.fixture(autouse=True)
def mock_embed():
    with patch("jaybrain.knowledge.embed_text", return_value=FAKE_EMBEDDING):
        yield


def _setup_db(temp_data_dir):
    """Initialize DB and return a connection."""
    init_db()
    return get_connection()


def _insert_knowledge_row(conn, kid, title="Test Article", url="https://example.com/article"):
    """Insert a knowledge row for FK references."""
    now = now_iso()
    conn.execute(
        "INSERT INTO knowledge (id, title, content, category, tags, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'news_feed', '[]', ?, ?, ?)",
        (kid, title, f"Summary of {title}", url, now, now),
    )
    conn.commit()


def _insert_news_feed_article(conn, kid, url="https://example.com/article", source_id="src1"):
    """Insert a news_feed_articles row."""
    # Ensure source exists
    try:
        now = now_iso()
        conn.execute(
            "INSERT INTO news_feed_sources (id, name, url, source_type, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, 'rss', '[]', ?, ?)",
            (source_id, "Test Source", "https://example.com/feed", now, now),
        )
        conn.commit()
    except Exception:
        pass  # already exists

    conn.execute(
        "INSERT INTO news_feed_articles (source_id, source_article_id, knowledge_id, title, url, fetched_at) "
        "VALUES (?, ?, ?, 'Test', ?, ?)",
        (source_id, uuid.uuid4().hex[:8], kid, url, now_iso()),
    )
    conn.commit()


# =============================================================================
# Google News URL Resolution
# =============================================================================


class TestGoogleNewsUrl:
    def test_passthrough_non_google(self):
        from jaybrain.signalforge import _resolve_google_news_url

        url = "https://example.com/article"
        assert _resolve_google_news_url(url) == url

    def test_decode_success(self):
        from jaybrain.signalforge import _resolve_google_news_url

        google_url = "https://news.google.com/rss/articles/abc123"
        with patch("googlenewsdecoder.new_decoderv1") as mock_decode:
            mock_decode.return_value = {
                "status": True,
                "decoded_url": "https://real-article.com/story",
            }
            result = _resolve_google_news_url(google_url)
            assert result == "https://real-article.com/story"
            mock_decode.assert_called_once()

    def test_decode_failure_returns_original(self):
        from jaybrain.signalforge import _resolve_google_news_url

        google_url = "https://news.google.com/rss/articles/abc123"
        with patch("googlenewsdecoder.new_decoderv1") as mock_decode:
            mock_decode.side_effect = Exception("decode failed")
            result = _resolve_google_news_url(google_url)
            assert result == google_url

    def test_empty_url(self):
        from jaybrain.signalforge import _resolve_google_news_url

        assert _resolve_google_news_url("") == ""


# =============================================================================
# Article Extraction
# =============================================================================


class TestArticleExtraction:
    def test_trafilatura_success(self):
        from jaybrain.signalforge import _extract_article_text

        with patch("trafilatura.extract") as mock_traf:
            mock_traf.return_value = "This is the article text."
            result = _extract_article_text("<html><body>text</body></html>", "https://example.com")
            assert result == "This is the article text."

    def test_fallback_to_bs4(self):
        from jaybrain.signalforge import _extract_article_text

        with patch("trafilatura.extract") as mock_traf:
            mock_traf.return_value = None  # trafilatura returns nothing
            with patch("jaybrain.scraping.extract_clean_text") as mock_bs4:
                mock_bs4.return_value = "BS4 extracted text."
                result = _extract_article_text("<html><body>text</body></html>", "https://example.com")
                assert result == "BS4 extracted text."

    def test_truncation(self):
        from jaybrain.signalforge import _extract_article_text

        long_text = "A" * (SIGNALFORGE_MAX_ARTICLE_CHARS + 1000)
        with patch("trafilatura.extract") as mock_traf:
            mock_traf.return_value = long_text
            result = _extract_article_text("<html></html>", "https://example.com")
            assert len(result) == SIGNALFORGE_MAX_ARTICLE_CHARS

    def test_empty_returns_empty(self):
        from jaybrain.signalforge import _extract_article_text

        with patch("trafilatura.extract") as mock_traf:
            mock_traf.return_value = None
            with patch("jaybrain.scraping.extract_clean_text") as mock_bs4:
                mock_bs4.return_value = ""
                result = _extract_article_text("<html></html>", "https://example.com")
                assert result == ""


# =============================================================================
# File Storage
# =============================================================================


class TestFileStorage:
    def test_path_format(self):
        from jaybrain.signalforge import _article_path

        dt = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        path = _article_path("abc123", date=dt)
        assert "2026-02-28" in str(path)
        assert "abc123.txt" in str(path)

    def test_write_and_read(self, temp_data_dir):
        from jaybrain.signalforge import _save_article_text, read_article_text

        _setup_db(temp_data_dir)
        kid = "test_kid_1"
        text = "Full article text here."

        # Set up DB rows for read_article_text
        conn = get_connection()
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf1", kid)
        path = _save_article_text(kid, text)
        update_signalforge_article(
            conn, "sf1",
            fetch_status="fetched",
            content_path=str(path),
        )
        conn.close()

        # Read back
        result = read_article_text(kid)
        assert result == text

    def test_read_missing_file(self, temp_data_dir):
        from jaybrain.signalforge import read_article_text

        _setup_db(temp_data_dir)
        kid = "missing_kid"
        conn = get_connection()
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_missing", kid)
        update_signalforge_article(
            conn, "sf_missing",
            fetch_status="fetched",
            content_path="/nonexistent/path.txt",
        )
        conn.close()

        result = read_article_text(kid)
        assert result is None

    def test_read_not_fetched(self, temp_data_dir):
        from jaybrain.signalforge import read_article_text

        _setup_db(temp_data_dir)
        kid = "pending_kid"
        conn = get_connection()
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_pending", kid)
        conn.close()

        result = read_article_text(kid)
        assert result is None


# =============================================================================
# Skip Logic
# =============================================================================


class TestShouldSkipUrl:
    def test_hn_skipped(self):
        from jaybrain.signalforge import _should_skip_url

        assert _should_skip_url("https://news.ycombinator.com/item?id=123") is True

    def test_empty_skipped(self):
        from jaybrain.signalforge import _should_skip_url

        assert _should_skip_url("") is True

    def test_normal_not_skipped(self):
        from jaybrain.signalforge import _should_skip_url

        assert _should_skip_url("https://example.com/article") is False


# =============================================================================
# Fetch Single Article
# =============================================================================


class TestFetchSingle:
    def test_success(self):
        from jaybrain.signalforge import _fetch_single_article

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Article content here.</p></body></html>"

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            with patch("trafilatura.extract", return_value="Article content here."):
                with patch("jaybrain.signalforge._save_article_text") as mock_save:
                    mock_save.return_value = Path("/data/articles/2026-02-28/kid1.txt")
                    result = _fetch_single_article("kid1", "https://example.com/article")

        assert result["status"] == "fetched"
        assert result["word_count"] == 3
        assert result["char_count"] == 21

    def test_429_rate_limit(self):
        from jaybrain.signalforge import _fetch_single_article

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            result = _fetch_single_article("kid1", "https://example.com/article")

        assert result["status"] == "failed"
        assert "429" in result["error"]

    def test_403_forbidden(self):
        from jaybrain.signalforge import _fetch_single_article

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            result = _fetch_single_article("kid1", "https://example.com/article")

        assert result["status"] == "failed"
        assert "403" in result["error"]

    def test_skipped_url(self):
        from jaybrain.signalforge import _fetch_single_article

        result = _fetch_single_article("kid1", "https://news.ycombinator.com/item?id=123")
        assert result["status"] == "skipped"


# =============================================================================
# Enqueue
# =============================================================================


class TestEnqueue:
    def test_creates_rows(self, temp_data_dir):
        from jaybrain.signalforge import _enqueue_new_articles

        conn = _setup_db(temp_data_dir)
        kid = "enqueue_kid_1"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/article1")
        conn.close()

        count = _enqueue_new_articles()
        assert count == 1

        conn = get_connection()
        pending = list_signalforge_pending(conn)
        assert len(pending) == 1
        assert pending[0]["knowledge_id"] == kid
        conn.close()

    def test_no_duplicates(self, temp_data_dir):
        from jaybrain.signalforge import _enqueue_new_articles

        conn = _setup_db(temp_data_dir)
        kid = "enqueue_kid_2"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/article2")
        conn.close()

        # First enqueue
        count1 = _enqueue_new_articles()
        assert count1 == 1

        # Second enqueue -- should find 0 new
        count2 = _enqueue_new_articles()
        assert count2 == 0

    def test_skips_empty_urls(self, temp_data_dir):
        from jaybrain.signalforge import _enqueue_new_articles

        conn = _setup_db(temp_data_dir)
        kid = "enqueue_empty"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="")
        conn.close()

        count = _enqueue_new_articles()
        assert count == 0


# =============================================================================
# Run Fetch (Daemon Entry Point)
# =============================================================================


class TestRunFetch:
    def test_happy_path(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_fetch

        conn = _setup_db(temp_data_dir)
        kid = "fetch_kid_1"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/story")
        conn.close()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Story content.</p></body></html>"

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            with patch("trafilatura.extract", return_value="Story content."):
                with patch("jaybrain.signalforge.time.sleep"):
                    result = run_signalforge_fetch()

        assert result["enqueued"] == 1
        assert result["fetched"] == 1
        assert result["failed"] == 0

    def test_empty_pending(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_fetch

        _setup_db(temp_data_dir)

        result = run_signalforge_fetch()
        assert result["enqueued"] == 0
        assert result["fetched"] == 0

    def test_backoff_on_429(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_fetch

        conn = _setup_db(temp_data_dir)
        kid = "fetch_429"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/rate-limited")
        conn.close()

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            with patch("jaybrain.signalforge.time.sleep"):
                result = run_signalforge_fetch()

        assert result["failed"] == 1

        # Verify status is failed in DB
        conn = get_connection()
        counts = count_signalforge_by_status(conn)
        assert counts.get("failed", 0) == 1
        conn.close()


# =============================================================================
# Cleanup
# =============================================================================


class TestCleanup:
    def test_deletes_files(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_cleanup, _save_article_text

        conn = _setup_db(temp_data_dir)
        kid = "cleanup_kid"
        _insert_knowledge_row(conn, kid)

        # Create a file
        path = _save_article_text(kid, "Old article text.")
        assert path.exists()

        # Insert signalforge row with past expiry
        insert_signalforge_article(conn, "sf_exp", kid)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        update_signalforge_article(
            conn, "sf_exp",
            fetch_status="fetched",
            content_path=str(path),
            expires_at=past,
        )
        conn.close()

        result = run_signalforge_cleanup()
        assert result["expired_count"] == 1
        assert result["deleted_files"] == 1
        assert not path.exists()

    def test_updates_status(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_cleanup, _save_article_text

        conn = _setup_db(temp_data_dir)
        kid = "cleanup_status"
        _insert_knowledge_row(conn, kid)
        path = _save_article_text(kid, "Text.")
        insert_signalforge_article(conn, "sf_exp2", kid)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        update_signalforge_article(
            conn, "sf_exp2",
            fetch_status="fetched",
            content_path=str(path),
            expires_at=past,
        )
        conn.close()

        run_signalforge_cleanup()

        conn = get_connection()
        row = get_signalforge_article(conn, "sf_exp2")
        assert row["fetch_status"] == "expired"
        assert row["content_path"] == ""
        conn.close()

    def test_removes_empty_date_dir(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_cleanup, _save_article_text

        conn = _setup_db(temp_data_dir)
        kid = "cleanup_dir"
        _insert_knowledge_row(conn, kid)
        path = _save_article_text(kid, "Text.")
        date_dir = path.parent
        assert date_dir.exists()

        insert_signalforge_article(conn, "sf_dir", kid)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        update_signalforge_article(
            conn, "sf_dir",
            fetch_status="fetched",
            content_path=str(path),
            expires_at=past,
        )
        conn.close()

        run_signalforge_cleanup()
        assert not date_dir.exists()


# =============================================================================
# Status
# =============================================================================


class TestStatus:
    def test_empty_db(self, temp_data_dir):
        from jaybrain.signalforge import get_signalforge_status

        _setup_db(temp_data_dir)
        status = get_signalforge_status()
        assert status["status_counts"] == {}
        assert status["storage"]["file_count"] == 0
        assert status["avg_word_count"] == 0

    def test_after_fetching(self, temp_data_dir):
        from jaybrain.signalforge import get_signalforge_status, _save_article_text

        conn = _setup_db(temp_data_dir)
        kid = "status_kid"
        _insert_knowledge_row(conn, kid, title="Test Status Article")
        insert_signalforge_article(conn, "sf_stat", kid)

        path = _save_article_text(kid, "Some article text content here.")
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        update_signalforge_article(
            conn, "sf_stat",
            fetch_status="fetched",
            content_path=str(path),
            word_count=5,
            char_count=31,
            fetched_at=now_iso(),
            expires_at=expires,
        )
        conn.close()

        status = get_signalforge_status()
        assert status["status_counts"].get("fetched") == 1
        assert status["storage"]["file_count"] == 1
        assert status["avg_word_count"] == 5
        assert len(status["recent_fetches"]) == 1
        assert status["recent_fetches"][0]["title"] == "Test Status Article"


# =============================================================================
# Fetch Single (MCP Entry Point)
# =============================================================================


class TestFetchSingleMcp:
    def test_creates_and_fetches(self, temp_data_dir):
        from jaybrain.signalforge import fetch_single

        conn = _setup_db(temp_data_dir)
        kid = "mcp_kid_1"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/mcp-article")
        conn.close()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>MCP article.</p></body></html>"

        with patch("jaybrain.signalforge.requests.get", return_value=mock_resp):
            with patch("trafilatura.extract", return_value="MCP article content."):
                result = fetch_single(kid)

        assert result["status"] == "fetched"
        assert result["word_count"] == 3

    def test_already_fetched(self, temp_data_dir):
        from jaybrain.signalforge import fetch_single

        conn = _setup_db(temp_data_dir)
        kid = "mcp_already"
        _insert_knowledge_row(conn, kid)
        _insert_news_feed_article(conn, kid, url="https://example.com/already")
        insert_signalforge_article(conn, "sf_already", kid)
        update_signalforge_article(
            conn, "sf_already",
            fetch_status="fetched",
            content_path="/data/articles/test.txt",
            word_count=100,
        )
        conn.close()

        result = fetch_single(kid)
        assert result["status"] == "already_fetched"
        assert result["word_count"] == 100


# =============================================================================
# DB CRUD Functions
# =============================================================================


class TestSignalforgeDb:
    def test_insert_and_get(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "db_kid_1"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_db1", kid)

        row = get_signalforge_article(conn, "sf_db1")
        assert row is not None
        assert row["knowledge_id"] == kid
        assert row["fetch_status"] == "pending"
        conn.close()

    def test_get_by_knowledge_id(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "db_kid_2"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_db2", kid)

        row = get_signalforge_article_by_knowledge_id(conn, kid)
        assert row is not None
        assert row["id"] == "sf_db2"
        conn.close()

    def test_list_pending(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        for i in range(3):
            kid = f"pending_{i}"
            _insert_knowledge_row(conn, kid)
            insert_signalforge_article(conn, f"sf_p{i}", kid)

        pending = list_signalforge_pending(conn)
        assert len(pending) == 3
        conn.close()

    def test_update(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "update_kid"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_upd", kid)

        success = update_signalforge_article(
            conn, "sf_upd",
            fetch_status="fetched",
            word_count=500,
        )
        assert success is True

        row = get_signalforge_article(conn, "sf_upd")
        assert row["fetch_status"] == "fetched"
        assert row["word_count"] == 500
        conn.close()

    def test_count_by_status(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        for i in range(3):
            kid = f"count_{i}"
            _insert_knowledge_row(conn, kid)
            insert_signalforge_article(conn, f"sf_c{i}", kid)

        # Update one to fetched
        update_signalforge_article(conn, "sf_c0", fetch_status="fetched")

        counts = count_signalforge_by_status(conn)
        assert counts.get("pending") == 2
        assert counts.get("fetched") == 1
        conn.close()

    def test_list_expired(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "expired_kid"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_expired", kid)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        update_signalforge_article(
            conn, "sf_expired",
            fetch_status="fetched",
            expires_at=past,
        )

        expired = list_signalforge_expired(conn)
        assert len(expired) == 1
        assert expired[0]["id"] == "sf_expired"
        conn.close()
