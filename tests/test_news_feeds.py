"""Tests for the news_feeds module (parse, dedup, poll, source CRUD)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import NEWS_FEED_MAX_ITEMS_PER_SOURCE, ensure_data_dirs
from jaybrain.db import get_connection, init_db


def _setup_db(temp_data_dir):
    ensure_data_dirs()
    init_db()


# Mock embedding to avoid loading the ONNX model during tests
FAKE_EMBEDDING = [0.1] * 384


@pytest.fixture(autouse=True)
def mock_embed():
    with patch("jaybrain.knowledge.embed_text", return_value=FAKE_EMBEDDING):
        yield


# ---- Inline fixtures ----

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Test RSS</title>
    <item>
      <guid>urn:test:article-1</guid>
      <title>Claude Code Gets MCP Support</title>
      <link>https://example.com/article-1</link>
      <pubDate>Fri, 28 Feb 2026 12:00:00 GMT</pubDate>
      <description>&lt;p&gt;Short teaser.&lt;/p&gt;</description>
      <dc:creator>Alice Tester</dc:creator>
      <source url="https://example.com">Example News</source>
      <category>AI</category>
      <category>Tools</category>
    </item>
    <item>
      <guid>urn:test:article-2</guid>
      <title>Anthropic Raises Series D</title>
      <link>https://example.com/article-2</link>
      <description>Funding round details.</description>
    </item>
  </channel>
</rss>"""

SAMPLE_RSS_WITH_CONTENT_ENCODED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <item>
      <guid>urn:wp:post-1</guid>
      <title>WP Post</title>
      <link>https://blog.example.com/post-1</link>
      <description>Excerpt</description>
      <content:encoded><![CDATA[<p>Full <b>rich</b> content here.</p>]]></content:encoded>
    </item>
  </channel>
</rss>"""

SAMPLE_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom</title>
  <entry>
    <id>tag:github.com,2026:release-v1.0</id>
    <title>v1.0 Release</title>
    <link rel="alternate" href="https://github.com/test/repo/releases/v1.0" />
    <published>2026-02-28T10:00:00Z</published>
    <content type="html">&lt;p&gt;Release notes here.&lt;/p&gt;</content>
    <author><name>Releaser Bot</name></author>
    <category term="release" />
  </entry>
  <entry>
    <id>tag:reddit,2026:post-abc</id>
    <title>Discussion about Claude</title>
    <link rel="alternate" href="https://reddit.com/r/ClaudeAI/abc" />
    <updated>2026-02-27T08:00:00Z</updated>
    <summary>People are discussing...</summary>
  </entry>
</feed>"""

SAMPLE_HN_JSON = {
    "hits": [
        {
            "objectID": "42000001",
            "title": "Show HN: Claude Code CLI",
            "url": "https://blog.anthropic.com/claude-code",
            "points": 234,
            "num_comments": 89,
            "author": "hnuser1",
            "created_at": "2026-02-28T09:15:00.000Z",
            "story_text": "",
        },
        {
            "objectID": "42000002",
            "title": "Ask HN: Anyone using Claude Code?",
            "url": "",
            "points": 45,
            "num_comments": 32,
            "author": "hnuser2",
            "created_at": "2026-02-27T14:00:00.000Z",
            "story_text": "<p>Self-post text about using it.</p>",
        },
    ]
}


# =============================================================================
# Parser Tests
# =============================================================================


