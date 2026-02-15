"""Google Docs integration for JayBrain.

Creates formatted Google Docs from markdown content using the Docs API,
and shares them via the Drive API. Used by resume/cover letter workflows
to produce professional documents alongside local markdown files.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def _get_credentials():
    """Load OAuth user credentials for Google Docs/Drive access.

    Uses OAuth 2.0 flow with the user's personal Google account so that
    created documents count against the user's storage quota (not the
    service account's zero-byte quota). A refresh token is cached after
    the first authorization.

    Returns Google credentials or None if unavailable.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        from .config import OAUTH_CLIENT_PATH, OAUTH_SCOPES, OAUTH_TOKEN_PATH

        scopes = OAUTH_SCOPES

        creds = None

        # Load cached token if it exists
        if OAUTH_TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(
                str(OAUTH_TOKEN_PATH), scopes,
            )

        # Refresh or run auth flow
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            if not OAUTH_CLIENT_PATH.exists():
                logger.warning("OAuth client file not found: %s", OAUTH_CLIENT_PATH)
                return None
            flow = InstalledAppFlow.from_client_secrets_file(
                str(OAUTH_CLIENT_PATH), scopes,
            )
            creds = flow.run_local_server(port=0)

        # Cache the token for future use
        OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        OAUTH_TOKEN_PATH.write_text(creds.to_json())

        return creds
    except ImportError:
        logger.warning(
            "google-auth-oauthlib not installed; Google Docs integration unavailable"
        )
        return None
    except Exception as e:
        logger.error("Failed to load Google credentials: %s", e)
        return None


