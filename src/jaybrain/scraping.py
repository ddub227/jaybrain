"""Enhanced web scraping with SPA detection and optional Playwright rendering.

Inspired by ddub227/web-scraper patterns: SPA heuristic detection,
structured metadata extraction, pagination discovery, and graceful
Playwright fallback for JS-rendered pages.

Playwright is optional -- install with: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .config import SCRAPE_TIMEOUT, SCRAPE_USER_AGENT, SCRAPE_MAX_PAGES, validate_url

logger = logging.getLogger(__name__)

# Markers that suggest a page is an SPA shell requiring JS rendering
_SPA_MARKERS = [
    'id="__next"',       # Next.js
    "data-reactroot",    # React
    'id="app"',          # Vue
    'id="root"',         # React (common)
    "ng-version",        # Angular
    "data-turbo",        # Hotwire/Turbo
    "ember-view",        # Ember
]


def should_render(html: str) -> bool:
    """Detect whether a page is a JS-rendered SPA shell that needs Playwright.

    Checks text density, script-to-content ratio, and known SPA framework
    markers. Adapted from ddub227/web-scraper's should_render_heuristic().
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strip scripts/styles for text measurement
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    visible_text = soup.get_text(strip=True)
    text_len = len(visible_text)

    # Very little visible text is a strong SPA signal
    if text_len < 200:
        # Check for SPA framework markers in the raw HTML
        html_lower = html.lower()
        for marker in _SPA_MARKERS:
            if marker.lower() in html_lower:
                logger.info("SPA detected: low text (%d chars) + marker '%s'", text_len, marker)
                return True

    # High script-to-text ratio
    script_count = html.lower().count("<script")
    if script_count > 5 and text_len < 500:
        logger.info("SPA detected: %d scripts, only %d chars of text", script_count, text_len)
        return True

    return False


def extract_clean_text(html: str) -> str:
    """Extract meaningful text content from HTML.

    Removes boilerplate (scripts, styles, nav, footer, etc.), extracts
    visible text, and collapses excessive whitespace. Based on
    ddub227/web-scraper's extract_text_content() pattern.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove boilerplate elements
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    # Also remove hidden elements
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        if isinstance(tag, Tag):
            tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        if isinstance(tag, Tag):
            tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none")):
        if isinstance(tag, Tag):
            tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of whitespace within lines
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def extract_metadata(html: str, url: str) -> dict:
    """Extract page metadata: title, description, OG tags, JSON-LD.

    Adapted from ddub227/web-scraper's extract_metadata() and
    extract_structured_data() patterns.
    """
    soup = BeautifulSoup(html, "html.parser")
    meta = {}

    # Title
    title_tag = soup.find("title")
    if title_tag:
        meta["title"] = title_tag.get_text(strip=True)

    # Meta description
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and desc_tag.get("content"):
        meta["description"] = desc_tag["content"]

    # OpenGraph tags
    og_fields = {}
    for og_tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
        key = og_tag.get("property", "").replace("og:", "")
        value = og_tag.get("content", "")
        if key and value:
            og_fields[key] = value
    if og_fields:
        meta["opengraph"] = og_fields

    # Canonical URL
    canonical = soup.find("link", attrs={"rel": "canonical"})
    if canonical and canonical.get("href"):
        meta["canonical"] = canonical["href"]

    # JSON-LD structured data
    json_ld = []
    import json
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            json_ld.append(data)
        except (json.JSONDecodeError, TypeError):
            pass
    if json_ld:
        meta["json_ld"] = json_ld

    return meta


def discover_next_page(html: str, current_url: str) -> Optional[str]:
    """Discover the next page URL for pagination.

    Checks <link rel="next"> and anchor elements with pagination
    keywords. Adapted from ddub227/web-scraper's
    extract_pagination_next_links() pattern.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(current_url).netloc

    # Check <link rel="next"> first (most reliable)
    link_next = soup.find("link", attrs={"rel": "next"})
    if link_next and link_next.get("href"):
        href = urljoin(current_url, link_next["href"])
        if urlparse(href).netloc == base_domain:
            return href

    # Check anchors with pagination keywords
    pagination_patterns = re.compile(
        r"(next|older|more\s+jobs|next\s+page|load\s+more|\u203a|\u00bb|>>)",
        re.IGNORECASE,
    )
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        rel = " ".join(a.get("rel", []))
        aria = a.get("aria-label", "")
        if pagination_patterns.search(text) or \
           pagination_patterns.search(rel) or \
           pagination_patterns.search(aria):
            href = urljoin(current_url, a["href"])
            # Must stay on same domain
            if urlparse(href).netloc == base_domain and href != current_url:
                return href

    return None


def fetch_page(url: str, render: str = "auto") -> dict:
    """Fetch a single page and return raw HTML + status info.

    render modes:
        "auto"   -- fetch plain first, use Playwright if SPA detected
        "always" -- always use Playwright
        "never"  -- plain HTTP only

    Returns dict with keys: html, url, rendered (bool), status_code.
    """
    import requests

    validate_url(url)

    headers = {"User-Agent": SCRAPE_USER_AGENT}
    rendered = False

    if render == "always":
        html = _render_with_playwright(url)
        if html is not None:
            return {"html": html, "url": url, "rendered": True, "status_code": 200}
        # Playwright unavailable, fall through to plain fetch
        logger.warning("Playwright unavailable, falling back to plain HTTP for %s", url)

    # Plain HTTP fetch
    response = requests.get(url, timeout=SCRAPE_TIMEOUT, headers=headers)
    response.raise_for_status()
    html = response.text
    status_code = response.status_code

    # Auto-detect SPA and re-render if needed
    if render == "auto" and should_render(html):
        logger.info("SPA detected for %s, attempting Playwright render", url)
        rendered_html = _render_with_playwright(url)
        if rendered_html is not None:
            html = rendered_html
            rendered = True

    return {
        "html": html,
        "url": url,
        "rendered": rendered,
        "status_code": status_code,
    }


def fetch_pages(
    url: str,
    max_pages: int = 0,
    render: str = "auto",
) -> list[dict]:
    """Fetch a URL and follow pagination up to max_pages.

    max_pages=0 means use the SCRAPE_MAX_PAGES config default.
    Returns a list of page results, each with text, metadata, and page_url.
    """
    if max_pages <= 0:
        max_pages = SCRAPE_MAX_PAGES

    pages = []
    current_url = url
    visited = set()

    for page_num in range(1, max_pages + 1):
        if current_url in visited:
            break
        visited.add(current_url)

        try:
            result = fetch_page(current_url, render=render)
        except Exception as e:
            logger.error("Failed to fetch page %d (%s): %s", page_num, current_url, e)
            break

        html = result["html"]
        text = extract_clean_text(html)
        metadata = extract_metadata(html, current_url)

        pages.append({
            "page_num": page_num,
            "page_url": current_url,
            "rendered": result["rendered"],
            "text": text,
            "text_length": len(text),
            "metadata": metadata,
        })

        # Try to find next page
        next_url = discover_next_page(html, current_url)
        if not next_url:
            break
        current_url = next_url

    return pages


def _render_with_playwright(url: str) -> Optional[str]:
    """Render a page with Playwright (Chromium). Returns HTML or None if unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright not installed -- skip JS rendering")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=SCRAPE_USER_AGENT,
                )
                page.goto(url, timeout=SCRAPE_TIMEOUT * 1000, wait_until="networkidle")
                html = page.content()
                return html
            finally:
                browser.close()
    except Exception as e:
        logger.warning("Playwright rendering failed for %s: %s", url, e)
        return None