class TestParseRss:
    def test_basic_rss(self):
        from jaybrain.news_feeds import _parse_rss

        articles = _parse_rss(SAMPLE_RSS)
        assert len(articles) == 2

        a1 = articles[0]
        assert a1["source_article_id"] == "urn:test:article-1"
        assert a1["title"] == "Claude Code Gets MCP Support"
        assert a1["url"] == "https://example.com/article-1"
        assert a1["author"] == "Alice Tester"
        assert a1["publisher"] == "Example News"
        assert "ai" in a1["extra_tags"]
        assert "tools" in a1["extra_tags"]
        assert a1["published_at"] is not None

    def test_summary_strips_html(self):
        from jaybrain.news_feeds import _parse_rss

        articles = _parse_rss(SAMPLE_RSS)
        assert "<p>" not in articles[0]["summary"]
        assert "Short teaser." in articles[0]["summary"]

    def test_content_encoded_preferred(self):
        from jaybrain.news_feeds import _parse_rss

        articles = _parse_rss(SAMPLE_RSS_WITH_CONTENT_ENCODED)
        assert len(articles) == 1
        assert "Full" in articles[0]["summary"]
        assert "rich" in articles[0]["summary"]
        assert "<b>" not in articles[0]["summary"]

    def test_empty_rss(self):
        from jaybrain.news_feeds import _parse_rss

        xml = '<?xml version="1.0"?><rss><channel></channel></rss>'
        articles = _parse_rss(xml)
        assert articles == []

    def test_item_without_guid_uses_link(self):
        from jaybrain.news_feeds import _parse_rss

        xml = """\
<?xml version="1.0"?>
<rss><channel><item>
  <title>No GUID</title>
  <link>https://example.com/no-guid</link>
</item></channel></rss>"""
        articles = _parse_rss(xml)
        assert len(articles) == 1
        assert articles[0]["source_article_id"] == "https://example.com/no-guid"


class TestParseAtom:
    def test_basic_atom(self):
        from jaybrain.news_feeds import _parse_atom

        articles = _parse_atom(SAMPLE_ATOM)
        assert len(articles) == 2

        a1 = articles[0]
        assert a1["source_article_id"] == "tag:github.com,2026:release-v1.0"
        assert a1["title"] == "v1.0 Release"
        assert a1["url"] == "https://github.com/test/repo/releases/v1.0"
        assert a1["author"] == "Releaser Bot"
        assert "release" in a1["extra_tags"]
        assert a1["published_at"] == "2026-02-28T10:00:00Z"

    def test_content_strips_html(self):
        from jaybrain.news_feeds import _parse_atom

        articles = _parse_atom(SAMPLE_ATOM)
        assert "<p>" not in articles[0]["summary"]
        assert "Release notes here." in articles[0]["summary"]

    def test_falls_back_to_updated_date(self):
        from jaybrain.news_feeds import _parse_atom

        articles = _parse_atom(SAMPLE_ATOM)
        a2 = articles[1]
        assert a2["published_at"] == "2026-02-27T08:00:00Z"

    def test_empty_atom(self):
        from jaybrain.news_feeds import _parse_atom

        xml = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        articles = _parse_atom(xml)
        assert articles == []


class TestParseJsonApi:
    def test_basic_hn(self):
        from jaybrain.news_feeds import _parse_json_api

        articles = _parse_json_api(SAMPLE_HN_JSON)
        assert len(articles) == 2

        a1 = articles[0]
        assert a1["source_article_id"] == "42000001"
        assert a1["title"] == "Show HN: Claude Code CLI"
        assert a1["url"] == "https://blog.anthropic.com/claude-code"
        assert a1["author"] == "hnuser1"
        assert a1["publisher"] == "Hacker News"
        assert "234 points" in a1["summary"]
        assert "89 comments" in a1["summary"]

    def test_self_post_uses_hn_url(self):
        from jaybrain.news_feeds import _parse_json_api

        articles = _parse_json_api(SAMPLE_HN_JSON)
        a2 = articles[1]
        assert "news.ycombinator.com/item?id=42000002" in a2["url"]

    def test_self_post_includes_text(self):
        from jaybrain.news_feeds import _parse_json_api

        articles = _parse_json_api(SAMPLE_HN_JSON)
        a2 = articles[1]
        assert "Self-post text" in a2["summary"]
        assert "<p>" not in a2["summary"]

    def test_empty_hn(self):
        from jaybrain.news_feeds import _parse_json_api

        articles = _parse_json_api({"hits": []})
        assert articles == []


# =============================================================================
# Max Items Cap Test
# =============================================================================


