"""Tests for the enhanced scraping module."""

import pytest

from jaybrain.scraping import (
    should_render,
    extract_clean_text,
    extract_metadata,
    discover_next_page,
)


# --- SPA Detection ---

class TestShouldRender:
    def test_static_html_no_render(self):
        html = """<html><body>
        <h1>Job Listings</h1>
        <p>We have many great jobs available. Here are the latest openings
        at our company. Browse through and find your perfect role today.
        Each position offers competitive pay and benefits.</p>
        <div class="job">Software Engineer - Remote</div>
        <div class="job">Data Analyst - NYC</div>
        </body></html>"""
        assert should_render(html) is False

    def test_nextjs_spa_shell(self):
        html = """<html><body>
        <div id="__next"></div>
        <script src="/static/chunks/main.js"></script>
        <script src="/static/chunks/pages/_app.js"></script>
        </body></html>"""
        assert should_render(html) is True

    def test_react_spa_shell(self):
        html = """<html><body>
        <div id="root" data-reactroot></div>
        <script src="/bundle.js"></script>
        <script src="/vendor.js"></script>
        </body></html>"""
        assert should_render(html) is True

    def test_angular_spa_shell(self):
        html = """<html><body>
        <app-root ng-version="17.0.0"></app-root>
        <script src="/main.js"></script>
        </body></html>"""
        assert should_render(html) is True

    def test_many_scripts_little_text(self):
        scripts = '<script src="/chunk{}.js"></script>' * 8
        html = f"<html><body><div>Loading</div>{scripts}</body></html>"
        assert should_render(html) is True

    def test_enough_text_not_spa(self):
        # Plenty of text content, even with scripts
        text = "This is a real job listing page with lots of content. " * 20
        html = f"""<html><body>
        <h1>Jobs</h1>
        <p>{text}</p>
        <script src="/analytics.js"></script>
        </body></html>"""
        assert should_render(html) is False


# --- Text Extraction ---

