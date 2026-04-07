"""Tests for summarization LLM config validation and fallback behavior."""

from __future__ import annotations

import logging

import pytest

from core.config import BaseConfig, LLMProvider


class TestSummarizeLLMActivation:
    """Test activation when all three required fields are set."""

    def test_all_three_set_activates(self) -> None:
        config = BaseConfig(
            llm_api_key="main-key",
            summarize_llm_provider="mistral",
            summarize_llm_model="mistral-small-latest",
            summarize_llm_api_key="summarize-key",
        )
        assert config.summarize_llm_provider == LLMProvider.mistral
        assert config.summarize_llm_model == "mistral-small-latest"
        assert config.summarize_llm_api_key == "summarize-key"

    def test_none_set_silently_falls_back(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            config = BaseConfig(llm_api_key="main-key")
        assert config.summarize_llm_provider is None
        assert config.summarize_llm_model is None
        assert config.summarize_llm_api_key is None
        assert "Partial summarization LLM config" not in caplog.text


class TestPartialConfig:
    """Test partial config (1 or 2 of 3) logs warning and falls back."""

    def test_only_provider_set_warns(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="core.config"):
            BaseConfig(
                llm_api_key="main-key",
                summarize_llm_provider="mistral",
            )
        assert "Partial summarization LLM config" in caplog.text
        assert "SUMMARIZE_LLM_MODEL" in caplog.text
        assert "SUMMARIZE_LLM_API_KEY" in caplog.text

    def test_provider_and_model_set_warns(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="core.config"):
            BaseConfig(
                llm_api_key="main-key",
                summarize_llm_provider="openai",
                summarize_llm_model="gpt-4o-mini",
            )
        assert "Partial summarization LLM config" in caplog.text
        assert "SUMMARIZE_LLM_API_KEY" in caplog.text

    def test_only_api_key_set_warns(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="core.config"):
            BaseConfig(
                llm_api_key="main-key",
                summarize_llm_api_key="sum-key",
            )
        assert "Partial summarization LLM config" in caplog.text
        assert "SUMMARIZE_LLM_PROVIDER" in caplog.text
        assert "SUMMARIZE_LLM_MODEL" in caplog.text


class TestInvalidProvider:
    """Test invalid provider rejected at load time."""

    def test_invalid_summarize_provider(self) -> None:
        with pytest.raises(ValueError):
            BaseConfig(
                llm_api_key="main-key",
                summarize_llm_provider="gemini",
                summarize_llm_model="model",
                summarize_llm_api_key="key",
            )


class TestTemperatureValidation:
    """Test summarize LLM temperature validation."""

    def test_temperature_defaults_to_none_when_unset(self) -> None:
        config = BaseConfig(
            llm_api_key="main-key",
            summarize_llm_provider="mistral",
            summarize_llm_model="mistral-small-latest",
            summarize_llm_api_key="key",
        )
        assert config.summarize_llm_temperature is None

    def test_temperature_valid_range(self) -> None:
        config = BaseConfig(
            llm_api_key="key",
            summarize_llm_temperature=0.3,
        )
        assert config.summarize_llm_temperature == 0.3

    def test_temperature_too_high(self) -> None:
        with pytest.raises(ValueError, match="SUMMARIZE_LLM_TEMPERATURE"):
            BaseConfig(llm_api_key="key", summarize_llm_temperature=2.5)

    def test_temperature_negative(self) -> None:
        with pytest.raises(ValueError, match="SUMMARIZE_LLM_TEMPERATURE"):
            BaseConfig(llm_api_key="key", summarize_llm_temperature=-0.1)

    def test_temperature_boundary_values(self) -> None:
        config_low = BaseConfig(llm_api_key="key", summarize_llm_temperature=0.0)
        assert config_low.summarize_llm_temperature == 0.0
        config_high = BaseConfig(llm_api_key="key", summarize_llm_temperature=2.0)
        assert config_high.summarize_llm_temperature == 2.0
