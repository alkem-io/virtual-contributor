"""Routing profiles — above all, that widening is not silently inert."""

from __future__ import annotations

import pytest

from core.domain.routing import (
    DEFAULT_ROUTING_TABLE,
    RetrievalProfile,
    effective_chunks,
)
from core.ports.query_router import RouteClass

#: The two chunk sizes that matter: the repo default and the deployed value.
CHUNK_SIZES = (2_000, 9_000)


class TestTableCompleteness:
    @pytest.mark.parametrize("route", list(RouteClass))
    def test_every_route_has_a_profile(self, route: RouteClass) -> None:
        assert route in DEFAULT_ROUTING_TABLE

    def test_only_conversational_skips_retrieval(self) -> None:
        for route, profile in DEFAULT_ROUTING_TABLE.items():
            expected = route is not RouteClass.CONVERSATIONAL
            assert profile.retrieve is expected


class TestWideningIsNotInert:
    """The failure this exists to prevent.

    At the deployed 9000-char chunk size the existing 20000-char budget admits
    only 2 chunks. A complex route that widened `n_results` from 5 to 10 while
    leaving the budget alone would deliver *exactly the same* context — a route
    that looks implemented and does nothing.
    """

    @pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
    def test_complex_delivers_strictly_more_context_than_simple(
        self, chunk_size: int,
    ) -> None:
        simple = effective_chunks(DEFAULT_ROUTING_TABLE[RouteClass.SIMPLE], chunk_size)
        complex_ = effective_chunks(
            DEFAULT_ROUTING_TABLE[RouteClass.COMPLEX], chunk_size,
        )
        assert complex_ > simple, (
            f"at chunk_size={chunk_size}, complex delivers {complex_} chunks and "
            f"simple delivers {simple} — the widening is inert"
        )

    @pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
    def test_complex_beats_moderate_too(self, chunk_size: int) -> None:
        moderate = effective_chunks(
            DEFAULT_ROUTING_TABLE[RouteClass.MODERATE], chunk_size,
        )
        complex_ = effective_chunks(
            DEFAULT_ROUTING_TABLE[RouteClass.COMPLEX], chunk_size,
        )
        assert complex_ > moderate

    def test_widening_width_alone_would_have_been_inert(self) -> None:
        """Demonstrates why the budget is part of the profile.

        Same width increase, default budget: no change at the deployed chunk
        size. This is the counterfactual the design avoids.
        """
        naive = RetrievalProfile(
            retrieve=True, n_results=10, score_threshold=0.3,
            max_context_chars=20_000,
        )
        baseline = DEFAULT_ROUTING_TABLE[RouteClass.SIMPLE]
        assert effective_chunks(naive, 9_000) == effective_chunks(baseline, 9_000)


class TestSimpleIsNeverSlower:
    def test_simple_retrieves_no_more_than_today(self) -> None:
        """A simple query must not become more expensive than it is now."""
        moderate = DEFAULT_ROUTING_TABLE[RouteClass.MODERATE]
        simple = DEFAULT_ROUTING_TABLE[RouteClass.SIMPLE]
        assert simple.n_results <= moderate.n_results
        assert simple.max_context_chars <= moderate.max_context_chars


class TestModerateIsTodaysBehaviour:
    def test_moderate_matches_develop_defaults(self) -> None:
        """Unrecognised input routes here, so it must be exactly today.

        If this drifts, the classifier's fallback silently stops being a
        no-op and every unmatched question changes behaviour.
        """
        moderate = DEFAULT_ROUTING_TABLE[RouteClass.MODERATE]
        assert moderate.n_results == 5
        assert moderate.score_threshold == 0.3
        assert moderate.max_context_chars == 20_000


class TestEffectiveChunks:
    def test_conversational_delivers_nothing(self) -> None:
        profile = DEFAULT_ROUTING_TABLE[RouteClass.CONVERSATIONAL]
        assert effective_chunks(profile, 9_000) == 0

    def test_budget_bounds_width(self) -> None:
        profile = RetrievalProfile(True, 100, 0.3, 20_000)
        assert effective_chunks(profile, 9_000) == 2

    def test_width_bounds_budget(self) -> None:
        profile = RetrievalProfile(True, 2, 0.3, 1_000_000)
        assert effective_chunks(profile, 9_000) == 2

    def test_zero_chunk_size_does_not_divide_by_zero(self) -> None:
        assert effective_chunks(RetrievalProfile(True, 5, 0.3, 20_000), 0) == 5
