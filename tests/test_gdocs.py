"""Tests for the gdocs module (markdown-to-HTML conversion + Google Doc creation).

Tests the pure logic functions; Google API calls are not tested here.
"""

import pytest

from jaybrain.gdocs import (
    _html_escape,
    _format_text,
    _inline_to_html,
    _markdown_to_html,
    _is_table_separator,
    _parse_table_row,
    create_google_doc,
    read_google_doc,
)


class TestHtmlEscape:
    def test_ampersand(self):
        assert _html_escape("A & B") == "A &amp; B"

    def test_angle_brackets(self):
        assert _html_escape("<script>") == "&lt;script&gt;"

    def test_quotes(self):
        assert _html_escape('"hello"') == "&quot;hello&quot;"

    def test_plain(self):
        assert _html_escape("no special chars") == "no special chars"


class TestFormatText:
    def test_bold(self):
        result = _format_text("**bold text**")
        assert "<b>bold text</b>" in result

    def test_italic(self):
        result = _format_text("*italic text*")
        assert "<i>italic text</i>" in result

    def test_bold_italic(self):
        result = _format_text("***both***")
        assert "<b><i>both</i></b>" in result

    def test_link(self):
        result = _format_text("[click](https://example.com)")
        assert 'href="https://example.com"' in result
        assert "click" in result

    def test_escapes_html_first(self):
        result = _format_text("A & B **bold**")
        assert "&amp;" in result
        assert "<b>bold</b>" in result


class TestInlineToHtml:
    def test_code_span(self):
        result = _inline_to_html("Use `pip install`")
        assert "<code" in result
        assert "pip install" in result

    def test_mixed(self):
        result = _inline_to_html("**bold** and `code`")
        assert "<b>bold</b>" in result
        assert "<code" in result

    def test_plain(self):
        result = _inline_to_html("plain text")
        assert "plain text" in result


class TestTableHelpers:
    def test_separator_valid(self):
        assert _is_table_separator("| --- | --- |") is True
        assert _is_table_separator("|-----|-----|") is True

    def test_separator_invalid(self):
        assert _is_table_separator("| data | here |") is False
        assert _is_table_separator("not a table") is False

    def test_parse_row(self):
        cells = _parse_table_row("| A | B | C |")
        assert cells == ["A", "B", "C"]

    def test_parse_row_no_outer_pipes(self):
        cells = _parse_table_row("A | B | C")
        assert cells == ["A", "B", "C"]


class TestMarkdownToHtml:
    def test_heading1(self):
        html = _markdown_to_html("# Title")
        assert "<h1>" in html
        assert "Title" in html

    def test_heading2(self):
        html = _markdown_to_html("## Subtitle")
        assert "<h2>" in html

    def test_heading3(self):
        html = _markdown_to_html("### Section")
        assert "<h3>" in html

    def test_bullet_list(self):
        html = _markdown_to_html("- Item one\n- Item two")
        assert "<ul>" in html
        assert "<li>" in html
        assert "Item one" in html
        assert "Item two" in html

    def test_bullet_asterisk(self):
        html = _markdown_to_html("* Star bullet")
        assert "<ul>" in html
        assert "Star bullet" in html

    def test_numbered_list(self):
        html = _markdown_to_html("1. First\n2. Second")
        assert "<ol>" in html
        assert "First" in html

    def test_paragraph(self):
        html = _markdown_to_html("This is a paragraph.")
        assert "<p>" in html
        assert "This is a paragraph." in html

    def test_horizontal_rule(self):
        html = _markdown_to_html("---")
        assert "<hr" in html

    def test_code_block(self):
        html = _markdown_to_html("```python\nprint('hi')\n```")
        assert "<pre" in html or "<code" in html
        assert "print" in html

    def test_blockquote(self):
        html = _markdown_to_html("> Quoted text")
        assert "<blockquote" in html
        assert "Quoted text" in html

    def test_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = _markdown_to_html(md)
        assert "<table" in html
        assert "<td" in html

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
        html = _markdown_to_html(md)
        assert "<h1>" in html
        assert "<h2>" in html
        assert "<ul>" in html
        assert "<p>" in html
        assert "<hr" in html

    def test_inline_formatting_in_paragraph(self):
        html = _markdown_to_html("This has **bold** and *italic*.")
        assert "<b>bold</b>" in html
        assert "<i>italic</i>" in html


class TestCreateGoogleDoc:
    def test_no_credentials(self):
        """When credentials aren't available, should return error dict."""
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            result = create_google_doc("Test", "# Hello")
        assert "error" in result
        assert "credentials" in result["error"].lower()


class TestReadGoogleDoc:
    def test_no_credentials(self):
        """When credentials aren't available, should raise RuntimeError."""
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            with pytest.raises(RuntimeError, match="credentials"):
                read_google_doc("fake-doc-id")
