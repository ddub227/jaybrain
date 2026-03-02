"""Tests for SignalForge HTTP feed server."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from http.client import HTTPConnection
from unittest.mock import patch

import pytest

from jaybrain.signalforge_feed import (
    FeedHandler,
    build_feed_html,
    collect_feed_data,
    start_feed_server,
    stop_feed_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def feed_db(tmp_path):
    """Create an in-memory-like temp DB with signalforge tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signalforge_clusters (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            article_count INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0,
            avg_similarity REAL NOT NULL DEFAULT 0.0,
            significance REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signalforge_cluster_articles (
            cluster_id TEXT NOT NULL,
            knowledge_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (cluster_id, knowledge_id)
        );
        CREATE TABLE IF NOT EXISTS signalforge_articles (
            id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            resolved_url TEXT NOT NULL DEFAULT '',
            content_path TEXT NOT NULL DEFAULT '',
            word_count INTEGER NOT NULL DEFAULT 0,
            char_count INTEGER NOT NULL DEFAULT 0,
            fetch_status TEXT NOT NULL DEFAULT 'pending',
            fetch_error TEXT NOT NULL DEFAULT '',
            fetched_at TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_cluster(db_path, label="Test Cluster", significance=5.0, n_articles=2):
    """Insert a cluster with N articles into the test DB."""
    conn = sqlite3.connect(str(db_path))
    now = datetime.now(timezone.utc).isoformat()
    cluster_id = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO signalforge_clusters
           (id, label, article_count, source_count, significance, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cluster_id, label, n_articles, 2, significance, now, now),
    )

    for i in range(n_articles):
        kid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO knowledge
               (id, title, content, source, url, category, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'news', '[]', ?, ?)""",
            (
                kid,
                f"Article {i + 1}: {label}",
                f"This is the summary content for article {i + 1}. It has multiple sentences. Very informative.",
                f"source-{i}",
                f"https://example.com/article-{i}",
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO signalforge_cluster_articles
               (cluster_id, knowledge_id, added_at)
               VALUES (?, ?, ?)""",
            (cluster_id, kid, now),
        )

    conn.commit()
    conn.close()
    return cluster_id


# ---------------------------------------------------------------------------
# TestCollectFeedData
# ---------------------------------------------------------------------------


class TestCollectFeedData:
    def test_empty_db(self, feed_db):
        """Empty DB returns empty list."""
        with patch("jaybrain.signalforge_feed.DB_PATH", feed_db):
            result = collect_feed_data()
        assert result == []

    def test_with_clusters(self, feed_db):
        """Clusters with articles return structured dicts."""
        _insert_cluster(feed_db, label="AI Breakthrough", significance=8.0, n_articles=3)
        _insert_cluster(feed_db, label="Security Update", significance=4.0, n_articles=2)

        with patch("jaybrain.signalforge_feed.DB_PATH", feed_db):
            result = collect_feed_data()

        assert len(result) == 2
        # Ordered by significance DESC
        assert result[0]["label"] == "AI Breakthrough"
        assert result[0]["article_count"] == 3
        assert result[0]["source_count"] == 2
        assert result[0]["significance"] == 8.0
        assert len(result[0]["articles"]) == 3
        assert result[0]["preview"]  # should have preview from knowledge.content

        assert result[1]["label"] == "Security Update"
        assert len(result[1]["articles"]) == 2


# ---------------------------------------------------------------------------
# TestBuildFeedHtml
# ---------------------------------------------------------------------------


class TestBuildFeedHtml:
    def test_renders_page(self):
        """HTML contains DOCTYPE, cluster titles, and More buttons."""
        clusters = [
            {
                "id": "c1",
                "label": "Test Story",
                "article_count": 3,
                "source_count": 2,
                "significance": 7.5,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "preview": "This is a preview sentence.",
                "full_text": "Full article text here.",
                "articles": [
                    {"title": "Art 1", "source": "src1", "url": "https://example.com/1"},
                    {"title": "Art 2", "source": "src2", "url": ""},
                ],
            }
        ]
        html = build_feed_html(clusters)
        assert "<!DOCTYPE html>" in html
        assert "Test Story" in html
        assert "More" in html
        assert "3 articles" in html
        assert "2 sources" in html
        assert "sig: 7.5" in html
        assert "Synthesize Now" in html
        assert "Art 1" in html
        assert "https://example.com/1" in html

    def test_empty_clusters(self):
        """Empty list renders page with 'no stories' message."""
        html = build_feed_html([])
        assert "<!DOCTYPE html>" in html
        assert "No stories" in html
        assert "0 clusters" in html


# ---------------------------------------------------------------------------
# TestFeedHandler
# ---------------------------------------------------------------------------


class TestFeedHandler:
    @pytest.fixture(autouse=True)
    def _setup_server(self, feed_db):
        """Start a test server on a random port, stop after test."""
        _insert_cluster(feed_db, label="Live Cluster", significance=6.0)

        with patch("jaybrain.signalforge_feed.DB_PATH", feed_db):
            from http.server import HTTPServer

            server = HTTPServer(("127.0.0.1", 0), FeedHandler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            self.port = port
            self.server = server
            yield

            server.shutdown()
            server.server_close()

    def test_get_root(self, feed_db):
        """GET / returns 200 with HTML content."""
        with patch("jaybrain.signalforge_feed.DB_PATH", feed_db):
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode()
            conn.close()

        assert resp.status == 200
        assert "text/html" in resp.getheader("Content-Type", "")
        assert "<!DOCTYPE html>" in body
        assert "Live Cluster" in body

    def test_post_synthesize(self, feed_db):
        """POST /synthesize returns 302 redirect."""
        # Mock the synthesis import inside do_POST
        mock_synth = patch(
            "jaybrain.signalforge.run_signalforge_synthesis",
            return_value={"status": "synthesized"},
            create=True,
        )
        with patch("jaybrain.signalforge_feed.DB_PATH", feed_db), mock_synth:
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("POST", "/synthesize")
            resp = conn.getresponse()
            resp.read()
            conn.close()

        assert resp.status == 302
        assert resp.getheader("Location") == "/"
