"""Tests for SignalForge: article fetching, lifecycle, and story clustering."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from jaybrain.config import SIGNALFORGE_MAX_ARTICLE_CHARS
from jaybrain.db import (
    _serialize_f32,
    get_connection,
    get_signalforge_synthesis,
    get_signalforge_synthesis_by_date,
    init_db,
    insert_signalforge_article,
    insert_signalforge_synthesis,
    get_signalforge_article,
    get_signalforge_article_by_knowledge_id,
    get_signalforge_cluster,
    get_cluster_articles,
    insert_signalforge_cluster,
    insert_cluster_article,
    list_signalforge_clusters,
    list_signalforge_pending,
    list_signalforge_expired,
    list_signalforge_syntheses,
    update_signalforge_article,
    update_signalforge_synthesis,
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


def _insert_knowledge_row(conn, kid, title="Test Article", url="https://example.com/article",
                          embedding=None):
    """Insert a knowledge row (+ vec embedding) for FK references."""
    now = now_iso()
    conn.execute(
        "INSERT INTO knowledge (id, title, content, category, tags, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'news_feed', '[]', ?, ?, ?)",
        (kid, title, f"Summary of {title}", url, now, now),
    )
    # Also insert embedding into knowledge_vec
    vec = embedding if embedding is not None else FAKE_EMBEDDING
    conn.execute(
        "INSERT INTO knowledge_vec (id, embedding) VALUES (?, ?)",
        (kid, _serialize_f32(vec)),
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
# Title Slugification
# =============================================================================


class TestSlugifyTitle:
    def test_basic(self):
        from jaybrain.signalforge import _slugify_title

        assert _slugify_title("Claude Code Flaws Found") == "claude-code-flaws-found"

    def test_special_chars(self):
        from jaybrain.signalforge import _slugify_title

        result = _slugify_title("What's New in AI — A Developer's Guide!")
        assert result == "whats-new-in-ai-a-developers-guide"

    def test_truncation(self):
        from jaybrain.signalforge import _slugify_title

        long_title = "This Is A Very Long Title " * 10
        result = _slugify_title(long_title, max_len=30)
        assert len(result) <= 30

    def test_empty(self):
        from jaybrain.signalforge import _slugify_title

        assert _slugify_title("") == "untitled"


# =============================================================================
# Article Formatting
# =============================================================================


class TestFormatArticleText:
    def test_adds_header(self):
        from jaybrain.signalforge import _format_article_text

        result = _format_article_text(
            "Body text.", title="My Article", url="https://example.com",
        )
        assert "My Article" in result
        assert "===" in result
        assert "Source: https://example.com" in result
        assert "Body text." in result

    def test_paragraph_separation(self):
        from jaybrain.signalforge import _format_article_text

        text = "First paragraph.\nSecond paragraph.\nThird paragraph."
        result = _format_article_text(text)
        assert "First paragraph.\n\nSecond paragraph.\n\nThird paragraph." in result

    def test_no_title_no_header(self):
        from jaybrain.signalforge import _format_article_text

        result = _format_article_text("Just body text.")
        assert "===" not in result
        assert "Just body text." in result


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
    def test_path_format_with_title(self):
        from jaybrain.signalforge import _article_path

        dt = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        path = _article_path("Claude Code Flaws Found", "abc123", date=dt)
        assert "2026-02-28" in str(path)
        assert "claude-code-flaws-found.txt" in str(path)

    def test_path_format_empty_title_falls_back(self):
        from jaybrain.signalforge import _article_path

        dt = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        path = _article_path("", "abc123", date=dt)
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
        path = _save_article_text("Test Article", kid, text)
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
                    mock_save.return_value = Path("/data/articles/2026-02-28/test-article.txt")
                    result = _fetch_single_article(
                        "kid1", "https://example.com/article",
                        title="Test Article",
                    )

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
        path = _save_article_text("Old Article", kid, "Old article text.")
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
        path = _save_article_text("Status Test", kid, "Text.")
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
        path = _save_article_text("Dir Test", kid, "Text.")
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

        path = _save_article_text("Test Status Article", kid, "Some article text content here.")
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


# =============================================================================
# Cluster DB CRUD
# =============================================================================


class TestClusterDb:
    def test_insert_and_get_cluster(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_cluster(
            conn, "cl1", "Test Cluster", article_count=3,
            source_count=2, avg_similarity=0.85, significance=5.1,
        )
        row = get_signalforge_cluster(conn, "cl1")
        assert row is not None
        assert row["label"] == "Test Cluster"
        assert row["article_count"] == 3
        assert row["significance"] == 5.1
        conn.close()

    def test_list_clusters_by_significance(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_cluster(
            conn, "cl_low", "Low", article_count=2,
            source_count=1, avg_similarity=0.75, significance=1.5,
        )
        insert_signalforge_cluster(
            conn, "cl_high", "High", article_count=5,
            source_count=3, avg_similarity=0.90, significance=13.5,
        )
        clusters = list_signalforge_clusters(conn, limit=10)
        assert len(clusters) == 2
        assert clusters[0]["id"] == "cl_high"  # highest first
        conn.close()

    def test_list_clusters_min_significance(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_cluster(
            conn, "cl_a", "A", article_count=2,
            source_count=1, avg_similarity=0.75, significance=1.0,
        )
        insert_signalforge_cluster(
            conn, "cl_b", "B", article_count=5,
            source_count=3, avg_similarity=0.90, significance=10.0,
        )
        clusters = list_signalforge_clusters(conn, min_significance=5.0)
        assert len(clusters) == 1
        assert clusters[0]["id"] == "cl_b"
        conn.close()

    def test_insert_cluster_article_junction(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "junc_kid"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_cluster(
            conn, "cl_j", "Junction Test", article_count=1,
            source_count=1, avg_similarity=0.80, significance=0.8,
        )
        insert_cluster_article(conn, "cl_j", kid)
        articles = get_cluster_articles(conn, "cl_j")
        assert len(articles) == 1
        assert articles[0]["id"] == kid
        conn.close()

    def test_insert_cluster_article_no_dupes(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        kid = "dupe_kid"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_cluster(
            conn, "cl_d", "Dupe Test", article_count=1,
            source_count=1, avg_similarity=0.80, significance=0.8,
        )
        insert_cluster_article(conn, "cl_d", kid)
        insert_cluster_article(conn, "cl_d", kid)  # INSERT OR IGNORE
        articles = get_cluster_articles(conn, "cl_d")
        assert len(articles) == 1
        conn.close()


# =============================================================================
# Build Clusters Algorithm
# =============================================================================


def _make_similar_vectors(n, base=None):
    """Create n vectors that are similar to each other (cosine > 0.9)."""
    rng = np.random.RandomState(42)
    if base is None:
        base = rng.randn(384).astype(np.float32)
    base = base / np.linalg.norm(base)
    vectors = []
    for _ in range(n):
        noise = rng.randn(384).astype(np.float32) * 0.01
        vec = base + noise
        vec = vec / np.linalg.norm(vec)
        vectors.append(vec.tolist())
    return vectors


def _make_distinct_vectors(n):
    """Create n vectors that are dissimilar (near-orthogonal)."""
    rng = np.random.RandomState(123)
    vectors = []
    for _ in range(n):
        vec = rng.randn(384).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        vectors.append(vec.tolist())
    return vectors


class TestBuildClusters:
    def test_groups_similar(self):
        from jaybrain.signalforge import _build_clusters

        # 3 similar articles + 1 distinct
        similar = _make_similar_vectors(3)
        distinct = _make_distinct_vectors(1)
        items = [
            ("a1", similar[0]),
            ("a2", similar[1]),
            ("a3", similar[2]),
            ("b1", distinct[0]),
        ]
        clusters = _build_clusters(items, threshold=0.72)
        assert len(clusters) == 1
        assert set(clusters[0]["knowledge_ids"]) == {"a1", "a2", "a3"}
        assert clusters[0]["avg_similarity"] > 0.9

    def test_two_groups(self):
        from jaybrain.signalforge import _build_clusters

        rng = np.random.RandomState(42)
        base_a = rng.randn(384).astype(np.float32)
        base_b = rng.randn(384).astype(np.float32)
        group_a = _make_similar_vectors(2, base=base_a)
        group_b = _make_similar_vectors(2, base=base_b)
        items = [
            ("a1", group_a[0]), ("a2", group_a[1]),
            ("b1", group_b[0]), ("b2", group_b[1]),
        ]
        clusters = _build_clusters(items, threshold=0.72)
        assert len(clusters) == 2

    def test_respects_threshold(self):
        from jaybrain.signalforge import _build_clusters

        distinct = _make_distinct_vectors(5)
        items = [(f"d{i}", distinct[i]) for i in range(5)]
        clusters = _build_clusters(items, threshold=0.99)
        assert len(clusters) == 0

    def test_caps_max_size(self):
        from jaybrain.signalforge import _build_clusters

        similar = _make_similar_vectors(10)
        items = [(f"s{i}", similar[i]) for i in range(10)]
        clusters = _build_clusters(items, threshold=0.72, max_size=3)
        assert len(clusters) >= 1
        for c in clusters:
            assert len(c["knowledge_ids"]) <= 3

    def test_fewer_than_two_returns_empty(self):
        from jaybrain.signalforge import _build_clusters

        items = [("a1", [0.1] * 384)]
        assert _build_clusters(items) == []
        assert _build_clusters([]) == []


# =============================================================================
# Compute Significance
# =============================================================================


class TestComputeSignificance:
    def test_basic(self):
        from jaybrain.signalforge import _compute_significance

        # 3 articles, 0.85 similarity, 2 sources = 3 * 0.85 * 2 = 5.1
        result = _compute_significance(3, 0.85, 2)
        assert result == 5.1

    def test_single_source(self):
        from jaybrain.signalforge import _compute_significance

        result = _compute_significance(2, 0.90, 1)
        assert result == 1.8


# =============================================================================
# Generate Cluster Label
# =============================================================================


class TestGenerateClusterLabel:
    def test_picks_shortest_title(self, temp_data_dir):
        from jaybrain.signalforge import _generate_cluster_label

        conn = _setup_db(temp_data_dir)
        _insert_knowledge_row(conn, "lbl1", title="Short Title")
        _insert_knowledge_row(conn, "lbl2", title="A Much Longer Article Title Here")
        label = _generate_cluster_label(conn, ["lbl1", "lbl2"])
        assert label == "Short Title"
        conn.close()

    def test_no_titles(self, temp_data_dir):
        from jaybrain.signalforge import _generate_cluster_label

        conn = _setup_db(temp_data_dir)
        _insert_knowledge_row(conn, "lbl_e", title="")
        label = _generate_cluster_label(conn, ["lbl_e"])
        assert label == "Untitled cluster"
        conn.close()


# =============================================================================
# Get Clusterable Articles
# =============================================================================


class TestGetClusterableArticles:
    def test_returns_fetched_with_embeddings(self, temp_data_dir):
        from jaybrain.signalforge import _get_clusterable_articles

        conn = _setup_db(temp_data_dir)
        kid = "cla_kid1"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_cla1", kid)
        update_signalforge_article(conn, "sf_cla1", fetch_status="fetched")

        items = _get_clusterable_articles(conn, window_days=7)
        assert len(items) == 1
        assert items[0][0] == kid
        assert len(items[0][1]) == 384
        conn.close()

    def test_excludes_pending(self, temp_data_dir):
        from jaybrain.signalforge import _get_clusterable_articles

        conn = _setup_db(temp_data_dir)
        kid = "cla_pending"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_cla_p", kid)
        # status stays pending

        items = _get_clusterable_articles(conn, window_days=7)
        assert len(items) == 0
        conn.close()

    def test_filters_by_window(self, temp_data_dir):
        from jaybrain.signalforge import _get_clusterable_articles

        conn = _setup_db(temp_data_dir)
        kid = "cla_old"
        _insert_knowledge_row(conn, kid)
        # Insert with old created_at
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute(
            "INSERT INTO signalforge_articles (id, knowledge_id, fetch_status, created_at, updated_at) "
            "VALUES (?, ?, 'fetched', ?, ?)",
            ("sf_cla_old", kid, old_date, old_date),
        )
        conn.commit()

        items = _get_clusterable_articles(conn, window_days=3)
        assert len(items) == 0
        conn.close()


# =============================================================================
# Run Clustering (Daemon Entry Point)
# =============================================================================


class TestRunClustering:
    def _setup_cluster_articles(self, conn, count, similar=True):
        """Insert N articles with similar or distinct embeddings."""
        if similar:
            vecs = _make_similar_vectors(count)
        else:
            vecs = _make_distinct_vectors(count)

        kids = []
        for i in range(count):
            kid = f"cluster_kid_{i}"
            _insert_knowledge_row(conn, kid, title=f"Article {i}", embedding=vecs[i])
            _insert_news_feed_article(conn, kid, url=f"https://example.com/a{i}",
                                       source_id=f"src_c{i % 3}")
            insert_signalforge_article(conn, f"sf_cl_{i}", kid)
            update_signalforge_article(conn, f"sf_cl_{i}", fetch_status="fetched")
            kids.append(kid)
        return kids

    def test_happy_path(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering

        conn = _setup_db(temp_data_dir)
        self._setup_cluster_articles(conn, 4, similar=True)
        conn.close()

        result = run_signalforge_clustering()
        assert result["clusters_found"] >= 1
        assert result["articles_clustered"] >= 2

    def test_skips_when_too_few(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering

        conn = _setup_db(temp_data_dir)
        kid = "solo_kid"
        _insert_knowledge_row(conn, kid)
        insert_signalforge_article(conn, "sf_solo", kid)
        update_signalforge_article(conn, "sf_solo", fetch_status="fetched")
        conn.close()

        result = run_signalforge_clustering()
        assert result["clusters_found"] == 0

    def test_no_clusters_when_distinct(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering

        conn = _setup_db(temp_data_dir)
        self._setup_cluster_articles(conn, 4, similar=False)
        conn.close()

        result = run_signalforge_clustering()
        assert result["clusters_found"] == 0

    def test_rebuilds_on_rerun(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering

        conn = _setup_db(temp_data_dir)
        self._setup_cluster_articles(conn, 4, similar=True)
        conn.close()

        result1 = run_signalforge_clustering()
        result2 = run_signalforge_clustering()
        # Should produce same clusters both times (full rebuild)
        assert result1["clusters_found"] == result2["clusters_found"]


# =============================================================================
# Clustering Status + Detail (MCP Helpers)
# =============================================================================


class TestClusteringStatus:
    def test_empty_state(self, temp_data_dir):
        from jaybrain.signalforge import get_clustering_status

        _setup_db(temp_data_dir)
        status = get_clustering_status()
        assert status["total_clusters"] == 0
        assert status["total_articles_clustered"] == 0
        assert status["unclustered_articles"] == 0

    def test_after_clustering(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering, get_clustering_status

        conn = _setup_db(temp_data_dir)
        vecs = _make_similar_vectors(3)
        for i in range(3):
            kid = f"status_kid_{i}"
            _insert_knowledge_row(conn, kid, title=f"Similar Article {i}", embedding=vecs[i])
            _insert_news_feed_article(conn, kid, url=f"https://ex.com/s{i}", source_id="src_s")
            insert_signalforge_article(conn, f"sf_s_{i}", kid)
            update_signalforge_article(conn, f"sf_s_{i}", fetch_status="fetched")
        conn.close()

        run_signalforge_clustering()
        status = get_clustering_status()
        assert status["total_clusters"] >= 1
        assert status["total_articles_clustered"] >= 2
        assert len(status["top_clusters"]) >= 1


class TestClusterDetail:
    def test_returns_articles(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_clustering, get_cluster_detail

        conn = _setup_db(temp_data_dir)
        vecs = _make_similar_vectors(3)
        for i in range(3):
            kid = f"detail_kid_{i}"
            _insert_knowledge_row(conn, kid, title=f"Detail Article {i}", embedding=vecs[i])
            _insert_news_feed_article(conn, kid, url=f"https://ex.com/d{i}", source_id="src_d")
            insert_signalforge_article(conn, f"sf_d_{i}", kid)
            update_signalforge_article(conn, f"sf_d_{i}", fetch_status="fetched")
        conn.close()

        run_signalforge_clustering()

        # Get first cluster
        conn = get_connection()
        clusters = list_signalforge_clusters(conn)
        conn.close()
        assert len(clusters) >= 1

        detail = get_cluster_detail(clusters[0]["id"])
        assert detail is not None
        assert len(detail["articles"]) >= 2
        assert detail["label"] != ""
        assert detail["significance"] > 0

    def test_not_found(self, temp_data_dir):
        from jaybrain.signalforge import get_cluster_detail

        _setup_db(temp_data_dir)
        result = get_cluster_detail("nonexistent")
        assert result is None


# =============================================================================
# Synthesis — LLM-powered daily intelligence article
# =============================================================================


def _mock_anthropic_response(text="Mock synthesis", input_tokens=100, output_tokens=50):
    """Create a mock Anthropic API response."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return mock_response


