"""Routing configuration: defaults, validation, and the built profile table."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import BaseConfig
from core.domain.routing import effective_chunks
from core.ports.query_router import RouteClass
from main import _build_routing_table

#: The deployed ingest chunk size — the regime where inert widening bites.
DEPLOYED_CHUNK_SIZE = 9_000


def _config(**overrides: object) -> BaseConfig:
    return BaseConfig(llm_api_key="test-key", **overrides)  # type: ignore[arg-type]


def _table(config: BaseConfig) -> dict:
    """Build with the plugin's effective knobs, as main.py does."""
    return _build_routing_table(
        config,
        n_results=config.retrieval_n_results,
        score_threshold=config.retrieval_score_threshold,
        max_context_chars=config.max_context_chars,
    )


class TestDefaults:
    def test_routing_is_off_by_default(self) -> None:
        """It changes what every answer is grounded in — opt in, never inherit."""
        assert BaseConfig.model_fields["routing_enabled"].default is False
        assert _config().routing_enabled is False

    def test_profile_defaults(self) -> None:
        config = _config()
        assert config.routing_simple_n_results == 3
        assert config.routing_complex_n_results == 10
        assert config.routing_complex_context_chars == 40_000


class TestValidation:
    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive_simple_width(self, value: int) -> None:
        with pytest.raises(ValidationError, match="ROUTING_SIMPLE_N_RESULTS"):
            _config(routing_simple_n_results=value)

    @pytest.mark.parametrize("value", [0, -5])
    def test_rejects_non_positive_complex_width(self, value: int) -> None:
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_N_RESULTS"):
            _config(routing_complex_n_results=value)

    @pytest.mark.parametrize("value", [0, -100])
    def test_rejects_non_positive_complex_budget(self, value: int) -> None:
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_CONTEXT_CHARS"):
            _config(routing_complex_context_chars=value)

    def test_rejects_complex_narrower_than_simple(self) -> None:
        """The route meant to see more must not see less.

        Simple stays within RETRIEVAL_N_RESULTS here so this isolates the
        ordering rule rather than tripping the "never slower than today" one.
        """
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_N_RESULTS"):
            _config(routing_simple_n_results=4, routing_complex_n_results=2)

    def test_rejects_simple_wider_than_the_global_default(self) -> None:
        """A simple query must never become slower than it is today.

        Documented on the field and in .env.example — enforced here so the
        promise is not merely written down.
        """
        with pytest.raises(ValidationError, match="ROUTING_SIMPLE_N_RESULTS"):
            _config(routing_simple_n_results=99, routing_complex_n_results=99)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"routing_complex_n_results": 10_000},
            {"routing_complex_context_chars": 10**12},
        ],
    )
    def test_rejects_absurd_upper_values(self, overrides: dict) -> None:
        """An extra zero should not start the pod and degrade it under load."""
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX"):
            _config(**overrides)

    def test_equal_widths_are_valid(self) -> None:
        config = _config(routing_simple_n_results=5, routing_complex_n_results=5)
        assert config.routing_complex_n_results == config.routing_simple_n_results


class TestBuiltRoutingTable:
    def test_every_route_has_a_profile(self) -> None:
        table = _table(_config())
        for route in RouteClass:
            assert route in table

    def test_only_conversational_skips_retrieval(self) -> None:
        table = _table(_config())
        for route, profile in table.items():
            assert profile.retrieve is (route is not RouteClass.CONVERSATIONAL)

    def test_moderate_mirrors_todays_defaults(self) -> None:
        """Unrecognised questions land here, so it must be exactly today.

        If this drifts, the classifier's fallback silently stops being a no-op
        and every unmatched question changes behaviour.
        """
        config = _config(expert_min_score=0.1, expert_n_results=8)
        moderate = _build_routing_table(
            config,
            n_results=config.expert_n_results,
            score_threshold=config.expert_min_score,
            max_context_chars=config.max_context_chars,
        )[RouteClass.MODERATE]
        # The PLUGIN's settings, not the deprecated globals. Production sets
        # EXPERT_MIN_SCORE=0.1 and never sets RETRIEVAL_SCORE_THRESHOLD, so
        # building from the global would impose 0.3 on every routed query the
        # moment routing was switched on.
        assert moderate.n_results == 8
        assert moderate.score_threshold == 0.1
        assert moderate.max_context_chars == config.max_context_chars

    def test_complex_is_not_inert_at_the_deployed_chunk_size(self) -> None:
        """The whole reason the budget is configurable alongside the width.

        With the default 20000-char budget, widening from 3 to 10 delivers the
        same 2 chunks at a 9000-char chunk size — a route that looks
        implemented and does nothing.
        """
        table = _table(_config())
        simple = effective_chunks(table[RouteClass.SIMPLE], DEPLOYED_CHUNK_SIZE)
        complex_ = effective_chunks(table[RouteClass.COMPLEX], DEPLOYED_CHUNK_SIZE)
        assert complex_ > simple

    def test_simple_is_never_wider_than_the_default(self) -> None:
        config = _config()
        simple = _table(config)[RouteClass.SIMPLE]
        assert simple.n_results <= config.retrieval_n_results


class TestProfilesInheritThePluginsSettings:
    """corr-vc-1: production runs EXPERT_MIN_SCORE=0.1, not the 0.3 global."""

    def test_threshold_comes_from_the_plugin_not_the_global(self) -> None:
        config = _config(expert_min_score=0.1)
        table = _build_routing_table(
            config,
            n_results=config.expert_n_results,
            score_threshold=config.expert_min_score,
            max_context_chars=config.max_context_chars,
        )
        assert config.retrieval_score_threshold == 0.3   # the global default
        for profile in table.values():
            assert profile.score_threshold == 0.1

    def test_complex_is_never_narrower_than_the_plugins_width(self) -> None:
        """A tuned width above the complex default must not be reduced."""
        config = _config()
        table = _build_routing_table(
            config, n_results=20, score_threshold=0.3,
            max_context_chars=config.max_context_chars,
        )
        assert table[RouteClass.COMPLEX].n_results >= 20
        assert table[RouteClass.SIMPLE].n_results <= 20


class TestDisabledRoutingCannotStopThePod:
    """A feature that is off by default must not be able to refuse a boot.

    `ROUTING_COMPLEX_CONTEXT_CHARS` is compared against `MAX_CONTEXT_CHARS`,
    which is **not** a routing setting. With routing disabled, an existing
    deployment running `MAX_CONTEXT_CHARS=2000` — perfectly valid on develop —
    was rejected at startup by the shipped `40000` default, even though no
    routing code would ever read it.
    """

    def test_a_tight_context_budget_boots_when_routing_is_off(self) -> None:
        config = _config(max_context_chars=2_000)
        assert config.routing_enabled is False
        assert config.max_context_chars == 2_000

    def test_the_same_config_is_rejected_when_routing_is_on(self) -> None:
        """The check is not removed — only scoped to when it governs anything."""
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_CONTEXT_CHARS"):
            _config(max_context_chars=2_000, routing_enabled=True)

    def test_absolute_routing_validation_still_applies_when_disabled(self) -> None:
        """Only the *relational* check is scoped. A nonsensical value on its
        own is still a misconfiguration worth failing on."""
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_N_RESULTS"):
            _config(routing_complex_n_results=0)
        with pytest.raises(ValidationError, match="ROUTING_COMPLEX_CONTEXT_CHARS"):
            _config(routing_complex_context_chars=0)

    def test_defaults_are_coherent_with_routing_enabled(self) -> None:
        assert _config(routing_enabled=True).routing_enabled is True
