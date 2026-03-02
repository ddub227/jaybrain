"""SignalForge HTTP Feed — lightweight localhost news reader.

Serves a single-page feed of clustered stories at http://localhost:8247/.
Uses only stdlib http.server — zero new dependencies.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .config import DB_PATH, SIGNALFORGE_FEED_PORT

logger = logging.getLogger(__name__)

# Module-level server lifecycle state
_server: HTTPServer | None = None
_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def collect_feed_data(
    max_clusters: int = 15,
    max_age_days: int = 3,
) -> list[dict[str, Any]]:
    """Query DB for recent clusters with their articles and previews."""
    conn = _get_conn()
    try:
        clusters_raw = conn.execute(
            """SELECT id, label, article_count, source_count,
                      significance, created_at
               FROM signalforge_clusters
               WHERE created_at >= datetime('now', ?)
               ORDER BY significance DESC
               LIMIT ?""",
            (f"-{max_age_days} days", max_clusters),
        ).fetchall()

        result: list[dict[str, Any]] = []
        for c in clusters_raw:
            cluster_id = c["id"]
            # Get articles in this cluster
            articles = conn.execute(
                """SELECT k.id AS kid, k.title, k.source, k.url, k.created_at
                   FROM signalforge_cluster_articles ca
                   JOIN knowledge k ON k.id = ca.knowledge_id
                   WHERE ca.cluster_id = ?
                   ORDER BY k.created_at DESC""",
                (cluster_id,),
            ).fetchall()

            # Build preview from lead article's full text
            preview = ""
            full_text = ""
            article_list: list[dict[str, str]] = []
            for art in articles:
                article_list.append({
                    "title": art["title"] or "(untitled)",
                    "source": art["source"] or "",
                    "url": art["url"] or "",
                })
                # Try full text from signalforge_articles
                if not full_text:
                    sf = conn.execute(
                        """SELECT content_path FROM signalforge_articles
                           WHERE knowledge_id = ? AND fetch_status = 'fetched'""",
                        (art["kid"],),
                    ).fetchone()
                    if sf and sf["content_path"]:
                        p = Path(sf["content_path"])
                        if p.exists():
                            try:
                                raw = p.read_text(encoding="utf-8")
                                parts = raw.split("\n\n", 1)
                                body = parts[1] if len(parts) > 1 else raw
                                full_text = body.strip()
                            except Exception:
                                pass
                    # Fallback: knowledge.content (RSS summary)
                    if not full_text:
                        krow = conn.execute(
                            "SELECT content FROM knowledge WHERE id = ?",
                            (art["kid"],),
                        ).fetchone()
                        if krow and krow["content"]:
                            full_text = krow["content"].strip()

            # Preview: first ~300 chars of full text
            if full_text:
                cut = full_text[:300]
                last_period = cut.rfind(".")
                if last_period > 100:
                    preview = cut[: last_period + 1]
                else:
                    preview = cut + "..."

            result.append({
                "id": cluster_id,
                "label": c["label"] or "(unlabeled cluster)",
                "article_count": c["article_count"],
                "source_count": c["source_count"],
                "significance": round(c["significance"], 1),
                "created_at": c["created_at"],
                "preview": preview,
                "full_text": full_text[:2000] if full_text else "",
                "articles": article_list,
            })

        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


def build_feed_html(clusters: list[dict[str, Any]]) -> str:
    """Render a self-contained HTML page with inline CSS and JS."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_articles = sum(c["article_count"] for c in clusters)

    # Build cluster cards
    cards_html = ""
    if not clusters:
        cards_html = (
            '<div class="empty">No stories in the last 3 days. '
            "Waiting for SignalForge to cluster new articles.</div>"
        )
    else:
        for i, c in enumerate(clusters):
            # Article list inside the expandable section
            art_items = ""
            for a in c["articles"]:
                source_tag = (
                    f' <span class="art-source">{_esc(a["source"])}</span>'
                    if a["source"]
                    else ""
                )
                if a["url"]:
                    art_items += (
                        f'<li><a href="{_esc(a["url"])}" target="_blank" '
                        f'rel="noopener">{_esc(a["title"])}</a>{source_tag}</li>'
                    )
                else:
                    art_items += f"<li>{_esc(a['title'])}{source_tag}</li>"

            full_text_html = ""
            if c["full_text"]:
                # Convert newlines to paragraphs
                paragraphs = c["full_text"].split("\n\n")
                for p in paragraphs[:10]:
                    p = p.strip()
                    if p:
                        full_text_html += f"<p>{_esc(p)}</p>"

            cards_html += f"""
        <div class="card">
            <h2>{_esc(c["label"])}</h2>
            <div class="meta">
                <span class="badge">{c["article_count"]} article{"s" if c["article_count"] != 1 else ""}</span>
                <span class="badge">{c["source_count"]} source{"s" if c["source_count"] != 1 else ""}</span>
                <span class="badge sig">sig: {c["significance"]}</span>
                <span class="time">{_format_time(c["created_at"])}</span>
            </div>
            <p class="preview">{_esc(c["preview"])}</p>
            <button class="toggle" onclick="toggle({i})">More &#9660;</button>
            <div class="details" id="det-{i}">
                <h3>Articles</h3>
                <ul>{art_items}</ul>
                <h3>Lead Article</h3>
                <div class="fulltext">{full_text_html if full_text_html else "<em>No full text available</em>"}</div>
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SignalForge Feed</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #f5f5f5; color: #333; line-height: 1.5; }}
header {{ background: #1a1a2e; color: #fff; padding: 1.2rem 2rem; }}
header h1 {{ font-size: 1.5rem; font-weight: 600; }}
header .stats {{ font-size: 0.85rem; color: #aab; margin-top: 0.3rem; }}
header .actions {{ margin-top: 0.8rem; }}
.synth-btn {{ background: #e94560; color: #fff; border: none; padding: 0.5rem 1.2rem;
              border-radius: 4px; cursor: pointer; font-size: 0.9rem; font-weight: 500; }}
.synth-btn:hover {{ background: #d63350; }}
.container {{ max-width: 800px; margin: 1.5rem auto; padding: 0 1rem; }}
.card {{ background: #fff; border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1rem;
         box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.card h2 {{ font-size: 1.15rem; margin-bottom: 0.4rem; color: #1a1a2e; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-bottom: 0.6rem; }}
.badge {{ background: #e8e8f0; color: #555; padding: 0.15rem 0.5rem; border-radius: 12px;
          font-size: 0.75rem; }}
.badge.sig {{ background: #ffeaa7; color: #856404; }}
.time {{ font-size: 0.75rem; color: #999; margin-left: auto; }}
.preview {{ color: #555; font-size: 0.92rem; margin-bottom: 0.5rem; }}
.toggle {{ background: none; border: 1px solid #ddd; padding: 0.3rem 0.8rem; border-radius: 4px;
           cursor: pointer; font-size: 0.8rem; color: #666; }}
.toggle:hover {{ background: #f0f0f0; }}
.details {{ display: none; margin-top: 1rem; border-top: 1px solid #eee; padding-top: 1rem; }}
.details h3 {{ font-size: 0.9rem; color: #1a1a2e; margin-bottom: 0.4rem; margin-top: 0.8rem; }}
.details h3:first-child {{ margin-top: 0; }}
.details ul {{ padding-left: 1.2rem; margin-bottom: 0.5rem; }}
.details li {{ font-size: 0.85rem; margin-bottom: 0.3rem; }}
.details li a {{ color: #2980b9; text-decoration: none; }}
.details li a:hover {{ text-decoration: underline; }}
.art-source {{ color: #999; font-size: 0.75rem; }}
.fulltext {{ font-size: 0.85rem; color: #444; }}
.fulltext p {{ margin-bottom: 0.6rem; }}
.empty {{ text-align: center; color: #999; padding: 3rem 1rem; font-size: 1.1rem; }}
</style>
</head>
<body>
<header>
    <h1>SignalForge Feed</h1>
    <div class="stats">{len(clusters)} cluster{"s" if len(clusters) != 1 else ""} &middot; {total_articles} article{"s" if total_articles != 1 else ""} &middot; Updated {now_str}</div>
    <div class="actions">
        <form method="POST" action="/synthesize" style="display:inline">
            <button type="submit" class="synth-btn">Synthesize Now</button>
        </form>
    </div>
</header>
<div class="container">
    {cards_html}
</div>
<script>
function toggle(i) {{
    var d = document.getElementById("det-" + i);
    var btn = d.previousElementSibling;
    if (d.style.display === "block") {{
        d.style.display = "none";
        btn.innerHTML = "More &#9660;";
    }} else {{
        d.style.display = "block";
        btn.innerHTML = "Less &#9650;";
    }}
}}
</script>
</body>
</html>"""


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_time(iso_str: str | None) -> str:
    """Format ISO timestamp to a short relative/absolute string."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if hours < 24:
            return f"{int(hours)}h ago"
        return f"{int(hours / 24)}d ago"
    except Exception:
        return iso_str[:16]


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class FeedHandler(BaseHTTPRequestHandler):
    """Handles GET / and POST /synthesize."""

    def do_GET(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if self.path != "/" and self.path != "":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        try:
            clusters = collect_feed_data()
            html = build_feed_html(clusters)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.error("Feed handler error: %s", e, exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Internal Server Error: {e}".encode())

    def do_POST(self) -> None:
        if self.path == "/synthesize":
            try:
                from .signalforge import run_signalforge_synthesis

                run_signalforge_synthesis(force=True)
            except Exception as e:
                logger.error("Synthesis trigger failed: %s", e, exc_info=True)
            # Redirect back to feed regardless
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        """Route request logs to the module logger instead of stderr."""
        logger.debug("Feed: %s", format % args)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def start_feed_server(port: int | None = None) -> dict[str, Any]:
    """Start the HTTP feed server in a daemon thread.

    Returns status dict. Safe to call if already running.
    """
    global _server, _thread
    if _server is not None:
        return {
            "status": "already_running",
            "url": f"http://localhost:{_server.server_address[1]}",
        }

    actual_port = port or SIGNALFORGE_FEED_PORT
    _server = HTTPServer(("127.0.0.1", actual_port), FeedHandler)
    _thread = threading.Thread(
        target=_server.serve_forever,
        name="signalforge-feed",
        daemon=True,
    )
    _thread.start()
    logger.info("SignalForge feed server started on port %d", actual_port)
    return {"status": "started", "url": f"http://localhost:{actual_port}"}


def stop_feed_server() -> dict[str, str]:
    """Stop the HTTP feed server. Safe to call if not running."""
    global _server, _thread
    if _server is None:
        return {"status": "not_running"}

    _server.shutdown()
    _server.server_close()
    _server = None
    _thread = None
    logger.info("SignalForge feed server stopped")
    return {"status": "stopped"}


def is_feed_running() -> bool:
    """Check if the feed server is currently running."""
    return _server is not None