class TestCallClaude:
    def test_success(self, temp_data_dir):
        from jaybrain.signalforge import _call_claude

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            text="Hello world", input_tokens=10, output_tokens=5,
        )

        with patch("jaybrain.signalforge._get_anthropic_client", return_value=mock_client):
            result = _call_claude("system", "user", max_tokens=100)
            assert result["text"] == "Hello world"
            assert result["input_tokens"] == 10
            assert result["output_tokens"] == 5
            assert "model" in result

    def test_missing_api_key_raises(self, temp_data_dir):
        from jaybrain.signalforge import _get_anthropic_client

        with patch("jaybrain.signalforge.ANTHROPIC_API_KEY", ""):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
                _get_anthropic_client()


class TestGatherClusterData:
    def test_gathers_articles(self, temp_data_dir):
        from jaybrain.signalforge import _gather_cluster_data

        conn = _setup_db(temp_data_dir)
        # Create a cluster with articles
        vecs = _make_similar_vectors(3)
        for i in range(3):
            kid = f"gather_kid_{i}"
            _insert_knowledge_row(conn, kid, title=f"Gather Article {i}", embedding=vecs[i])
            _insert_news_feed_article(conn, kid, url=f"https://ex.com/g{i}", source_id="src_g")
            insert_signalforge_article(conn, f"sf_g_{i}", kid)
            update_signalforge_article(conn, f"sf_g_{i}", fetch_status="fetched")

        insert_signalforge_cluster(conn, "gather_c1", "Test Cluster",
                                   article_count=3, source_count=1,
                                   avg_similarity=0.95, significance=3.0)
        for i in range(3):
            insert_cluster_article(conn, "gather_c1", f"gather_kid_{i}")

        result = _gather_cluster_data(conn, "gather_c1", excerpt_chars=100)
        conn.close()

        assert result is not None
        assert result["cluster_id"] == "gather_c1"
        assert result["label"] == "Test Cluster"
        assert len(result["articles"]) == 3
        assert all(a["text"] for a in result["articles"])

    def test_returns_none_for_missing(self, temp_data_dir):
        from jaybrain.signalforge import _gather_cluster_data

        conn = _setup_db(temp_data_dir)
        result = _gather_cluster_data(conn, "nonexistent", excerpt_chars=100)
        conn.close()
        assert result is None


