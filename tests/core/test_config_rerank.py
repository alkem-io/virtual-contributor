"""Re-ranking configuration: defaults, and failing loudly on bad values.

A bad weight or an incoherent candidate/top-K pair would not crash anything.
It would just make answers quietly worse, with nothing in the logs tying the
change to a config edit. So these are startup errors that name the variable.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import BaseConfig
from core.domain.rerank import LexicalReranker


def _config(**overrides: object) -> BaseConfig:
    return BaseConfig(llm_api_key="test-key", **overrides)  # type: ignore[arg-type]


class TestDefaults:
    def test_rerank_is_off_by_default(self) -> None:
        """Re-ranking changes what every answer is grounded in.

        That is opted into, never inherited by an existing deployment.
        """
        assert _config().rerank_enabled is False

    def test_candidate_and_top_k_defaults(self) -> None:
        config = _config()
        assert config.rerank_candidate_n == 20
        assert config.rerank_top_k == 5

    def test_default_weight_matches_the_reranker_and_clears_the_boundary(self) -> None:
        """Config and domain must not drift apart on this value.

        And it must stay above 0.5 — at exactly the midpoint the blend cannot
        promote a worst-vector candidate however well it matches.
        """
        assert _config().rerank_lexical_weight == LexicalReranker.DEFAULT_LEXICAL_WEIGHT
        assert _config().rerank_lexical_weight > 0.5


class TestValidation:
    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive_top_k(self, value: int) -> None:
        with pytest.raises(ValidationError, match="RERANK_TOP_K"):
            _config(rerank_top_k=value)

    @pytest.mark.parametrize("value", [0, -5])
    def test_rejects_non_positive_candidate_n(self, value: int) -> None:
        with pytest.raises(ValidationError, match="RERANK_CANDIDATE_N"):
            _config(rerank_candidate_n=value)

    def test_rejects_fewer_candidates_than_results(self) -> None:
        """Keeping more than we fetch is incoherent — nothing to choose between."""
        with pytest.raises(ValidationError, match="RERANK_CANDIDATE_N"):
            _config(rerank_candidate_n=3, rerank_top_k=10)

    @pytest.mark.parametrize("value", [-0.1, 1.1, 2.0])
    def test_rejects_weight_outside_unit_interval(self, value: float) -> None:
        with pytest.raises(ValidationError, match="RERANK_LEXICAL_WEIGHT"):
            _config(rerank_lexical_weight=value)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite_weight(self, value: float) -> None:
        """NaN and inf must not slip through.

        NaN is caught by the same range check, because every comparison
        against NaN is False. Asserted so that stays true if the check is ever
        rewritten — a NaN weight would make the ordering arbitrary.
        """
        with pytest.raises(ValidationError, match="RERANK_LEXICAL_WEIGHT"):
            _config(rerank_lexical_weight=value)

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_accepts_valid_boundaries(self, value: float) -> None:
        assert _config(rerank_lexical_weight=value).rerank_lexical_weight == value

    def test_equal_candidate_and_top_k_is_valid(self) -> None:
        config = _config(rerank_candidate_n=5, rerank_top_k=5)
        assert config.rerank_candidate_n == config.rerank_top_k