class TestExtractCleanText:
    def test_strips_scripts_and_styles(self):
        html = """<html><head><style>body{color:red}</style></head>
        <body><script>alert('hi')</script><p>Real content</p></body></html>"""
        text = extract_clean_text(html)
        assert "Real content" in text
        assert "alert" not in text
        assert "color:red" not in text

    def test_strips_nav_footer(self):
        html = """<html><body>
        <nav>Home | About | Contact</nav>
        <main><p>Job: Security Analyst at Acme</p></main>
        <footer>Copyright 2026</footer>
        </body></html>"""
        text = extract_clean_text(html)
        assert "Security Analyst" in text
        assert "Home | About" not in text
        assert "Copyright" not in text

    def test_strips_hidden_elements(self):
        html = """<html><body>
        <p>Visible content</p>
        <div style="display: none">Hidden stuff</div>
        <span aria-hidden="true">Screen reader hidden</span>
        <div hidden>Also hidden</div>
        </body></html>"""
        text = extract_clean_text(html)
        assert "Visible content" in text
        assert "Hidden stuff" not in text
        assert "Screen reader hidden" not in text
        assert "Also hidden" not in text

    def test_collapses_whitespace(self):
        html = "<html><body><p>Line 1</p><p></p><p></p><p></p><p></p><p>Line 2</p></body></html>"
        text = extract_clean_text(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in text
        assert "Line 1" in text
        assert "Line 2" in text

    def test_strips_iframes_and_forms(self):
        html = """<html><body>
        <p>Job listing here</p>
        <iframe src="https://ads.example.com"></iframe>
        <form action="/apply"><input type="text"></form>
        </body></html>"""
        text = extract_clean_text(html)
        assert "Job listing" in text
        assert "ads.example" not in text


# --- Metadata Extraction ---

class TestExtractMetadata:
    def test_extracts_title(self):
        html = "<html><head><title>SOC Analyst Jobs | SecBoard</title></head><body></body></html>"
        meta = extract_metadata(html, "https://example.com")
        assert meta["title"] == "SOC Analyst Jobs | SecBoard"

    def test_extracts_description(self):
        html = '<html><head><meta name="description" content="Find security jobs"></head><body></body></html>'
        meta = extract_metadata(html, "https://example.com")
        assert meta["description"] == "Find security jobs"

    def test_extracts_opengraph(self):
        html = """<html><head>
        <meta property="og:title" content="Remote Security Jobs">
        <meta property="og:description" content="Top remote security positions">
        <meta property="og:type" content="website">
        </head><body></body></html>"""
        meta = extract_metadata(html, "https://example.com")
        assert meta["opengraph"]["title"] == "Remote Security Jobs"
        assert meta["opengraph"]["type"] == "website"

    def test_extracts_canonical(self):
        html = '<html><head><link rel="canonical" href="https://example.com/jobs"></head><body></body></html>'
        meta = extract_metadata(html, "https://example.com")
        assert meta["canonical"] == "https://example.com/jobs"

    def test_extracts_json_ld(self):
        html = """<html><head>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Security Engineer", "hiringOrganization": {"name": "Acme"}}
        </script>
        </head><body></body></html>"""
        meta = extract_metadata(html, "https://example.com")
        assert len(meta["json_ld"]) == 1
        assert meta["json_ld"][0]["@type"] == "JobPosting"
        assert meta["json_ld"][0]["title"] == "Security Engineer"

    def test_handles_malformed_json_ld(self):
        html = """<html><head>
        <script type="application/ld+json">not valid json{</script>
        </head><body></body></html>"""
        meta = extract_metadata(html, "https://example.com")
        assert "json_ld" not in meta

    def test_empty_page(self):
        meta = extract_metadata("<html><body></body></html>", "https://example.com")
        assert "title" not in meta
        assert "description" not in meta


# --- Pagination Discovery ---

class TestDiscoverNextPage:
    def test_link_rel_next(self):
        html = """<html><head>
        <link rel="next" href="/jobs?page=2">
        </head><body></body></html>"""
        result = discover_next_page(html, "https://example.com/jobs")
        assert result == "https://example.com/jobs?page=2"

    def test_anchor_with_next_text(self):
        html = """<html><body>
        <a href="/jobs?page=1">1</a>
        <a href="/jobs?page=2">Next</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs")
        assert result == "https://example.com/jobs?page=2"

    def test_anchor_with_next_page_text(self):
        html = """<html><body>
        <a href="/careers?p=3">Next Page</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/careers?p=2")
        assert result == "https://example.com/careers?p=3"

    def test_anchor_with_aria_label(self):
        html = """<html><body>
        <a href="/jobs/2" aria-label="Next page">&gt;</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs/1")
        assert result == "https://example.com/jobs/2"

    def test_anchor_with_chevron(self):
        html = """<html><body>
        <a href="/search?page=4">\u00bb</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/search?page=3")
        assert result == "https://example.com/search?page=4"

    def test_no_pagination(self):
        html = """<html><body>
        <a href="/about">About</a>
        <a href="/contact">Contact</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs")
        assert result is None

    def test_rejects_cross_domain(self):
        html = """<html><body>
        <a href="https://other-site.com/jobs?page=2">Next</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs")
        assert result is None

    def test_rejects_self_link(self):
        html = """<html><body>
        <a href="/jobs?page=1">Next</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs?page=1")
        assert result is None

    def test_resolves_relative_urls(self):
        html = """<html><body>
        <a href="?page=2">Next</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs?page=1")
        assert result == "https://example.com/jobs?page=2"

    def test_more_jobs_text(self):
        html = """<html><body>
        <a href="/jobs?offset=20">More Jobs</a>
        </body></html>"""
        result = discover_next_page(html, "https://example.com/jobs")
        assert result == "https://example.com/jobs?offset=20"
