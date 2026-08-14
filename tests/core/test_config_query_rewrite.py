"""Config for the query-rewrite gate.

The defaults matter more than the overrides: an unconfigured deployment must
behave exactly as develop did, so the gate is opt-in and the validation
allowance is permissive.
"""

from __future__ import annotations

import pytest

from core.config import BaseConfig

#: BaseConfig requires a provider key; unrelated to this feature.
_REQUIRED = {"llm_api_key": "test-key"}


class TestDefaultsReproduceDevelop:
    def test_gating_is_off_by_default(self) -> None:
        """With no policy built, every turn with history is still rewritten."""
        assert BaseConfig(**_REQUIRED).query_rewrite_gating_enabled is False

    def test_the_expansion_allowance_defaults_to_the_measured_value(self) -> None:
        assert BaseConfig(**_REQUIRED).query_rewrite_max_expansion_ratio == 8.0


class TestOverridesAreAccepted:
    @pytest.mark.parametrize("ratio", [1.5, 4.0, 8.0, 20.0])
    def test_a_valid_ratio_is_accepted(self, ratio: float) -> None:
        config = BaseConfig(**_REQUIRED, query_rewrite_max_expansion_ratio=ratio)
        assert config.query_rewrite_max_expansion_ratio == ratio

    def test_gating_can_be_enabled(self) -> None:
        assert BaseConfig(
            **_REQUIRED, query_rewrite_gating_enabled=True
        ).query_rewrite_gating_enabled is True


class TestInvalidRatioIsRejected:
    @pytest.mark.parametrize("ratio", [1.0, 0.5, 0.0, -1.0])
    def test_a_ratio_at_or_below_one_raises(self, ratio: float) -> None:
        """A ratio <= 1 rejects every rewrite longer than the original — which
        is what resolving a follow-up normally produces — so the gate would
        silently discard all of them and always fall back."""
        with pytest.raises(ValueError, match="QUERY_REWRITE_MAX_EXPANSION_RATIO"):
            BaseConfig(**_REQUIRED, query_rewrite_max_expansion_ratio=ratio)


class TestNonFiniteRatiosAreRejected:
    """`inf`, `nan` and absurd finite values all pass a bare `> 1.0` check and
    silently disable the length bound this feature exists to enforce.

    `nan` is the worst: every comparison against it is False, so the check is
    not merely large but structurally unreachable, while startup logs a
    plausible-looking value.
    """

    @pytest.mark.parametrize("ratio", [float("inf"), float("nan"), 1e308, 1e400])
    def test_a_non_finite_or_absurd_ratio_raises(self, ratio: float) -> None:
        with pytest.raises(ValueError, match="QUERY_REWRITE_MAX_EXPANSION_RATIO"):
            BaseConfig(**_REQUIRED, query_rewrite_max_expansion_ratio=ratio)

    def test_the_upper_bound_is_enforced(self) -> None:
        assert BaseConfig(
            **_REQUIRED, query_rewrite_max_expansion_ratio=100.0
        ).query_rewrite_max_expansion_ratio == 100.0
        with pytest.raises(ValueError):
            BaseConfig(**_REQUIRED, query_rewrite_max_expansion_ratio=101.0)
