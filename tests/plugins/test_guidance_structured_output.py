"""Tests for structured output parsing edge cases in GuidancePlugin."""

from __future__ import annotations

from plugins.guidance.plugin import GuidancePlugin


class TestParseJsonSources:
    """Test _parse_json_sources handles provider-specific formatting."""

    def test_clean_json(self) -> None:
        text = '{"answer": "Hello", "source_scores": {"a": 0.9}}'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello", "source_scores": {"a": 0.9}}

    def test_fenced_json(self) -> None:
        text = '```json\n{"answer": "Hello"}\n```'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_fenced_json_no_language(self) -> None:
        text = '```\n{"answer": "Hello"}\n```'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_preamble_text_before_json(self) -> None:
        text = 'Here is the response:\n```json\n{"answer": "Hello"}\n```'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_preamble_text_before_bare_json(self) -> None:
        text = 'Sure, here is your answer:\n{"answer": "Hello"}'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_trailing_text_after_json(self) -> None:
        text = '{"answer": "Hello"}\n\nI hope this helps!'
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_malformed_json_returns_none(self) -> None:
        text = 'This is not JSON at all, just a regular response.'
        result = GuidancePlugin._parse_json_sources(text)
        assert result is None

    def test_empty_response_returns_none(self) -> None:
        result = GuidancePlugin._parse_json_sources("")
        assert result is None

    def test_nested_json(self) -> None:
        text = '{"answer": "Hello", "details": {"key": "value"}}'
        result = GuidancePlugin._parse_json_sources(text)
        assert result["details"] == {"key": "value"}

    def test_json_with_whitespace(self) -> None:
        text = '  \n  {"answer": "Hello"}  \n  '
        result = GuidancePlugin._parse_json_sources(text)
        assert result == {"answer": "Hello"}

    def test_multiple_fenced_blocks_uses_first(self) -> None:
        text = '```json\n{"answer": "first"}\n```\n\n```json\n{"answer": "second"}\n```'
        result = GuidancePlugin._parse_json_sources(text)
        assert result["answer"] == "first"