class TestMaxItemsCap:
    def test_rss_caps_at_max(self):
        from jaybrain.news_feeds import _parse_rss

        items = "\n".join(
            f'<item><guid>id-{i}</guid><title>Art {i}</title>'
            f'<link>https://ex.com/{i}</link></item>'
            for i in range(200)
        )
        xml = f'<?xml version="1.0"?><rss><channel>{items}</channel></rss>'
        articles = _parse_rss(xml)
        assert len(articles) == NEWS_FEED_MAX_ITEMS_PER_SOURCE


# =============================================================================
# Dedup Tests
# =============================================================================


class TestDedup:
    def _insert_source(self, conn, source_id):
        """Insert a minimal source row so FK constraints pass."""
        from jaybrain.db import insert_news_feed_source
        insert_news_feed_source(conn, source_id, f"Source {source_id}", "https://ex.com", "rss", [])

    def test_per_source_dedup(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _is_seen, _mark_seen

        conn = get_connection()
        try:
            self._insert_source(conn, "src1")
            self._insert_source(conn, "src2")
            assert not _is_seen(conn, "src1", "art1")
            _mark_seen(conn, "src1", "art1", "k1", "Test", "https://ex.com/1", None)
            assert _is_seen(conn, "src1", "art1")
            assert not _is_seen(conn, "src2", "art1")
        finally:
            conn.close()

    def test_cross_source_url_dedup(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _is_url_seen, _mark_seen

        conn = get_connection()
        try:
            self._insert_source(conn, "src1")
            _mark_seen(
                conn, "src1", "art1", "k1", "Test",
                "https://example.com/article-1", None,
            )
            assert _is_url_seen(conn, "https://example.com/article-1")
            assert not _is_url_seen(conn, "https://example.com/other")
        finally:
            conn.close()

    def test_google_news_url_skipped(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _is_url_seen

        conn = get_connection()
        try:
            assert not _is_url_seen(conn, "https://news.google.com/rss/redirect/abc")
        finally:
            conn.close()

    def test_empty_url_skipped(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _is_url_seen

        conn = get_connection()
        try:
            assert not _is_url_seen(conn, "")
        finally:
            conn.close()


# =============================================================================
# Source CRUD Tests
# =============================================================================


class TestSourceCRUD:
    def test_add_source(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import add_source

        s = add_source("Test Feed", "https://example.com/rss", "rss", ["test"])
        assert s["name"] == "Test Feed"
        assert s["url"] == "https://example.com/rss"
        assert s["source_type"] == "rss"
        assert s["tags"] == ["test"]
        assert s["active"] is True
        assert len(s["id"]) == 12

    def test_remove_source(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import add_source, remove_source

        s = add_source("Removable", "https://example.com/rss")
        assert remove_source(s["id"]) is True
        assert remove_source(s["id"]) is False

    def test_invalid_source_type(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import add_source

        with pytest.raises(ValueError, match="Invalid source_type"):
            add_source("Bad", "https://ex.com", "ftp")

    def test_get_sources_seeds_defaults(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import get_sources, _DEFAULT_SOURCES

        sources = get_sources(active_only=True)
        assert len(sources) == len(_DEFAULT_SOURCES)

    def test_get_sources_doesnt_reseed(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import get_sources, _DEFAULT_SOURCES

        sources1 = get_sources()
        sources2 = get_sources()
        assert len(sources1) == len(sources2) == len(_DEFAULT_SOURCES)

    def test_active_only_filter(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import add_source, get_sources
        from jaybrain.db import update_news_feed_source

        s = add_source("Inactive", "https://example.com/rss")
        conn = get_connection()
        update_news_feed_source(conn, s["id"], active=0)
        conn.close()

        active = get_sources(active_only=True)
        all_sources = get_sources(active_only=False)
        # Inactive source should appear in all but not active
        active_ids = {s["id"] for s in active}
        all_ids = {s["id"] for s in all_sources}
        assert s["id"] not in active_ids
        assert s["id"] in all_ids


# =============================================================================
# Poll Tests
# =============================================================================


def _make_source_row(source_id="src1", name="Test Source", url="https://example.com/rss",
                     source_type="rss", tags="[]", active=1, articles_total=0):
    """Build a fake source row dict that looks like a sqlite3.Row."""
    return {
        "id": source_id,
        "name": name,
        "url": url,
        "source_type": source_type,
        "tags": tags,
        "active": active,
        "last_polled": None,
        "last_error": "",
        "articles_total": articles_total,
        "created_at": "2026-02-28T00:00:00",
        "updated_at": "2026-02-28T00:00:00",
    }


class TestPollSingle:
    def test_stores_to_knowledge(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _poll_single
        from jaybrain.db import insert_news_feed_source

        source_row = _make_source_row()
        conn = get_connection()
        insert_news_feed_source(conn, "src1", "Test Source", "https://example.com/rss", "rss", [])

        with patch("jaybrain.news_feeds._fetch_source") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "source_article_id": "art-1",
                    "title": "Test Article",
                    "url": "https://example.com/test",
                    "summary": "A test article.",
                    "published_at": "2026-02-28T12:00:00Z",
                    "author": "Test Author",
                    "publisher": "Test Pub",
                    "extra_tags": [],
                }
            ]
            result = _poll_single(conn, source_row)

        assert result["status"] == "ok"
        assert result["new"] == 1
        assert result["fetched"] == 1
        conn.close()

    def test_dedup_skips_seen(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _poll_single, _mark_seen
        from jaybrain.db import insert_news_feed_source

        source_row = _make_source_row()
        conn = get_connection()
        insert_news_feed_source(conn, "src1", "Test Source", "https://example.com/rss", "rss", [])

        _mark_seen(conn, "src1", "art-1", "k1", "Old", "https://ex.com/1", None)

        with patch("jaybrain.news_feeds._fetch_source") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "source_article_id": "art-1",
                    "title": "Same Article",
                    "url": "https://ex.com/1",
                    "summary": "Already seen.",
                    "published_at": None,
                    "author": "",
                    "publisher": "",
                    "extra_tags": [],
                }
            ]
            result = _poll_single(conn, source_row)

        assert result["new"] == 0
        conn.close()

    def test_cross_source_dedup(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _poll_single, _mark_seen
        from jaybrain.db import insert_news_feed_source

        source_row = _make_source_row(source_id="src2", name="Source 2")
        conn = get_connection()
        insert_news_feed_source(conn, "src1", "Source 1", "https://ex.com/1", "rss", [])
        insert_news_feed_source(conn, "src2", "Source 2", "https://ex.com/2", "rss", [])

        # Same URL already stored by a different source
        _mark_seen(conn, "src1", "art-X", "k1", "Orig", "https://shared.com/art", None)

        with patch("jaybrain.news_feeds._fetch_source") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "source_article_id": "art-Y",
                    "title": "Duplicate URL",
                    "url": "https://shared.com/art",
                    "summary": "Cross-source dup.",
                    "published_at": None,
                    "author": "",
                    "publisher": "",
                    "extra_tags": [],
                }
            ]
            result = _poll_single(conn, source_row)

        assert result["new"] == 0
        conn.close()

    def test_http_error_recorded(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _poll_single

        source_row = _make_source_row()
        conn = get_connection()

        # Need to insert the source so update_news_feed_source can find it
        from jaybrain.db import insert_news_feed_source
        insert_news_feed_source(conn, "src1", "Test Source", "https://example.com/rss", "rss", [])

        with patch("jaybrain.news_feeds._fetch_source", side_effect=Exception("Connection refused")):
            result = _poll_single(conn, source_row)

        assert result["status"] == "error"
        assert "Connection refused" in result["error"]
        conn.close()

    def test_updates_article_count(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import _poll_single
        from jaybrain.db import insert_news_feed_source, get_news_feed_source

        conn = get_connection()
        insert_news_feed_source(conn, "src1", "Test", "https://ex.com", "rss", [])

        source_row = _make_source_row()
        with patch("jaybrain.news_feeds._fetch_source") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "source_article_id": f"art-{i}",
                    "title": f"Article {i}",
                    "url": f"https://example.com/{i}",
                    "summary": "Content.",
                    "published_at": None,
                    "author": "",
                    "publisher": "",
                    "extra_tags": [],
                }
                for i in range(3)
            ]
            _poll_single(conn, source_row)

        row = get_news_feed_source(conn, "src1")
        assert row["articles_total"] == 3
        conn.close()


class TestRunPoll:
    def test_polls_all_sources(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import run_news_feed_poll, _DEFAULT_SOURCES

        with patch("jaybrain.news_feeds._fetch_source", return_value=[]):
            with patch("jaybrain.telegram.send_telegram_message"):
                result = run_news_feed_poll()

        assert result["status"] == "ok"
        assert result["sources_polled"] == len(_DEFAULT_SOURCES)

    def test_empty_sources(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import run_news_feed_poll

        # Patch auto-seed so it doesn't populate, leaving table empty
        with patch("jaybrain.news_feeds._ensure_default_sources", return_value=0):
            result = run_news_feed_poll()

        assert result["status"] == "skipped"

    def test_telegram_notification(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import run_news_feed_poll

        articles = [
            {
                "source_article_id": "notif-1",
                "title": "Breaking News",
                "url": "https://example.com/breaking",
                "summary": "Big news.",
                "published_at": None,
                "author": "",
                "publisher": "",
                "extra_tags": [],
            }
        ]

        with patch("jaybrain.news_feeds._fetch_source", return_value=articles):
            with patch("jaybrain.telegram.send_telegram_message") as mock_tg:
                result = run_news_feed_poll()

        assert result["total_new"] > 0
        mock_tg.assert_called_once()
        call_args = mock_tg.call_args
        assert "new article" in call_args[0][0].lower()


# =============================================================================
# Status Tests
# =============================================================================


class TestStatus:
    def test_empty_status(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import get_news_feed_status, _DEFAULT_SOURCES

        status = get_news_feed_status()
        assert len(status["sources"]) == len(_DEFAULT_SOURCES)
        assert status["total_articles"] == 0
        assert status["recent"] == []

    def test_status_after_poll(self, temp_data_dir):
        _setup_db(temp_data_dir)
        from jaybrain.news_feeds import run_news_feed_poll, get_news_feed_status

        articles = [
            {
                "source_article_id": f"status-{i}",
                "title": f"Status Article {i}",
                "url": f"https://example.com/status-{i}",
                "summary": "Content.",
                "published_at": None,
                "author": "",
                "publisher": "",
                "extra_tags": [],
            }
            for i in range(3)
        ]

        with patch("jaybrain.news_feeds._fetch_source", return_value=articles):
            with patch("jaybrain.telegram.send_telegram_message"):
                run_news_feed_poll()

        status = get_news_feed_status()
        assert status["total_articles"] > 0
        assert len(status["recent"]) > 0
        assert status["last_poll"] is not None


# =============================================================================
# Content Builder Tests
# =============================================================================


class TestContentBuilder:
    def test_builds_full_content(self):
        from jaybrain.news_feeds import _build_knowledge_content

        article = {
            "summary": "Article about Claude Code security.",
            "author": "Test Author",
            "publisher": "Tech News",
            "url": "https://example.com/article",
        }
        content = _build_knowledge_content(article, "Google News")
        assert "Article about Claude Code security." in content
        assert "Author: Test Author" in content
        assert "Publisher: Tech News" in content
        assert "URL: https://example.com/article" in content
        assert "Source feed: Google News" in content

    def test_builds_minimal_content(self):
        from jaybrain.news_feeds import _build_knowledge_content

        article = {
            "summary": "",
            "author": "",
            "publisher": "",
            "url": "",
        }
        content = _build_knowledge_content(article, "Test Feed")
        assert "Source feed: Test Feed" in content
        assert "Author:" not in content


# =============================================================================
# HTML Strip Tests
# =============================================================================


class TestStripHtml:
    def test_strips_tags(self):
        from jaybrain.news_feeds import _strip_html

        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        from jaybrain.news_feeds import _strip_html

        assert _strip_html("  too   many    spaces  ") == "too many spaces"

    def test_empty_string(self):
        from jaybrain.news_feeds import _strip_html

        assert _strip_html("") == ""
