"""Tests for config validation: backward compat, missing key, invalid ranges, defaults."""

from __future__ import annotations

import pytest

from core.config import BaseConfig, LLMProvider


class TestBackwardCompatibility:
    """Test backward-compat alias resolution (FR-009)."""

    def test_mistral_api_key_fallback(self) -> None:
        config = BaseConfig(mistral_api_key="legacy-key")
        assert config.llm_api_key == "legacy-key"
        assert config.llm_provider == LLMProvider.mistral

    def test_mistral_model_name_fallback(self) -> None:
        config = BaseConfig(
            mistral_api_key="key",
            mistral_model_name="mistral-small-latest",
        )
        assert config.llm_model == "mistral-small-latest"

    def test_llm_api_key_takes_precedence(self) -> None:
        config = BaseConfig(
            llm_api_key="new-key",
            mistral_api_key="legacy-key",
        )
        assert config.llm_api_key == "new-key"

    def test_llm_model_takes_precedence(self) -> None:
        config = BaseConfig(
            llm_api_key="key",
            llm_model="mistral-large-latest",
            mistral_model_name="mistral-small-latest",
        )
        assert config.llm_model == "mistral-large-latest"


class TestDefaultProvider:
    """Test default provider is mistral."""

    def test_default_provider(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.llm_provider == LLMProvider.mistral


class TestMissingApiKey:
    """Test missing API key raises error."""

    def test_no_key_no_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="LLM_API_KEY is required"):
            BaseConfig(llm_provider="openai")

    def test_base_url_allows_no_key(self) -> None:
        config = BaseConfig(
            llm_provider="openai",
            llm_base_url="http://localhost:8000/v1",
        )
        assert config.llm_api_key is None
        assert config.llm_base_url == "http://localhost:8000/v1"


class TestInvalidRanges:
    """Test validation of generation parameter ranges."""

    def test_temperature_too_high(self) -> None:
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            BaseConfig(llm_api_key="key", llm_temperature=3.0)

    def test_temperature_negative(self) -> None:
        with pytest.raises(ValueError, match="LLM_TEMPERATURE"):
            BaseConfig(llm_api_key="key", llm_temperature=-0.1)

    def test_temperature_valid_boundary(self) -> None:
        config = BaseConfig(llm_api_key="key", llm_temperature=0.0)
        assert config.llm_temperature == 0.0
        config2 = BaseConfig(llm_api_key="key", llm_temperature=2.0)
        assert config2.llm_temperature == 2.0

    def test_max_tokens_zero(self) -> None:
        with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
            BaseConfig(llm_api_key="key", llm_max_tokens=0)

    def test_max_tokens_negative(self) -> None:
        with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
            BaseConfig(llm_api_key="key", llm_max_tokens=-10)

    def test_top_p_too_high(self) -> None:
        with pytest.raises(ValueError, match="LLM_TOP_P"):
            BaseConfig(llm_api_key="key", llm_top_p=1.5)

    def test_top_p_negative(self) -> None:
        with pytest.raises(ValueError, match="LLM_TOP_P"):
            BaseConfig(llm_api_key="key", llm_top_p=-0.1)

    def test_timeout_zero(self) -> None:
        with pytest.raises(ValueError, match="LLM_TIMEOUT"):
            BaseConfig(llm_api_key="key", llm_timeout=0)


class TestPerPluginOverride:
    """Test per-plugin provider override via env vars."""

    def test_plugin_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import _resolve_plugin_llm_config

        monkeypatch.setenv("GUIDANCE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("GUIDANCE_LLM_API_KEY", "plugin-key")
        config = BaseConfig(
            plugin_type="guidance",
            llm_api_key="global-key",
            llm_provider="mistral",
        )
        resolved = _resolve_plugin_llm_config(config)
        assert resolved.llm_provider == LLMProvider.openai
        assert resolved.llm_api_key == "plugin-key"

    def test_fallback_to_global(self) -> None:
        from main import _resolve_plugin_llm_config

        config = BaseConfig(
            plugin_type="guidance",
            llm_api_key="global-key",
            llm_provider="mistral",
        )
        resolved = _resolve_plugin_llm_config(config)
        assert resolved.llm_provider == LLMProvider.mistral
        assert resolved.llm_api_key == "global-key"

    def test_plugin_generation_params_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from main import _resolve_plugin_llm_config

        monkeypatch.setenv("EXPERT_LLM_TEMPERATURE", "0.3")
        monkeypatch.setenv("EXPERT_LLM_MAX_TOKENS", "512")
        monkeypatch.setenv("EXPERT_LLM_TOP_P", "0.8")
        config = BaseConfig(
            plugin_type="expert",
            llm_api_key="key",
            llm_temperature=0.7,
            llm_max_tokens=4096,
        )
        resolved = _resolve_plugin_llm_config(config)
        assert resolved.llm_temperature == 0.3
        assert resolved.llm_max_tokens == 512
        assert resolved.llm_top_p == 0.8

    def test_no_plugin_type_returns_config_unchanged(self) -> None:
        from main import _resolve_plugin_llm_config

        config = BaseConfig(llm_api_key="key")
        resolved = _resolve_plugin_llm_config(config)
        assert resolved is config


class TestUnsupportedProvider:
    """Test unsupported provider fail-fast (FR-008)."""

    def test_invalid_provider(self) -> None:
        with pytest.raises(ValueError):
            BaseConfig(llm_provider="gemini", llm_api_key="key")
