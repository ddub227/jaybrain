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


def _get_sheets_service(creds):
    """Build a Google Sheets API service client."""
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def register_sheet_in_index(
    spreadsheet_id: str,
    title: str,
    purpose: str = "",
    category: str = "",
    created_by: str = "JayBrain",
) -> bool:
    """Append a new row to the Google Sheets Master Index.

    Called automatically whenever JayBrain creates a new spreadsheet.
    Silently returns False on failure so it never blocks the main workflow.
    """
    from datetime import date

    from .config import SHEETS_INDEX_ID

    creds = _get_credentials()
    if creds is None:
        return False

    try:
        sheets_service = _get_sheets_service(creds)
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        today = date.today().isoformat()

        sheets_service.spreadsheets().values().append(
            spreadsheetId=SHEETS_INDEX_ID,
            range="Index!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [[
                title, url, spreadsheet_id, purpose,
                category, today, "", "active", created_by, "",
            ]]},
        ).execute()
        logger.info("Registered sheet '%s' in master index", title)
        return True
    except Exception as e:
        logger.warning("Failed to register sheet in index: %s", e)
        return False


# ---------------------------------------------------------------------------
# Markdown to HTML conversion
# ---------------------------------------------------------------------------

def _html_escape(text: str) -> str:
    """Escape HTML special characters in text content."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _format_text(text: str) -> str:
    """Apply bold, italic, and link formatting to escaped HTML text."""
    text = _html_escape(text)
    text = re.sub(r"\*{3}(.+?)\*{3}", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*{2}(.+?)\*{2}", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _inline_to_html(text: str) -> str:
    """Convert inline markdown to HTML, processing code spans first."""
    result = []
    last = 0
    for m in re.finditer(r"`([^`]+)`", text):
        before = text[last:m.start()]
        result.append(_format_text(before))
        result.append(
            f'<code style="font-family:Consolas,monospace;'
            f'background-color:#f5f5f5;padding:1px 3px;">'
            f"{_html_escape(m.group(1))}</code>"
        )
        last = m.end()
    result.append(_format_text(text[last:]))
    return "".join(result)


def _is_table_separator(line: str) -> bool:
    """Check if a line is a markdown table separator row."""
    return bool(re.match(r"^\s*\|[\s\-:|]+\|\s*$", line))


def _parse_table_row(line: str) -> list[str]:
    """Parse a markdown table row into cell text values."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _markdown_to_html(md: str) -> str:
    """Convert markdown to HTML for Google Docs import.

    Handles headings, bold, italic, tables, bullets, numbered lists,
    checkboxes, code blocks, blockquotes, horizontal rules, links,
    and inline code.
    """
    lines = md.replace("\r\n", "\n").split("\n")
    html: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # --- Code block (fenced) ---
        if line.strip().startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(_html_escape(lines[i]))
                i += 1
            if i < len(lines):
                i += 1
            html.append(
                '<pre style="font-family:Consolas,monospace;'
                "background-color:#f5f5f5;padding:8px;"
                'border:1px solid #ddd;font-size:10pt;">'
                + "\n".join(code_lines)
                + "</pre>"
            )
            continue

        # --- Horizontal rule ---
        if re.match(r"^\s*([-]{3,}|[*]{3,}|[_]{3,})\s*$", line):
            html.append("<hr>")
            i += 1
            continue

        # --- Heading ---
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = _inline_to_html(m.group(2).strip())
            html.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # --- Table ---
        if (
            "|" in line
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            headers = _parse_table_row(line)
            num_cols = len(headers)
            i += 2
            rows: list[list[str]] = []
            while (
                i < len(lines)
                and lines[i].strip()
                and "|" in lines[i]
                and not _is_table_separator(lines[i])
            ):
                rows.append(_parse_table_row(lines[i]))
                i += 1
            if i < len(lines) and _is_table_separator(lines[i]):
                i += 1

            html.append(
                '<table border="1" cellpadding="5" cellspacing="0"'
                ' style="border-collapse:collapse;border-color:#999;">'
            )
            html.append("<tr>")
            for h in headers:
                html.append(
                    f'<th style="background-color:#f0f0f0;">'
                    f"{_inline_to_html(h)}</th>"
                )
            html.append("</tr>")
            for row in rows:
                html.append("<tr>")
                for ci in range(num_cols):
                    cell = row[ci] if ci < len(row) else ""
                    html.append(f"<td>{_inline_to_html(cell)}</td>")
                html.append("</tr>")
            html.append("</table><br>")
            continue

        # --- Blockquote ---
        if line.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines) and (
                lines[i].startswith("> ")
                or lines[i] == ">"
                or lines[i].startswith(">")
            ):
                content = lines[i]
                if content.startswith("> "):
                    content = content[2:]
                elif content == ">":
                    content = ""
                else:
                    content = content[1:]
                quote_lines.append(content)
                i += 1
            quote_html = "<br>".join(
                _inline_to_html(ql) for ql in quote_lines
            )
            html.append(
                '<blockquote style="border-left:3px solid #ccc;'
                'padding-left:12px;margin-left:0;color:#555;">'
                f"{quote_html}</blockquote>"
            )
            continue

        # --- Checkbox list ---
        if re.match(r"^\s*-\s+\[[ x]\]", line):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*-\s+\[[ x]\]", lines[i]):
                cm = re.match(r"^\s*-\s+\[([ x])\]\s*(.*)", lines[i])
                if cm:
                    checked = cm.group(1) == "x"
                    text = _inline_to_html(cm.group(2))
                    marker = "&#9745;" if checked else "&#9744;"
                    items.append(f"{marker} {text}")
                i += 1
            html.append("<ul style='list-style:none;padding-left:0;'>")
            for item in items:
                html.append(f"<li>{item}</li>")
            html.append("</ul>")
            continue

        # --- Numbered list (with nested bullets) ---
        if re.match(r"^\s{0,3}\d+\.\s+", line):
            html.append("<ol>")
            while i < len(lines) and re.match(r"^\s{0,3}\d+\.\s+", lines[i]):
                nm = re.match(r"^\s{0,3}\d+\.\s+(.*)", lines[i])
                item_text = _inline_to_html(nm.group(1)) if nm else ""
                i += 1
                nested: list[str] = []
                while i < len(lines) and re.match(r"^\s{2,}[-*+]\s+", lines[i]):
                    sm = re.match(r"^\s{2,}[-*+]\s+(.*)", lines[i])
                    if sm:
                        nested.append(_inline_to_html(sm.group(1)))
                    i += 1
                if nested:
                    sub = "<ul>" + "".join(
                        f"<li>{n}</li>" for n in nested
                    ) + "</ul>"
                    html.append(f"<li>{item_text}{sub}</li>")
                else:
                    html.append(f"<li>{item_text}</li>")
            html.append("</ol>")
            continue

        # --- Bullet list (with nested bullets) ---
        if re.match(r"^\s{0,1}[-*+]\s+", line):
            html.append("<ul>")
            while i < len(lines) and re.match(r"^\s{0,1}[-*+]\s+", lines[i]):
                bm = re.match(r"^\s{0,1}[-*+]\s+(.*)", lines[i])
                item_text = _inline_to_html(bm.group(1)) if bm else ""
                i += 1
                nested = []
                while i < len(lines) and re.match(r"^\s{2,}[-*+]\s+", lines[i]):
                    sm = re.match(r"^\s{2,}[-*+]\s+(.*)", lines[i])
                    if sm:
                        nested.append(_inline_to_html(sm.group(1)))
                    i += 1
                if nested:
                    sub = "<ul>" + "".join(
                        f"<li>{n}</li>" for n in nested
                    ) + "</ul>"
                    html.append(f"<li>{item_text}{sub}</li>")
                else:
                    html.append(f"<li>{item_text}</li>")
            html.append("</ul>")
            continue

        # --- Empty line ---
        if not line.strip():
            i += 1
            continue

        # --- Paragraph ---
        para_lines: list[str] = []
        while i < len(lines):
            ln = lines[i]
            if not ln.strip():
                break
            if re.match(r"^#{1,6}\s+", ln):
                break
            if re.match(r"^\s*[-*+]\s+", ln):
                break
            if re.match(r"^\s*\d+\.\s+", ln):
                break
            if ln.startswith(">"):
                break
            if ln.strip().startswith("```"):
                break
            if re.match(r"^\s*([-]{3,}|[*]{3,}|[_]{3,})\s*$", ln):
                break
            if (
                "|" in ln
                and i + 1 < len(lines)
                and _is_table_separator(lines[i + 1])
            ):
                break
            para_lines.append(ln)
            i += 1

        if para_lines:
            text = _inline_to_html(" ".join(para_lines))
            html.append(f"<p>{text}</p>")
        continue

    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        "<style>"
        "body { font-family: Arial, sans-serif; font-size: 11pt; }"
        "h1 { font-size: 20pt; }"
        "h2 { font-size: 16pt; }"
        "h3 { font-size: 13pt; }"
        "table { width: 100%; margin-bottom: 8px; }"
        "th { text-align: left; }"
        "code { font-family: Consolas, monospace; }"
        "</style>"
        "</head><body>"
        + "\n".join(html)
        + "</body></html>"
    )


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

    Converts markdown to HTML and uploads via the Drive API, which
    natively handles tables, headings, bold/italic, lists, code blocks,
    blockquotes, and all other formatting.

    Args:
        title: Document title.
        markdown_content: Markdown-formatted content to convert.
        folder_id: Optional Google Drive folder ID to place the doc in.
        share_with: Optional email address to share the doc with (writer access).

    Returns:
        Dict with doc_id, doc_url, title on success.
        Dict with error key on failure.
    """
    from googleapiclient.http import MediaInMemoryUpload

    from .config import GDOC_FOLDER_ID, GDOC_SHARE_EMAIL

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
        drive_service = _get_drive_service(creds)

        html_content = _markdown_to_html(markdown_content)

        media = MediaInMemoryUpload(
            html_content.encode("utf-8"),
            mimetype="text/html",
            resumable=False,
        )

        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if folder_id:
            file_metadata["parents"] = [folder_id]

        created = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
        ).execute()

        doc_id = created["id"]
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        logger.info("Created Google Doc: %s (%s)", title, doc_id)

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


# ---------------------------------------------------------------------------
# Google Drive folder management
# ---------------------------------------------------------------------------

def find_or_create_folder(
    name: str,
    parent_id: str = "",
) -> dict:
    """Find a folder by name (optionally within a parent) or create it.

    If a folder with the given name already exists under the parent,
    returns its ID without creating a duplicate.

    Args:
        name: Folder name.
        parent_id: Optional parent folder ID. If empty, searches/creates in root.

    Returns:
        Dict with folder_id, folder_name, created (bool), or error.
    """
    creds = _get_credentials()
    if creds is None:
        return {"error": "Google credentials not available."}

    try:
        drive = _get_drive_service(creds)

        # Search for existing folder with this name
        query_parts = [
            f"name = '{name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")

        results = drive.files().list(
            q=" and ".join(query_parts),
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
        ).execute()

        files = results.get("files", [])
        if files:
            folder = files[0]
            logger.info("Found existing folder '%s' (%s)", folder["name"], folder["id"])
            return {
                "folder_id": folder["id"],
                "folder_name": folder["name"],
                "created": False,
            }

        # Create the folder
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = drive.files().create(
            body=metadata,
            fields="id, name",
        ).execute()

        logger.info("Created folder '%s' (%s)", folder["name"], folder["id"])
        return {
            "folder_id": folder["id"],
            "folder_name": folder["name"],
            "created": True,
        }

    except Exception as e:
        logger.error("Failed to find/create folder '%s': %s", name, e, exc_info=True)
        return {"error": f"Google Drive API error: {e}"}


def move_file_to_folder(
    file_id: str,
    folder_id: str,
) -> dict:
    """Move a file (document, spreadsheet, etc.) into a Drive folder.

    Removes the file from its current parent(s) and adds it to the
    specified folder.

    Args:
        file_id: The Google Drive file ID to move.
        folder_id: The target folder ID.

    Returns:
        Dict with file_id, folder_id, file_name on success, or error.
    """
    creds = _get_credentials()
    if creds is None:
        return {"error": "Google credentials not available."}

    try:
        drive = _get_drive_service(creds)

        # Get current parents so we can remove them
        file_info = drive.files().get(
            fileId=file_id,
            fields="id, name, parents",
        ).execute()

        previous_parents = ",".join(file_info.get("parents", []))

        # Move: add new parent, remove old parents
        updated = drive.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, name, parents",
        ).execute()

        logger.info(
            "Moved '%s' (%s) to folder %s",
            updated["name"], updated["id"], folder_id,
        )
        return {
            "file_id": updated["id"],
            "file_name": updated["name"],
            "folder_id": folder_id,
        }

    except Exception as e:
        logger.error(
            "Failed to move file %s to folder %s: %s",
            file_id, folder_id, e, exc_info=True,
        )
        return {"error": f"Google Drive API error: {e}"}