class TestSynthesizeCluster:
    def test_success(self, temp_data_dir):
        from jaybrain.signalforge import _synthesize_cluster

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            text="Synthesized summary of the cluster.",
            input_tokens=200, output_tokens=80,
        )

        cluster_data = {
            "cluster_id": "c1",
            "label": "Test Story",
            "article_count": 3,
            "articles": [
                {"title": "Article 1", "source": "Source A", "text": "Text 1"},
                {"title": "Article 2", "source": "Source B", "text": "Text 2"},
                {"title": "Article 3", "source": "Source C", "text": "Text 3"},
            ],
        }

        with patch("jaybrain.signalforge._get_anthropic_client", return_value=mock_client):
            result = _synthesize_cluster(cluster_data)
            assert result["text"] == "Synthesized summary of the cluster."
            assert result["input_tokens"] == 200
            assert result["output_tokens"] == 80
            assert result["cluster_id"] == "c1"
            assert result["label"] == "Test Story"

    def test_api_failure_returns_error(self, temp_data_dir):
        from jaybrain.signalforge import _synthesize_cluster

        cluster_data = {
            "cluster_id": "c1",
            "label": "Test",
            "article_count": 1,
            "articles": [{"title": "A", "source": "S", "text": "T"}],
        }

        with patch("jaybrain.signalforge._get_anthropic_client", side_effect=RuntimeError("No key")):
            result = _synthesize_cluster(cluster_data)
            assert "error" in result
            assert result["cluster_id"] == "c1"


