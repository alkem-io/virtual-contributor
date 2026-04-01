"""Tests for provider factory: resolution, defaults, fail-fast, param passthrough."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.config import BaseConfig, LLMProvider
from core.provider_factory import create_llm_adapter, DEFAULT_MODELS

# Patch targets — lazy imports inside _get_model_class
_MISTRAL = "langchain_mistralai.ChatMistralAI"
_OPENAI = "langchain_openai.ChatOpenAI"
_ANTHROPIC = "langchain_anthropic.ChatAnthropic"


class TestProviderResolution:
    """Test that the factory resolves each supported provider."""

    @patch(_MISTRAL)
    def test_resolves_mistral(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="mistral", llm_api_key="key")
        adapter = create_llm_adapter(config)
        assert adapter is not None
        mock_cls.assert_called_once()

    @patch(_OPENAI)
    def test_resolves_openai(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key")
        adapter = create_llm_adapter(config)
        assert adapter is not None
        mock_cls.assert_called_once()

    @patch(_ANTHROPIC)
    def test_resolves_anthropic(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="anthropic", llm_api_key="key")
        adapter = create_llm_adapter(config)
        assert adapter is not None
        mock_cls.assert_called_once()


class TestDefaultModels:
    """Test default model names per provider (FR-013)."""

    @patch(_MISTRAL)
    def test_mistral_default_model(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="mistral", llm_api_key="key")
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == DEFAULT_MODELS[LLMProvider.mistral]

    @patch(_OPENAI)
    def test_openai_default_model(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key")
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == DEFAULT_MODELS[LLMProvider.openai]

    @patch(_ANTHROPIC)
    def test_anthropic_default_model(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="anthropic", llm_api_key="key")
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == DEFAULT_MODELS[LLMProvider.anthropic]

    @patch(_OPENAI)
    def test_custom_model_overrides_default(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key", llm_model="gpt-4-turbo")
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "gpt-4-turbo"


class TestGenerationParamPassthrough:
    """Test that generation params are passed to the LangChain constructor."""

    @patch(_OPENAI)
    def test_temperature_passthrough(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key", llm_temperature=0.5)
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["temperature"] == 0.5

    @patch(_OPENAI)
    def test_max_tokens_passthrough(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key", llm_max_tokens=2048)
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["max_tokens"] == 2048

    @patch(_OPENAI)
    def test_top_p_passthrough(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key", llm_top_p=0.9)
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["top_p"] == 0.9

    @patch(_OPENAI)
    def test_timeout_passthrough(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key", llm_timeout=60)
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["timeout"] == 60

    @patch(_OPENAI)
    def test_none_params_not_passed(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(llm_provider="openai", llm_api_key="key")
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert "temperature" not in call_kwargs
        assert "max_tokens" not in call_kwargs
        assert "top_p" not in call_kwargs


class TestUnsupportedProvider:
    """Test fail-fast on unsupported provider (FR-008)."""

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError):
            BaseConfig(llm_provider="gemini", llm_api_key="key")


class TestBaseUrlPassthrough:
    """Test base_url is passed to ChatOpenAI for local models."""

    @patch(_OPENAI)
    def test_base_url_passed(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        config = BaseConfig(
            llm_provider="openai",
            llm_api_key="key",
            llm_base_url="http://localhost:8000/v1",
        )
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:8000/v1"

    @patch(_OPENAI)
    def test_no_api_key_with_base_url(self, mock_cls: MagicMock) -> None:
        """Config validation skips API key requirement when base_url is set."""
        mock_cls.return_value = MagicMock()
        config = BaseConfig(
            llm_provider="openai",
            llm_base_url="http://localhost:8000/v1",
        )
        create_llm_adapter(config)
        call_kwargs = mock_cls.call_args[1]
        assert "api_key" not in call_kwargs
        assert call_kwargs["base_url"] == "http://localhost:8000/v1"
