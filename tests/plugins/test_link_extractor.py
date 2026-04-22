"""Unit tests for the link_extractor module."""

from __future__ import annotations

from plugins.ingest_space.link_extractor import (
    _detect_kind,
    _normalise,
    extract_text,
)


class TestDetectKindMime:
    """Format detection via MIME content-type header."""

    def test_pdf(self):
        assert _detect_kind(b"", "application/pdf") == "pdf"

    def test_docx(self):
        assert _detect_kind(
            b"",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ) == "docx"

    def test_xlsx(self):
        assert _detect_kind(
            b"",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ) == "xlsx"

    def test_html(self):
        assert _detect_kind(b"", "text/html") == "html"

    def test_plain(self):
        assert _detect_kind(b"", "text/plain") == "text"

    def test_csv(self):
        assert _detect_kind(b"", "text/csv") == "text"

    def test_markdown(self):
        assert _detect_kind(b"", "text/markdown") == "text"

    def test_json(self):
        assert _detect_kind(b"", "application/json") == "text"

    def test_unknown_no_magic(self):
        assert _detect_kind(b"\x00\x01\x02", "application/octet-stream") is None

    def test_mime_with_charset(self):
        """Content-type with charset parameter is still detected."""
        assert _detect_kind(b"", "application/pdf; charset=binary") == "pdf"


class TestDetectKindMagic:
    """Format detection via magic bytes when content-type is empty."""

    def test_pdf_magic(self):
        assert _detect_kind(b"%PDF-1.4 rest of data", "") == "pdf"

    def test_html_doctype_magic(self):
        assert _detect_kind(b"<!DOCTYPE html>", "") == "html"

    def test_html_tag_magic(self):
        assert _detect_kind(b"<html><body>hi</body></html>", "") == "html"

    def test_zip_magic_docx_or_xlsx(self):
        assert _detect_kind(b"PK\x03\x04extra", "") == "docx_or_xlsx"

    def test_no_magic_no_mime(self):
        assert _detect_kind(b"just random bytes", "") is None


class TestExtractText:
    """End-to-end extraction through extract_text()."""

    def test_plain_text(self):
        result = extract_text(b"hello world", "text/plain")
        assert result == "hello world"

    def test_html_strips_scripts(self):
        body = b"<html><body><p>Hello</p><script>evil</script></body></html>"
        result = extract_text(body, "text/html")
        assert result is not None
        assert "Hello" in result
        assert "evil" not in result

    def test_empty_body_returns_none(self):
        assert extract_text(b"", "text/plain") is None

    def test_unsupported_format_returns_none(self):
        assert extract_text(b"\x00\x01\x02", "application/octet-stream") is None

    def test_invalid_pdf_returns_none(self):
        result = extract_text(b"%PDF-1.4 invalid garbage", "application/pdf")
        assert result is None

    def test_json_treated_as_text(self):
        body = b'{"key": "value"}'
        result = extract_text(body, "application/json")
        assert result is not None
        assert '"key"' in result
        assert '"value"' in result

    def test_html_strips_style_tags(self):
        body = b"<html><body><style>body{color:red}</style><p>Content</p></body></html>"
        result = extract_text(body, "text/html")
        assert result is not None
        assert "Content" in result
        assert "color:red" not in result


class TestNormalise:
    """Whitespace normalisation helper."""

    def test_collapses_horizontal_whitespace(self):
        assert _normalise("hello   \t  world") == "hello world"

    def test_collapses_excessive_newlines(self):
        result = _normalise("a\n\n\n\n\nb")
        assert result == "a\n\nb"

    def test_strips_leading_trailing(self):
        assert _normalise("  hello  ") == "hello"

    def test_empty_string(self):
        assert _normalise("") == ""

    def test_preserves_single_newlines(self):
        assert _normalise("line1\nline2") == "line1\nline2"

    def test_preserves_double_newlines(self):
        assert _normalise("para1\n\npara2") == "para1\n\npara2"
