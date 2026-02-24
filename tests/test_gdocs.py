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
    DocElement,
    DocStructure,
    parse_doc_structure,
    build_replace_text_request,
    build_insert_text_request,
    build_delete_range_request,
    build_update_text_style_request,
    sort_requests_reverse,
    get_doc_structure,
    replace_text,
    append_to_doc,
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


# ---------------------------------------------------------------------------
# Document structure parsing tests
# ---------------------------------------------------------------------------

SAMPLE_DOC_JSON = {
    "documentId": "test-doc-123",
    "title": "Test Document",
    "body": {
        "content": [
            {
                "startIndex": 1,
                "endIndex": 16,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Main Heading\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                },
            },
            {
                "startIndex": 16,
                "endIndex": 35,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Some body text.\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
            {
                "startIndex": 35,
                "endIndex": 50,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Sub Heading\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                },
            },
            {
                "startIndex": 50,
                "endIndex": 70,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Sub body content.\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
            {
                "startIndex": 70,
                "endIndex": 90,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Another Heading\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                },
            },
            {
                "startIndex": 90,
                "endIndex": 105,
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Final content\n"}}
                    ],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
        ],
    },
}


class TestParseDocStructure:
    def test_parses_headings_and_paragraphs(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        headings = [e for e in structure.elements if e.kind == "heading"]
        paragraphs = [e for e in structure.elements if e.kind == "paragraph"]
        assert len(headings) == 3
        assert len(paragraphs) == 3

    def test_heading_levels(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        headings = structure.find_all_headings()
        assert headings[0].heading_level == 1
        assert headings[1].heading_level == 2
        assert headings[2].heading_level == 1

    def test_heading_text(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        h = structure.find_heading("Main Heading")
        assert h is not None
        assert "Main Heading" in h.text

    def test_h1_section_boundary(self):
        """H1 section extends until next H1."""
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        h1 = structure.find_heading("Main Heading")
        assert h1 is not None
        assert h1.section_end_index == 70  # stops at "Another Heading"

    def test_h2_section_boundary(self):
        """H2 section extends until next heading of same or higher level."""
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        h2 = structure.find_heading("Sub Heading")
        assert h2 is not None
        assert h2.section_end_index == 70  # stops at "Another Heading" (H1)

    def test_last_heading_extends_to_doc_end(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        last = structure.find_heading("Another Heading")
        assert last is not None
        assert last.section_end_index == 105

    def test_find_heading_substring(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        result = structure.find_heading("Main")
        assert result is not None
        assert result.heading_level == 1

    def test_find_heading_case_insensitive(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        result = structure.find_heading("main heading")
        assert result is not None

    def test_find_heading_with_level_filter(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        # "Sub Heading" is H2, should not match when filtering for H1
        result = structure.find_heading("Heading", level=2)
        assert result is not None
        assert result.heading_level == 2
        assert "Sub" in result.text

    def test_find_heading_not_found(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        result = structure.find_heading("Nonexistent")
        assert result is None

    def test_doc_end_index(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        assert structure.end_index == 105

    def test_doc_id_and_title(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        assert structure.doc_id == "test-doc-123"
        assert structure.title == "Test Document"

    def test_empty_doc(self):
        empty = {
            "documentId": "empty",
            "title": "Empty",
            "body": {"content": []},
        }
        structure = parse_doc_structure(empty)
        assert structure.elements == []
        assert structure.end_index == 1

    def test_find_all_headings_by_level(self):
        structure = parse_doc_structure(SAMPLE_DOC_JSON)
        h1s = structure.find_all_headings(level=1)
        assert len(h1s) == 2
        h2s = structure.find_all_headings(level=2)
        assert len(h2s) == 1


class TestRequestBuilders:
    def test_replace_text_request(self):
        req = build_replace_text_request("old", "new")
        assert "replaceAllText" in req
        assert req["replaceAllText"]["containsText"]["text"] == "old"
        assert req["replaceAllText"]["replaceText"] == "new"

    def test_insert_text_request(self):
        req = build_insert_text_request(42, "hello")
        assert req["insertText"]["location"]["index"] == 42
        assert req["insertText"]["text"] == "hello"

    def test_delete_range_request(self):
        req = build_delete_range_request(10, 50)
        rng = req["deleteContentRange"]["range"]
        assert rng["startIndex"] == 10
        assert rng["endIndex"] == 50

    def test_style_request_bold(self):
        req = build_update_text_style_request(5, 15, bold=True)
        assert req["updateTextStyle"]["textStyle"]["bold"] is True
        assert "bold" in req["updateTextStyle"]["fields"]

    def test_style_request_multiple_fields(self):
        req = build_update_text_style_request(0, 10, bold=True, italic=True, font_size=14.0)
        style = req["updateTextStyle"]["textStyle"]
        assert style["bold"] is True
        assert style["italic"] is True
        assert style["fontSize"]["magnitude"] == 14.0
        fields = req["updateTextStyle"]["fields"]
        assert "bold" in fields
        assert "italic" in fields
        assert "fontSize" in fields

    def test_style_request_omits_none_fields(self):
        req = build_update_text_style_request(0, 10, italic=True)
        assert "bold" not in req["updateTextStyle"]["textStyle"]
        assert "italic" in req["updateTextStyle"]["fields"]
        assert "bold" not in req["updateTextStyle"]["fields"]

    def test_sort_requests_reverse(self):
        requests = [
            build_insert_text_request(10, "a"),
            build_insert_text_request(50, "b"),
            build_insert_text_request(30, "c"),
        ]
        sorted_reqs = sort_requests_reverse(requests)
        indexes = [r["insertText"]["location"]["index"] for r in sorted_reqs]
        assert indexes == [50, 30, 10]

    def test_sort_mixed_request_types(self):
        requests = [
            build_insert_text_request(10, "a"),
            build_delete_range_request(60, 80),
            build_replace_text_request("x", "y"),  # index 0 (no position)
        ]
        sorted_reqs = sort_requests_reverse(requests)
        # delete (80) should come first, then insert (10), then replace (0)
        assert "deleteContentRange" in sorted_reqs[0]
        assert "insertText" in sorted_reqs[1]
        assert "replaceAllText" in sorted_reqs[2]


class TestEditAPINoCredentials:
    """API functions handle missing credentials gracefully."""

    def test_get_doc_structure_no_creds(self):
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            with pytest.raises(RuntimeError, match="credentials"):
                get_doc_structure("fake-id")

    def test_replace_text_no_creds(self):
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            result = replace_text("fake-id", "old", "new")
            assert "error" in result

    def test_append_no_creds(self):
        from unittest.mock import patch
        with patch("jaybrain.gdocs._get_credentials", return_value=None):
            result = append_to_doc("fake-id", "text")
            assert "error" in result
