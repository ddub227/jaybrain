"""Job board URL management and web fetching.

Registers job board URLs to monitor, fetches pages, and strips HTML
boilerplate so Claude can parse the cleaned text and extract postings.
Includes auto-fetch for daemon-driven change detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from .db import (
    get_connection,
    get_job_board,
    insert_job_board,
    list_job_boards,
    now_iso,
    update_job_board,
)
from .models import JobBoard

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _parse_board_row(row) -> JobBoard:
    """Convert a database row to a JobBoard model."""
    return JobBoard(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        board_type=row["board_type"],
        tags=json.loads(row["tags"]),
        active=bool(row["active"]),
        last_checked=datetime.fromisoformat(row["last_checked"]) if row["last_checked"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def add_board(
    name: str,
    url: str,
    board_type: str = "general",
    tags: Optional[list[str]] = None,
) -> JobBoard:
    """Register a new job board URL to monitor."""
    tags = tags or []
    board_id = _generate_id()
    conn = get_connection()
    try:
        insert_job_board(conn, board_id, name, url, board_type, tags)
        row = get_job_board(conn, board_id)
        return _parse_board_row(row)
    finally:
        conn.close()


def get_boards(active_only: bool = True) -> list[JobBoard]:
    """List all registered job boards."""
    conn = get_connection()
    try:
        rows = list_job_boards(conn, active_only=active_only)
        return [_parse_board_row(r) for r in rows]
    finally:
        conn.close()


def fetch_board(
    board_id: str,
    max_pages: int = 0,
    render: str = "auto",
) -> dict:
    """Fetch a job board URL with enhanced scraping.

    Uses the scraping module for SPA detection, optional Playwright
    rendering, pagination following, and structured metadata extraction.

    render modes: "auto" (detect SPA), "always" (force Playwright), "never" (plain HTTP).
    max_pages: how many pagination pages to follow (0 = config default).
    """
    from .scraping import fetch_pages

    conn = get_connection()
    try:
        row = get_job_board(conn, board_id)
        if not row:
            raise ValueError(f"Job board not found: {board_id}")

        board = _parse_board_row(row)

        pages = fetch_pages(board.url, max_pages=max_pages, render=render)

        # Combine all page text for Claude to parse
        combined_text = ""
        total_length = 0
        any_rendered = False
        for page in pages:
            if page["rendered"]:
                any_rendered = True
            combined_text += page["text"] + "\n\n"
            total_length += page["text_length"]

        # First page metadata is most useful
        metadata = pages[0]["metadata"] if pages else {}

        # Update last_checked
        update_job_board(conn, board_id, last_checked=now_iso())

        return {
            "board_id": board.id,
            "board_name": board.name,
            "url": board.url,
            "content": combined_text.strip(),
            "content_length": total_length,
            "pages_fetched": len(pages),
            "js_rendered": any_rendered,
            "metadata": metadata,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-fetch: daemon-driven change detection
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    """SHA-256 hash of content for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def auto_fetch_boards() -> dict:
    """Fetch all active boards, detect content changes, notify via Telegram.

    Called by the daemon on a weekly schedule. For each active board:
    1. Fetch the page content via the scraping pipeline.
    2. Hash the content and compare against the stored content_hash.
    3. If changed, send a Telegram notification and update the hash.

    Returns a summary dict with counts of checked/changed/errored boards.
    """
    boards = get_boards(active_only=True)
    if not boards:
        return {"checked": 0, "changed": 0, "errors": 0, "message": "No active boards"}

    checked = 0
    changed = 0
    errors = 0
    changed_boards: list[str] = []

    for board in boards:
        try:
            result = fetch_board(board.id, max_pages=1, render="auto")
            content = result.get("content", "")
            new_hash = _content_hash(content)

            conn = get_connection()
            try:
                row = get_job_board(conn, board.id)
                old_hash = row["content_hash"] if row and row["content_hash"] else ""

                if new_hash != old_hash:
                    update_job_board(conn, board.id, content_hash=new_hash)
                    changed += 1
                    changed_boards.append(f"{board.name} ({board.url})")
            finally:
                conn.close()

            checked += 1
        except Exception as e:
            logger.error("Auto-fetch failed for board %s (%s): %s", board.name, board.id, e)
            errors += 1

    # Notify on changes
    if changed_boards:
        try:
            from .telegram import send_telegram_message
            lines = [f"{len(changed_boards)} job board(s) have new content:"]
            for name in changed_boards[:10]:
                lines.append(f"  - {name}")
            if len(changed_boards) > 10:
                lines.append(f"  ... and {len(changed_boards) - 10} more")
            send_telegram_message("\n".join(lines))
        except Exception as e:
            logger.error("Failed to send job board change notification: %s", e)

    summary = {
        "checked": checked,
        "changed": changed,
        "errors": errors,
        "changed_boards": changed_boards,
    }
    logger.info("Auto-fetch complete: %s", summary)
    return summary
