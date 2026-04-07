"""Tests for per-plugin retrieval config validation."""

from __future__ import annotations

import pytest

from core.config import BaseConfig


class TestExpertNResults:
    """Test expert_n_results validation."""

    def test_default_is_5(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.expert_n_results == 5

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="EXPERT_N_RESULTS"):
            BaseConfig(llm_api_key="key", expert_n_results=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="EXPERT_N_RESULTS"):
            BaseConfig(llm_api_key="key", expert_n_results=-1)

    def test_accepts_positive(self) -> None:
        config = BaseConfig(llm_api_key="key", expert_n_results=10)
        assert config.expert_n_results == 10


class TestGuidanceNResults:
    """Test guidance_n_results validation."""

    def test_default_is_5(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.guidance_n_results == 5

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="GUIDANCE_N_RESULTS"):
            BaseConfig(llm_api_key="key", guidance_n_results=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="GUIDANCE_N_RESULTS"):
            BaseConfig(llm_api_key="key", guidance_n_results=-1)


class TestExpertMinScore:
    """Test expert_min_score validation."""

    def test_default_is_0_3(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.expert_min_score == 0.3

    def test_rejects_above_1(self) -> None:
        with pytest.raises(ValueError, match="EXPERT_MIN_SCORE"):
            BaseConfig(llm_api_key="key", expert_min_score=1.5)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="EXPERT_MIN_SCORE"):
            BaseConfig(llm_api_key="key", expert_min_score=-0.1)

    def test_accepts_boundaries(self) -> None:
        config_low = BaseConfig(llm_api_key="key", expert_min_score=0.0)
        assert config_low.expert_min_score == 0.0
        config_high = BaseConfig(llm_api_key="key", expert_min_score=1.0)
        assert config_high.expert_min_score == 1.0


class TestGuidanceMinScore:
    """Test guidance_min_score validation."""

    def test_default_is_0_3(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.guidance_min_score == 0.3

    def test_rejects_above_1(self) -> None:
        with pytest.raises(ValueError, match="GUIDANCE_MIN_SCORE"):
            BaseConfig(llm_api_key="key", guidance_min_score=1.5)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="GUIDANCE_MIN_SCORE"):
            BaseConfig(llm_api_key="key", guidance_min_score=-0.1)


class TestMaxContextChars:
    """Test max_context_chars validation."""

    def test_default_is_20000(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.max_context_chars == 20000

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="MAX_CONTEXT_CHARS"):
            BaseConfig(llm_api_key="key", max_context_chars=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="MAX_CONTEXT_CHARS"):
            BaseConfig(llm_api_key="key", max_context_chars=-1)
