"""Hybrid retrieval configuration: defaults and startup rejection."""

from __future__ import annotations

import pytest

from core.config import BaseConfig


def _config(**overrides) -> BaseConfig:
    base = {"llm_api_key": "k", "llm_model": "m"}
    base.update(overrides)
    return BaseConfig(**base)  # type: ignore[arg-type]


class TestHybridDefaults:
    def test_hybrid_is_off_unless_asked_for(self):
        """It changes what every answer is grounded in — opt in, don't inherit."""
        assert _config().hybrid_retrieval_enabled is False

    def test_arms_are_equally_weighted_by_default(self):
        config = _config()
        assert config.hybrid_dense_weight == 1.0
        assert config.hybrid_lexical_weight == 1.0

    def test_fusion_constant_and_term_bounds_have_defaults(self):
        config = _config()
        assert config.hybrid_rrf_k == 60
        assert config.hybrid_max_terms == 8
        assert config.hybrid_min_term_len == 3


class TestHybridValidationAtStartup:
    """Bad values must fail the process, not silently degrade retrieval."""

    @pytest.mark.parametrize(
        ("field", "value", "fragment"),
        [
            ("hybrid_rrf_k", 0, "HYBRID_RRF_K"),
            ("hybrid_rrf_k", -1, "HYBRID_RRF_K"),
            ("hybrid_dense_weight", -0.1, "HYBRID_DENSE_WEIGHT"),
            ("hybrid_lexical_weight", -1.0, "HYBRID_LEXICAL_WEIGHT"),
            ("hybrid_max_terms", 0, "HYBRID_MAX_TERMS"),
            ("hybrid_min_term_len", 0, "HYBRID_MIN_TERM_LEN"),
        ],
    )
    def test_invalid_value_is_rejected(self, field, value, fragment):
        with pytest.raises(ValueError, match=fragment):
            _config(**{field: value})

    def test_both_weights_zero_is_rejected(self):
        """Every result would score 0 and the ordering would be arbitrary."""
        with pytest.raises(ValueError, match="must not both"):
            _config(hybrid_dense_weight=0.0, hybrid_lexical_weight=0.0)

    def test_one_weight_zero_is_allowed(self):
        """Muting an arm is a legitimate way to compare against the baseline."""
        assert _config(hybrid_lexical_weight=0.0).hybrid_lexical_weight == 0.0
        assert _config(hybrid_dense_weight=0.0).hybrid_dense_weight == 0.0
