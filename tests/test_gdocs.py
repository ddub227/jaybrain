"""Tests for the gdocs module (markdown parsing + request building).

Tests the pure logic functions; Google API calls are not tested here.
"""

import pytest

from jaybrain.gdocs import (
    _parse_markdown,
    _parse_inline,
    _build_requests,
    _HEADING_STYLES,
    create_google_doc,
)


class TestParseInline:
    def test_plain_text(self):
        runs = _parse_inline("Hello world")
        assert len(runs) == 1
        assert runs[0]["text"] == "Hello world"
        assert runs[0]["bold"] is False
        assert runs[0]["italic"] is False

    def test_bold(self):
        runs = _parse_inline("**bold text**")
        assert any(r["bold"] and r["text"] == "bold text" for r in runs)

    def test_italic(self):
        runs = _parse_inline("*italic text*")
        assert any(r["italic"] and r["text"] == "italic text" for r in runs)

    def test_bold_italic(self):
        runs = _parse_inline("***both***")
        assert any(r["bold"] and r["italic"] and r["text"] == "both" for r in runs)

    def test_mixed(self):
        runs = _parse_inline("Normal **bold** and *italic*")
        texts = [r["text"] for r in runs]
        assert "bold" in texts
        assert "italic" in texts
        bold_run = next(r for r in runs if r["text"] == "bold")
        assert bold_run["bold"] is True
        italic_run = next(r for r in runs if r["text"] == "italic")
        assert italic_run["italic"] is True


class TestParseMarkdown:
    def test_heading1(self):
        blocks = _parse_markdown("# Title")
        assert blocks[0]["type"] == "heading1"
        assert blocks[0]["text"] == "Title"

    def test_heading2(self):
        blocks = _parse_markdown("## Subtitle")
        assert blocks[0]["type"] == "heading2"
        assert blocks[0]["text"] == "Subtitle"

    def test_heading3(self):
        blocks = _parse_markdown("### Section")
        assert blocks[0]["type"] == "heading3"
        assert blocks[0]["text"] == "Section"

    def test_bullet(self):
        blocks = _parse_markdown("- Item one\n- Item two")
        assert len(blocks) == 2
        assert all(b["type"] == "bullet" for b in blocks)
        assert blocks[0]["text"] == "Item one"

    def test_bullet_asterisk(self):
        blocks = _parse_markdown("* Star bullet")
        assert blocks[0]["type"] == "bullet"

    def test_paragraph(self):
        blocks = _parse_markdown("This is a paragraph.\nContinues here.")
        assert blocks[0]["type"] == "paragraph"
        assert "This is a paragraph." in blocks[0]["text"]
        assert "Continues here." in blocks[0]["text"]

    def test_horizontal_rule_dashes(self):
        blocks = _parse_markdown("---")
        assert blocks[0]["type"] == "rule"

    def test_horizontal_rule_asterisks(self):
        blocks = _parse_markdown("***")
        assert blocks[0]["type"] == "rule"

    def test_empty_lines_skipped(self):
        blocks = _parse_markdown("\n\n# Title\n\nParagraph\n\n")
        assert len(blocks) == 2

    def test_mixed_content(self):
        md = """# Resume

## Summary
Experienced developer.

## Skills
- Python
- SQL
- Docker

---

## Experience
Built things.
"""
        blocks = _parse_markdown(md)
        types = [b["type"] for b in blocks]
        assert "heading1" in types
        assert "heading2" in types
        assert "bullet" in types
        assert "paragraph" in types
        assert "rule" in types


class TestBuildRequests:
    def test_empty_blocks(self):
        assert _build_requests([]) == []

    def test_single_paragraph(self):
        blocks = [{"type": "paragraph", "text": "Hello", "runs": [{"text": "Hello", "bold": False, "italic": False}]}]
        requests = _build_requests(blocks)
        # Should have at least an insertText request
        insert_reqs = [r for r in requests if "insertText" in r]
        assert len(insert_reqs) >= 1
        assert insert_reqs[0]["insertText"]["text"] == "Hello\n"

    def test_heading_gets_style(self):
        blocks = [{"type": "heading1", "text": "Title", "runs": [{"text": "Title", "bold": False, "italic": False}]}]
        requests = _build_requests(blocks)
        style_reqs = [r for r in requests if "updateParagraphStyle" in r]
        assert len(style_reqs) >= 1
        assert style_reqs[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"

    def test_bullet_gets_style(self):
        blocks = [{"type": "bullet", "text": "Item", "runs": [{"text": "Item", "bold": False, "italic": False}]}]
        requests = _build_requests(blocks)
        bullet_reqs = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_reqs) >= 1

    def test_bold_gets_text_style(self):
        blocks = [{"type": "paragraph", "text": "**bold**", "runs": [{"text": "bold", "bold": True, "italic": False}]}]
        requests = _build_requests(blocks)
        text_style_reqs = [r for r in requests if "updateTextStyle" in r]
        assert len(text_style_reqs) >= 1
        assert text_style_reqs[0]["updateTextStyle"]["textStyle"]["bold"] is True


class TestCreateGoogleDoc:
    def test_no_credentials(self):
        """When credentials aren't available, should return error dict."""
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            result = create_google_doc("Test", "# Hello")
        assert "error" in result
        assert "credentials" in result["error"].lower()