def _get_docs_service(creds):
    """Build a Google Docs API service client."""
    from googleapiclient.discovery import build
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _get_drive_service(creds):
    """Build a Google Drive API service client."""
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _parse_markdown(md: str) -> list[dict]:
    """Parse markdown into a list of block dicts.

    Each block has:
      type: "heading1" | "heading2" | "heading3" | "bullet" | "rule" | "paragraph"
      text: the raw text content (without markdown markers)
      runs: list of {text, bold, italic} for inline formatting
    """
    blocks: list[dict] = []
    lines = md.replace("\r\n", "\n").split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Horizontal rule
        if re.match(r"^\s*-{3,}\s*$", line) or re.match(r"^\s*\*{3,}\s*$", line):
            blocks.append({"type": "rule"})
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            blocks.append({
                "type": f"heading{level}",
                "text": text,
                "runs": _parse_inline(text),
            })
            i += 1
            continue

        # Bullet
        m = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m:
            text = m.group(1).strip()
            blocks.append({
                "type": "bullet",
                "text": text,
                "runs": _parse_inline(text),
            })
            i += 1
            continue

        # Empty line - skip
        if line.strip() == "":
            i += 1
            continue

        # Paragraph: collect consecutive non-empty, non-special lines
        para_lines = []
        while i < len(lines):
            ln = lines[i]
            if ln.strip() == "":
                break
            if re.match(r"^#{1,3}\s+", ln):
                break
            if re.match(r"^\s*[-*+]\s+", ln):
                break
            if re.match(r"^\s*-{3,}\s*$", ln) or re.match(r"^\s*\*{3,}\s*$", ln):
                break
            para_lines.append(ln)
            i += 1

        if para_lines:
            text = " ".join(para_lines)
            blocks.append({
                "type": "paragraph",
                "text": text,
                "runs": _parse_inline(text),
            })
        continue

    return blocks


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown formatting into runs.

    Handles **bold**, *italic*, and ***bold+italic***.
    Returns list of {text, bold, italic}.
    """
    runs: list[dict] = []
    # Pattern matches ***bold+italic***, **bold**, *italic*, or plain text
    pattern = re.compile(
        r"\*{3}(.+?)\*{3}"     # ***bold italic***
        r"|\*{2}(.+?)\*{2}"    # **bold**
        r"|\*(.+?)\*"          # *italic*
        r"|([^*]+)"            # plain text
    )

    for m in pattern.finditer(text):
        if m.group(1) is not None:
            runs.append({"text": m.group(1), "bold": True, "italic": True})
        elif m.group(2) is not None:
            runs.append({"text": m.group(2), "bold": True, "italic": False})
        elif m.group(3) is not None:
            runs.append({"text": m.group(3), "bold": False, "italic": True})
        elif m.group(4) is not None:
            runs.append({"text": m.group(4), "bold": False, "italic": False})

    return runs


# ---------------------------------------------------------------------------
# Docs API request builders
# ---------------------------------------------------------------------------

# Heading style mapping
_HEADING_STYLES = {
    "heading1": "HEADING_1",
    "heading2": "HEADING_2",
    "heading3": "HEADING_3",
}


def _build_requests(blocks: list[dict]) -> list[dict]:
    """Build Google Docs batchUpdate requests from parsed blocks.

    Strategy:
    1. Insert all text at index 1 (start of body) in reverse order
       so the first block ends up first in the document.
    2. Then apply paragraph styles and text formatting using character ranges.

    We build two passes:
    - Pass 1: Insert text for all blocks (in reverse)
    - Pass 2: Apply styles using computed offsets (forward)
    """
    if not blocks:
        return []

    # Build the full text content and track offsets
    # Each block becomes text + newline
    segments: list[dict] = []  # {text, block_idx, type, runs}

    for idx, block in enumerate(blocks):
        if block["type"] == "rule":
            # Insert a horizontal rule as a sequence of underscores
            segments.append({
                "text": "\n",
                "block_idx": idx,
                "type": "rule",
                "runs": [],
            })
        else:
            text = block.get("text", "")
            segments.append({
                "text": text + "\n",
                "block_idx": idx,
                "type": block["type"],
                "runs": block.get("runs", []),
            })

    # Build insert requests in reverse order (inserting at index 1 each time)
    insert_requests = []
    for seg in reversed(segments):
        insert_requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": seg["text"],
            }
        })

    # Compute forward offsets for styling
    style_requests = []
    offset = 1  # document body starts at index 1

    for seg in segments:
        text_len = len(seg["text"])
        seg_type = seg["type"]

        if seg_type == "rule":
            # Style the rule line
            if text_len > 0:
                style_requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": offset, "endIndex": offset + text_len},
                        "paragraphStyle": {
                            "borderBottom": {
                                "color": {"color": {"rgbColor": {"red": 0.7, "green": 0.7, "blue": 0.7}}},
                                "width": {"magnitude": 1, "unit": "PT"},
                                "padding": {"magnitude": 6, "unit": "PT"},
                                "dashStyle": "SOLID",
                            },
                        },
                        "fields": "borderBottom",
                    }
                })
        elif seg_type in _HEADING_STYLES:
            style_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": offset, "endIndex": offset + text_len},
                    "paragraphStyle": {
                        "namedStyleType": _HEADING_STYLES[seg_type],
                    },
                    "fields": "namedStyleType",
                }
            })
        elif seg_type == "bullet":
            style_requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": offset, "endIndex": offset + text_len},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # Apply inline formatting (bold/italic)
        if seg.get("runs"):
            run_offset = offset
            for run in seg["runs"]:
                run_len = len(run["text"])
                if run_len > 0 and (run.get("bold") or run.get("italic")):
                    text_style = {}
                    fields = []
                    if run.get("bold"):
                        text_style["bold"] = True
                        fields.append("bold")
                    if run.get("italic"):
                        text_style["italic"] = True
                        fields.append("italic")

                    style_requests.append({
                        "updateTextStyle": {
                            "range": {
                                "startIndex": run_offset,
                                "endIndex": run_offset + run_len,
                            },
                            "textStyle": text_style,
                            "fields": ",".join(fields),
                        }
                    })
                run_offset += run_len
            # Account for the newline that was appended but isn't in runs
            # run_offset should now point past the visible text, before \n

        offset += text_len

    return insert_requests + style_requests


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_google_doc(
    title: str,
    markdown_content: str,
    folder_id: str = "",
    share_with: str = "",
) -> dict:
    """Create a formatted Google Doc from markdown content.

    Args:
        title: Document title.
        markdown_content: Markdown-formatted content to convert.
        folder_id: Optional Google Drive folder ID to place the doc in.
        share_with: Optional email address to share the doc with (writer access).

    Returns:
        Dict with doc_id, doc_url, title on success.
        Dict with error key on failure.
    """
    from .config import GDOC_FOLDER_ID, GDOC_SHARE_EMAIL

    # Use defaults from config if not specified
    if not folder_id:
        folder_id = GDOC_FOLDER_ID
    if not share_with:
        share_with = GDOC_SHARE_EMAIL

    creds = _get_credentials()
    if creds is None:
        return {
            "error": "Google credentials not available. "
                     "Check GOOGLE_APPLICATION_CREDENTIALS or service account file.",
        }

    try:
        docs_service = _get_docs_service(creds)
        drive_service = _get_drive_service(creds)

        # Create doc directly in target folder via Drive API so storage
        # counts against the folder owner, not the service account.
        file_metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        created = drive_service.files().create(
            body=file_metadata, fields="id",
        ).execute()
        doc_id = created["id"]
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        logger.info("Created Google Doc: %s (%s)", title, doc_id)

        # Parse markdown and build formatting requests
        blocks = _parse_markdown(markdown_content)
        requests = _build_requests(blocks)

        if requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            logger.info("Applied %d formatting requests", len(requests))

        # Share with user
        if share_with:
            try:
                drive_service.permissions().create(
                    fileId=doc_id,
                    body={
                        "type": "user",
                        "role": "writer",
                        "emailAddress": share_with,
                    },
                    sendNotificationEmail=False,
                ).execute()
                logger.info("Shared doc with %s", share_with)
            except Exception as e:
                logger.warning("Failed to share doc with %s: %s", share_with, e)

        return {
            "doc_id": doc_id,
            "doc_url": doc_url,
            "title": title,
        }

    except Exception as e:
        logger.error("Failed to create Google Doc: %s", e, exc_info=True)
        return {"error": f"Google Docs API error: {e}"}
