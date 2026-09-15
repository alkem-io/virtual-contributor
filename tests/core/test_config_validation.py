"""Tests for config validation: backward compat, missing key, invalid ranges, defaults."""

from __future__ import annotations

import logging

import pytest

from core.config import BaseConfig, IngestSpaceConfig, LLMProvider


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

    def test_summarize_concurrency_negative(self) -> None:
        with pytest.raises(ValueError, match="SUMMARIZE_CONCURRENCY"):
            BaseConfig(llm_api_key="key", summarize_concurrency=-1)

    def test_summarize_concurrency_zero_valid(self) -> None:
        config = BaseConfig(llm_api_key="key", summarize_concurrency=0)
        assert config.summarize_concurrency == 0

    def test_summarize_enabled_default_true(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.summarize_enabled is True

    def test_summarize_enabled_false(self) -> None:
        config = BaseConfig(llm_api_key="key", summarize_enabled=False)
        assert config.summarize_enabled is False


class TestIngestSizingConfiguration:
    """Test sizing validation and startup injection for space ingestion."""

    def test_space_defaults_are_valid_and_proportional(self) -> None:
        config = IngestSpaceConfig(llm_api_key="key")

        assert config.chunk_size == 2500
        assert config.chunk_overlap == 300
        assert 0.10 <= config.chunk_overlap / config.chunk_size <= 0.15

    def test_summary_defaults_match_embedding_target(self) -> None:
        from core.domain.pipeline import (
            BodyOfKnowledgeSummaryStep,
            DocumentSummaryStep,
        )
        from tests.conftest import MockLLMPort

        llm = MockLLMPort()
        assert BaseConfig(llm_api_key="key").summary_length == 2500
        assert DocumentSummaryStep(llm)._summary_length == 2500
        assert BodyOfKnowledgeSummaryStep(llm)._summary_length == 2500

    @pytest.mark.parametrize(
        ("values", "setting"),
        [
            ({"chunk_size": 0}, "CHUNK_SIZE"),
            ({"chunk_overlap": -1}, "CHUNK_OVERLAP"),
            ({"chunk_size": 300, "chunk_overlap": 300}, "CHUNK_OVERLAP"),
            ({"chunk_size": 300, "chunk_overlap": 301}, "CHUNK_OVERLAP"),
            ({"summary_length": 0}, "SUMMARY_LENGTH"),
        ],
    )
    def test_rejects_invalid_sizing_values(
        self,
        values: dict[str, int],
        setting: str,
    ) -> None:
        with pytest.raises(ValueError, match=setting) as exc_info:
            BaseConfig(llm_api_key="key", **values)

        assert str(next(iter(values.values()))) in str(exc_info.value)

    def test_main_injects_non_default_sizing_values(self) -> None:
        from main import _inject_plugin_config

        class SizingPlugin:
            def __init__(
                self,
                *,
                chunk_size: int = 0,
                chunk_overlap: int = 0,
                summary_length: int = 0,
            ) -> None:
                self.chunk_size = chunk_size
                self.chunk_overlap = chunk_overlap
                self.summary_length = summary_length

        config = IngestSpaceConfig(
            llm_api_key="key",
            chunk_size=137,
            chunk_overlap=11,
            summary_length=911,
        )
        deps: dict[str, object] = {}

        _inject_plugin_config(
            deps,
            SizingPlugin,
            config,
            summarize_llm=None,
            bok_llm=None,
        )

        plugin = SizingPlugin(**deps)
        assert (plugin.chunk_size, plugin.chunk_overlap, plugin.summary_length) == (
            137,
            11,
            911,
        )

    def test_main_loads_space_specific_sizing_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from main import _load_config

        monkeypatch.setenv("PLUGIN_TYPE", "ingest-space")
        monkeypatch.setenv("LLM_API_KEY", "key")
        monkeypatch.setenv("CHUNK_SIZE", "137")
        monkeypatch.setenv("CHUNK_OVERLAP", "11")
        monkeypatch.setenv("SUMMARY_LENGTH", "911")

        config = _load_config()

        assert isinstance(config, IngestSpaceConfig)
        assert (config.chunk_size, config.chunk_overlap, config.summary_length) == (
            137,
            11,
            911,
        )

    def test_startup_log_reports_effective_sizing(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from main import _log_config

        config = IngestSpaceConfig(
            llm_api_key="key",
            chunk_size=137,
            chunk_overlap=11,
            summary_length=911,
        )

        with caplog.at_level(logging.INFO, logger="main"):
            _log_config(config)

        assert "Config: CHUNK_SIZE=137" in caplog.messages
        assert "Config: CHUNK_OVERLAP=11" in caplog.messages
        assert "Config: SUMMARY_LENGTH=911" in caplog.messages


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


class TestIngestSizingBounds:
    """SEC-1: startup must reject sizing that amplifies embedding volume."""

    def test_overlap_above_half_chunk_size_is_rejected(self):
        import pytest

        from core.config import IngestSpaceConfig

        # 2499/2500 embeds ~238x the corpus — startup is the only place this
        # can be caught, since the ingest run itself has a multi-hour budget.
        with pytest.raises(ValueError, match="must not exceed half of CHUNK_SIZE"):
            IngestSpaceConfig(
                llm_base_url="http://local", chunk_size=2500, chunk_overlap=2499
            )
        with pytest.raises(ValueError, match="must not exceed half of CHUNK_SIZE"):
            IngestSpaceConfig(
                llm_base_url="http://local", chunk_size=2500, chunk_overlap=1251
            )

    def test_overlap_at_exactly_half_is_accepted(self):
        from core.config import IngestSpaceConfig

        config = IngestSpaceConfig(
            llm_base_url="http://local", chunk_size=2500, chunk_overlap=1250
        )
        assert config.chunk_overlap == 1250

    def test_chunk_size_ceiling_is_enforced(self):
        import pytest

        from core.config import MAX_CHUNK_SIZE, IngestSpaceConfig

        with pytest.raises(ValueError, match="must not exceed"):
            IngestSpaceConfig(
                llm_base_url="http://local", chunk_size=MAX_CHUNK_SIZE + 1
            )


class TestPluginTypeResolution:
    """SEC-2: plugin-type resolution must honour the .env binding."""

    def test_env_file_plugin_type_selects_space_config(self, tmp_path, monkeypatch):
        from main import _load_config

        monkeypatch.delenv("PLUGIN_TYPE", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "PLUGIN_TYPE=ingest-space\nLLM_BASE_URL=http://local\n"
        )

        config = _load_config()

        # A raw os.environ read would miss this and silently ingest at the
        # shared 2000/400 defaults instead of the space-tuned 2500/300.
        assert type(config).__name__ == "IngestSpaceConfig"
        assert config.chunk_size == 2500

    def test_probe_shares_base_config_env_binding(self):
        """sec-vc-5: the probe must not drift from BaseConfig's binding."""
        from core.config import BaseConfig
        from main import _PluginTypeProbe

        assert _PluginTypeProbe.model_config == BaseConfig.model_config


def test_embedding_retry_and_deadline_limits_are_validated() -> None:
    with pytest.raises(ValueError):
        BaseConfig(llm_base_url="http://local", embeddings_max_attempts=6)
    with pytest.raises(ValueError):
        BaseConfig(llm_base_url="http://local", embeddings_attempt_timeout_seconds=46, embeddings_total_deadline_seconds=45)


def test_rewrite_utf8_cap_cannot_exceed_embedding_input_cap() -> None:
    with pytest.raises(ValueError):
        BaseConfig(llm_base_url="http://local", embeddings_query_max_utf8_bytes=4, query_rewrite_max_utf8_bytes=5)


def test_embedding_limit_defaults_are_bounded() -> None:
    config = BaseConfig(llm_base_url="http://local")
    assert 1 <= config.embeddings_max_attempts <= 5 and config.embeddings_attempt_timeout_seconds <= config.embeddings_total_deadline_seconds <= config.pipeline_timeout