class TestCombineStories:
    def test_combines_summaries(self, temp_data_dir):
        from jaybrain.signalforge import _combine_stories

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            text="# Daily Briefing Title\n\nExecutive summary here.\n\n**Story 1**\nDetails.",
            input_tokens=300, output_tokens=150,
        )

        stories = [
            {"text": "Summary 1", "label": "Story A", "cluster_id": "c1"},
            {"text": "Summary 2", "label": "Story B", "cluster_id": "c2"},
        ]

        with patch("jaybrain.signalforge._get_anthropic_client", return_value=mock_client):
            result = _combine_stories(stories, "2026-02-28")
            assert result["title"] == "Daily Briefing Title"
            assert "Executive summary" in result["text"]
            assert result["input_tokens"] == 300
            assert result["output_tokens"] == 150


class TestRunSynthesis:
    def _setup_clusters(self, temp_data_dir):
        """Set up clusters with articles above significance threshold."""
        conn = _setup_db(temp_data_dir)
        vecs = _make_similar_vectors(4)
        for i in range(4):
            kid = f"synth_kid_{i}"
            _insert_knowledge_row(conn, kid, title=f"Synth Article {i}", embedding=vecs[i])
            _insert_news_feed_article(conn, kid, url=f"https://ex.com/s{i}", source_id="src_synth")
            insert_signalforge_article(conn, f"sf_synth_{i}", kid)
            update_signalforge_article(conn, f"sf_synth_{i}", fetch_status="fetched")

        # Create cluster with significance > 2.0
        insert_signalforge_cluster(conn, "synth_c1", "Big Story",
                                   article_count=4, source_count=3,
                                   avg_similarity=0.9, significance=10.8)
        for i in range(4):
            insert_cluster_article(conn, "synth_c1", f"synth_kid_{i}")
        conn.close()

    def test_happy_path(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_synthesis

        self._setup_clusters(temp_data_dir)

        mock_client = MagicMock()
        # Phase 1 response (cluster synthesis)
        phase1_resp = _mock_anthropic_response(
            text="Cluster summary paragraph.", input_tokens=200, output_tokens=80,
        )
        # Phase 2 response (combine)
        phase2_resp = _mock_anthropic_response(
            text="# Cyber Daily\n\nExecutive summary.\n\n**Big Story**\nDetails here.",
            input_tokens=300, output_tokens=150,
        )
        mock_client.messages.create.side_effect = [phase1_resp, phase2_resp]

        with patch("jaybrain.signalforge._get_anthropic_client", return_value=mock_client):
            with patch("jaybrain.gdocs.create_google_doc", side_effect=Exception("no gdocs")):
                result = run_signalforge_synthesis()

        assert result["status"] == "synthesized"
        assert result["title"] == "Cyber Daily"
        assert result["cluster_count"] == 1
        assert result["word_count"] > 0
        assert result["input_tokens"] == 500  # 200 + 300
        assert result["output_tokens"] == 230  # 80 + 150

        # Verify stored in DB
        conn = get_connection()
        row = get_signalforge_synthesis_by_date(conn, result["synthesis_date"])
        conn.close()
        assert row is not None
        assert row["title"] == "Cyber Daily"

    def test_already_exists(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_synthesis

        self._setup_clusters(temp_data_dir)

        # Insert today's synthesis
        conn = get_connection()
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        insert_signalforge_synthesis(
            conn, "existing_id", today, "Existing Title", "Content",
            "[]", 1, 3, 100, "model", 50, 25,
        )
        conn.close()

        result = run_signalforge_synthesis()
        assert result["status"] == "already_exists"
        assert result["title"] == "Existing Title"

    def test_force_resynthesizes(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_synthesis

        self._setup_clusters(temp_data_dir)

        # Insert today's synthesis
        conn = get_connection()
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        insert_signalforge_synthesis(
            conn, "old_id", today, "Old Title", "Old Content",
            "[]", 1, 3, 100, "model", 50, 25,
        )
        conn.close()

        mock_client = MagicMock()
        phase1_resp = _mock_anthropic_response(text="New summary.", input_tokens=100, output_tokens=50)
        phase2_resp = _mock_anthropic_response(
            text="# New Title\n\nNew content.", input_tokens=200, output_tokens=100,
        )
        mock_client.messages.create.side_effect = [phase1_resp, phase2_resp]

        with patch("jaybrain.signalforge._get_anthropic_client", return_value=mock_client):
            with patch("jaybrain.gdocs.create_google_doc", side_effect=Exception("no gdocs")):
                result = run_signalforge_synthesis(force=True)

        assert result["status"] == "synthesized"
        assert result["title"] == "New Title"

        # Old one should be gone
        conn = get_connection()
        old = get_signalforge_synthesis(conn, "old_id")
        conn.close()
        assert old is None

    def test_no_clusters_above_threshold(self, temp_data_dir):
        from jaybrain.signalforge import run_signalforge_synthesis

        conn = _setup_db(temp_data_dir)
        # Create cluster with low significance
        insert_signalforge_cluster(conn, "low_c1", "Small Story",
                                   article_count=2, source_count=1,
                                   avg_similarity=0.8, significance=1.0)
        conn.close()

        result = run_signalforge_synthesis()
        assert result["status"] == "no_clusters"


class TestSynthesisStatus:
    def test_empty_state(self, temp_data_dir):
        from jaybrain.signalforge import get_synthesis_status

        _setup_db(temp_data_dir)
        status = get_synthesis_status()
        assert status["today"]["synthesized"] is False
        assert status["today"]["title"] is None
        assert status["recent_syntheses"] == []
        assert status["token_usage"]["total_syntheses"] == 0

    def test_with_data(self, temp_data_dir):
        from jaybrain.signalforge import get_synthesis_status

        conn = _setup_db(temp_data_dir)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        insert_signalforge_synthesis(
            conn, "status_id", today, "Today's Briefing", "Content here",
            '["c1"]', 1, 5, 250, "claude-sonnet", 400, 200,
        )
        conn.close()

        status = get_synthesis_status()
        assert status["today"]["synthesized"] is True
        assert status["today"]["title"] == "Today's Briefing"
        assert status["today"]["word_count"] == 250
        assert len(status["recent_syntheses"]) == 1
        assert status["token_usage"]["total_input_tokens"] == 400
        assert status["token_usage"]["total_output_tokens"] == 200


class TestSynthesisDb:
    def test_insert_and_get(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_synthesis(
            conn, "db_id1", "2026-02-28", "Test Title", "Test content",
            '["c1", "c2"]', 2, 8, 300, "claude-sonnet", 500, 250,
            gdoc_id="doc123", gdoc_url="https://docs.google.com/doc123",
        )
        row = get_signalforge_synthesis(conn, "db_id1")
        conn.close()

        assert row is not None
        assert row["title"] == "Test Title"
        assert row["synthesis_date"] == "2026-02-28"
        assert row["cluster_count"] == 2
        assert row["gdoc_id"] == "doc123"

    def test_unique_date_constraint(self, temp_data_dir):
        import sqlite3 as _sqlite3
        conn = _setup_db(temp_data_dir)
        insert_signalforge_synthesis(
            conn, "dup_id1", "2026-02-28", "First", "Content",
            "[]", 1, 3, 100, "model", 50, 25,
        )
        with pytest.raises(_sqlite3.IntegrityError):
            insert_signalforge_synthesis(
                conn, "dup_id2", "2026-02-28", "Second", "Content",
                "[]", 1, 3, 100, "model", 50, 25,
            )
        conn.close()

    def test_get_by_date(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_synthesis(
            conn, "date_id", "2026-03-01", "March Title", "Content",
            "[]", 1, 3, 100, "model", 50, 25,
        )
        row = get_signalforge_synthesis_by_date(conn, "2026-03-01")
        assert row is not None
        assert row["title"] == "March Title"

        missing = get_signalforge_synthesis_by_date(conn, "2026-01-01")
        assert missing is None
        conn.close()

    def test_list_ordered_desc(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        for day in ["2026-02-25", "2026-02-27", "2026-02-26"]:
            insert_signalforge_synthesis(
                conn, f"list_{day}", day, f"Title {day}", "Content",
                "[]", 1, 3, 100, "model", 50, 25,
            )
        rows = list_signalforge_syntheses(conn, limit=10)
        conn.close()

        dates = [r["synthesis_date"] for r in rows]
        assert dates == ["2026-02-27", "2026-02-26", "2026-02-25"]

    def test_update(self, temp_data_dir):
        conn = _setup_db(temp_data_dir)
        insert_signalforge_synthesis(
            conn, "upd_id", "2026-02-28", "Original", "Content",
            "[]", 1, 3, 100, "model", 50, 25,
        )
        result = update_signalforge_synthesis(conn, "upd_id", title="Updated Title", gdoc_id="new_doc")
        assert result is True
        row = get_signalforge_synthesis(conn, "upd_id")
        assert row["title"] == "Updated Title"
        assert row["gdoc_id"] == "new_doc"
        conn.close()
