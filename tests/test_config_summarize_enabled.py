"""Tests for the summarize_enabled config flag."""

from __future__ import annotations

from core.config import BaseConfig


class TestSummarizeEnabled:
    """Verify the summarize_enabled config flag defaults and behavior."""

    def test_summarize_enabled_defaults_to_true(self) -> None:
        config = BaseConfig(llm_api_key="test-key")
        assert config.summarize_enabled is True

    def test_summarize_enabled_can_be_set_false(self) -> None:
        config = BaseConfig(llm_api_key="test-key", summarize_enabled=False)
        assert config.summarize_enabled is False

    def test_summarize_enabled_can_be_set_true(self) -> None:
        config = BaseConfig(llm_api_key="test-key", summarize_enabled=True)
        assert config.summarize_enabled is True
