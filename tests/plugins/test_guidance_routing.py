"""Guidance routing — and whether widened retrieval survives the funnel.

Guidance applies its width at TWO points: the per-collection query, and the
post-dedupe truncation. Applying the profile at only the first would fetch the
extra evidence and then throw it away at the second, leaving a "complex" route
that costs more and delivers the same context.
"""

from __future__ import annotations

import pytest

from core.domain.rule_classifier import RuleQueryClassifier
from core.ports.knowledge_store import QueryResult
from core.ports.query_router import RouteClass, RoutingDecision
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


class _AlwaysRoute:
    def __init__(self, route: RouteClass) -> None:
        self._route = route

    def classify(self, message: str) -> RoutingDecision:
        return RoutingDecision(self._route, "pinned for test")


class _Raises:
    def classify(self, message: str) -> RoutingDecision:
        raise RuntimeError("classifier exploded")


class _WideStore(MockKnowledgeStorePort):
    """Every chunk from a distinct page, so dedupe never binds.

    Short documents on purpose: this isolates the *width* path from the
    context-budget path, so a failure points at one of them rather than both.
    """

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        keep = n_results
        return QueryResult(
            documents=[[f"{collection} chunk {i}" for i in range(keep)]],
            metadatas=[[
                {"source": f"https://{collection}/page{i}", "title": f"p{i}"}
                for i in range(keep)
            ]],
            distances=[[0.05 + 0.001 * i for i in range(keep)]],
            ids=[[f"{collection}-{i}" for i in range(keep)]],
        )


def _plugin(store: MockKnowledgeStorePort, **kwargs: object) -> GuidancePlugin:
    return GuidancePlugin(
        llm=MockLLMPort(response="an answer"),
        knowledge_store=store,
        **kwargs,  # type: ignore[arg-type]
    )


class TestSmallTalkSkipsRetrieval:
    async def test_conversational_queries_no_collections(self) -> None:
        """All three collection queries are skipped, not run and discarded."""
        store = _WideStore()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        response = await plugin.handle(make_input(message="thanks!"))
        assert store.query_calls == []
        assert response is not None

    async def test_a_real_question_queries_all_three(self) -> None:
        store = _WideStore()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        await plugin.handle(make_input(message="What is the mission?"))
        assert len(store.query_calls) == 3


class TestDepthScales:
    async def test_complex_requests_more_per_collection(self) -> None:
        simple = _WideStore()
        await _plugin(simple, query_router=RuleQueryClassifier()).handle(
            make_input(message="Who is the space lead?"),
        )
        complex_ = _WideStore()
        await _plugin(complex_, query_router=RuleQueryClassifier()).handle(
            make_input(message="Compare subspace A and subspace B"),
        )
        assert complex_.query_calls[0][2] > simple.query_calls[0][2]

    async def test_widened_evidence_survives_the_funnel(self) -> None:
        """T014 / R-3 — the test that would have caught the 046 regression.

        Requesting more is worthless if truncation still cuts to the old width.
        Assert on the sources that actually reach the answer, not on what was
        requested from the store.
        """
        simple = _WideStore()
        simple_response = await _plugin(
            simple, query_router=_AlwaysRoute(RouteClass.SIMPLE),
        ).handle(make_input(message="anything"))

        complex_ = _WideStore()
        complex_response = await _plugin(
            complex_, query_router=_AlwaysRoute(RouteClass.COMPLEX),
        ).handle(make_input(message="anything"))

        assert len(complex_response.sources) > len(simple_response.sources), (
            f"complex delivered {len(complex_response.sources)} sources and "
            f"simple delivered {len(simple_response.sources)} — the widening "
            f"did not survive truncation"
        )

    async def test_sources_are_distinct_after_widening(self) -> None:
        """Widening must add real evidence, not duplicates."""
        store = _WideStore()
        response = await _plugin(
            store, query_router=_AlwaysRoute(RouteClass.COMPLEX),
        ).handle(make_input(message="anything"))
        uris = [s.uri for s in response.sources]
        assert len(set(uris)) == len(uris)


class TestDisabledIsIdentical:
    async def test_disabled_still_retrieves_for_small_talk(self) -> None:
        store = _WideStore()
        await _plugin(store, n_results=5).handle(make_input(message="thanks!"))
        assert len(store.query_calls) == 3

    async def test_disabled_uses_configured_width_for_every_query(self) -> None:
        store = _WideStore()
        plugin = _plugin(store, n_results=6)
        for message in ("thanks", "who is the lead?", "compare A and B"):
            await plugin.handle(make_input(message=message))
        assert all(call[2] == 6 for call in store.query_calls)


class TestFailureFallsBackToDefaults:
    async def test_a_raising_classifier_still_answers(self) -> None:
        store = _WideStore()
        plugin = _plugin(store, n_results=5, query_router=_Raises())
        response = await plugin.handle(make_input(message="who is the lead?"))
        assert response is not None
        assert all(call[2] == 5 for call in store.query_calls)


class TestStrategyIsSwappable:
    async def test_substituted_classifier_drives_the_profile(self) -> None:
        simple = _WideStore()
        await _plugin(simple, query_router=_AlwaysRoute(RouteClass.SIMPLE)).handle(
            make_input(message="anything at all"),
        )
        complex_ = _WideStore()
        await _plugin(complex_, query_router=_AlwaysRoute(RouteClass.COMPLEX)).handle(
            make_input(message="anything at all"),
        )
        assert complex_.query_calls[0][2] > simple.query_calls[0][2]

    async def test_the_route_reason_is_logged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        store = _WideStore()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        with caplog.at_level(logging.INFO, logger="plugins.guidance.plugin"):
            await plugin.handle(make_input(message="who is the space lead?"))
        assert any("Routed query as" in r.getMessage() for r in caplog.records)
