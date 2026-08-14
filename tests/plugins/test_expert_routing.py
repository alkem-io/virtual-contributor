"""Expert routing: skipping, scaling, and the rollback.

Expert has TWO retrieval sites — `_handle_simple` and the `retrieve_node`
closure inside `_handle_with_graph`. The closure captures its settings from the
enclosing scope, so wiring one and forgetting the other would leave half the
traffic silently unrouted. Every behavioural test here runs against both.
"""

from __future__ import annotations

import pytest

from core.domain.rule_classifier import RuleQueryClassifier
from core.ports.query_router import RouteClass, RoutingDecision
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input

#: A prompt graph definition. The graph itself is mocked in these tests (as
#: the existing expert suite does) — what matters here is the `retrieve_node`
#: closure the plugin builds, which is captured and driven directly.
GRAPH = {
    "nodes": [{"name": "n1"}],
    "edges": [{"from": "START", "to": "END"}],
}


class _AlwaysRoute:
    """A classifier pinned to one route, to prove the port is swappable."""

    def __init__(self, route: RouteClass) -> None:
        self._route = route

    def classify(self, message: str) -> RoutingDecision:
        return RoutingDecision(self._route, "pinned for test")


class _Raises:
    def classify(self, message: str) -> RoutingDecision:
        raise RuntimeError("classifier exploded")


def _plugin(store: MockKnowledgeStorePort, **kwargs: object) -> ExpertPlugin:
    return ExpertPlugin(
        llm=MockLLMPort(response="an answer"),
        knowledge_store=store,
        **kwargs,  # type: ignore[arg-type]
    )


async def _run_graph_retrieve(
    plugin: ExpertPlugin, message: str,
) -> None:
    """Drive the graph path's retrieve_node without a real LangGraph.

    The existing expert suite mocks PromptGraph wholesale, which means the
    `retrieve_node` closure — where the graph path's retrieval actually happens
    — is never executed by it. Capturing and invoking the closure is what makes
    these assertions cover both paths rather than one path twice.
    """
    captured: dict = {}

    mock_graph = MagicMock()
    mock_graph.compile = MagicMock(
        side_effect=lambda **kw: captured.update(kw) or mock_graph,
    )
    mock_graph.invoke = AsyncMock(return_value={"final_answer": "ok"})

    with patch("core.domain.prompt_graph.PromptGraph") as MockPromptGraph:
        MockPromptGraph.from_definition.return_value = mock_graph
        await plugin.handle(make_input(message=message, promptGraph=GRAPH))

    retrieve_node = captured["special_nodes"]["retrieve"]
    await retrieve_node({"current_question": message})


class TestSmallTalkSkipsRetrieval:
    """US1 — nothing in a knowledge base answers "thanks"."""

    async def test_conversational_makes_zero_store_calls(self) -> None:
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        response = await plugin.handle(make_input(message="thanks!"))
        assert store.query_calls == []
        assert response is not None

    async def test_a_real_question_still_retrieves(self) -> None:
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        await plugin.handle(
            make_input(message="What is the mission of this space?"),
        )
        assert len(store.query_calls) == 1

    async def test_a_question_opening_with_thanks_still_retrieves(
        self,
    ) -> None:
        """The dangerous shape: acknowledgement then question."""
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        await plugin.handle(
            make_input(message="Thanks - who is the space lead?"),
        )
        assert len(store.query_calls) == 1


class TestDepthScales:
    """US2 — a comparison gets more evidence than a lookup."""

    async def test_complex_requests_more_than_simple(self) -> None:
        simple_store = MockKnowledgeStorePort()
        await _plugin(
            simple_store, query_router=RuleQueryClassifier(),
        ).handle(make_input(message="Who is the space lead?"))

        complex_store = MockKnowledgeStorePort()
        await _plugin(
            complex_store, query_router=RuleQueryClassifier(),
        ).handle(make_input(
            message="Compare the goals of subspace A and subspace B",
        ))

        assert complex_store.query_calls[0][2] > simple_store.query_calls[0][2]

    async def test_simple_is_never_wider_than_todays_default(
        self,
    ) -> None:
        """A simple query must not become more expensive than it is now."""
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, n_results=5, query_router=RuleQueryClassifier())
        await plugin.handle(make_input(message="Who is the space lead?"))
        assert store.query_calls[0][2] <= 5


class TestDisabledIsIdentical:
    """US3 — the primary rollback."""

    async def test_disabled_still_retrieves_for_small_talk(
        self,
    ) -> None:
        """Nothing is skipped when routing is off — that is the whole point."""
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, n_results=5)
        await plugin.handle(make_input(message="thanks!"))
        assert len(store.query_calls) == 1

    async def test_disabled_uses_configured_width_for_every_query(
        self,
    ) -> None:
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, n_results=7)
        for message in ("thanks", "who is the lead?", "compare A and B"):
            await plugin.handle(make_input(message=message))
        assert all(call[2] == 7 for call in store.query_calls)

    async def test_no_classification_happens_when_disabled(self) -> None:
        """Off means the classifier is never consulted, not consulted-and-ignored."""
        class _Tripwire:
            def classify(self, message: str) -> RoutingDecision:
                raise AssertionError("classifier ran while routing was disabled")

        store = MockKnowledgeStorePort()
        plugin = _plugin(store)          # no router injected
        plugin._query_router = None      # explicit: this is the disabled shape
        await plugin.handle(make_input(message="thanks!"))
        assert len(store.query_calls) == 1
        assert isinstance(_Tripwire(), object)


class TestFailureFallsBackToDefaults:
    async def test_a_raising_classifier_still_answers(self) -> None:
        """Classification is an optimisation, never a dependency of answering."""
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, n_results=5, query_router=_Raises())
        response = await plugin.handle(
            make_input(message="who is the space lead?"),
        )
        assert response is not None
        assert store.query_calls[0][2] == 5


class TestStrategyIsSwappable:
    """US4 — a different classifier changes behaviour with no plugin change."""

    async def test_substituted_classifier_drives_the_profile(self) -> None:
        simple_store = MockKnowledgeStorePort()
        await _plugin(
            simple_store, query_router=_AlwaysRoute(RouteClass.SIMPLE),
        ).handle(make_input(message="anything at all"))

        complex_store = MockKnowledgeStorePort()
        await _plugin(
            complex_store, query_router=_AlwaysRoute(RouteClass.COMPLEX),
        ).handle(make_input(message="anything at all"))

        assert complex_store.query_calls[0][2] > simple_store.query_calls[0][2]

    async def test_conversational_route_skips_regardless_of_wording(self) -> None:
        store = MockKnowledgeStorePort()
        await _plugin(
            store, query_router=_AlwaysRoute(RouteClass.CONVERSATIONAL),
        ).handle(make_input(message="what is the mission of this space?"))
        assert store.query_calls == []

    async def test_the_route_reason_is_logged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        with caplog.at_level(logging.INFO, logger="plugins.expert.plugin"):
            await plugin.handle(make_input(message="who is the space lead?"))
        assert any("Routed query as" in r.getMessage() for r in caplog.records)


class TestGraphPathRoutesToo:
    """R-4 — the closure is a separate retrieval site and must route as well.

    The existing expert suite mocks PromptGraph wholesale, so `retrieve_node`
    never executes in it. Wiring `_handle_simple` and forgetting the closure
    would leave every graph-driven query on today's behaviour, and no existing
    test would notice.
    """

    async def test_graph_path_skips_retrieval_for_small_talk(self) -> None:
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        await _run_graph_retrieve(plugin, "thanks!")
        assert store.query_calls == []

    async def test_graph_path_retrieves_for_a_real_question(self) -> None:
        store = MockKnowledgeStorePort()
        plugin = _plugin(store, query_router=RuleQueryClassifier())
        await _run_graph_retrieve(plugin, "What is the mission of this space?")
        assert len(store.query_calls) == 1

    async def test_graph_path_scales_width_with_complexity(self) -> None:
        simple_store = MockKnowledgeStorePort()
        await _run_graph_retrieve(
            _plugin(simple_store, query_router=RuleQueryClassifier()),
            "Who is the space lead?",
        )
        complex_store = MockKnowledgeStorePort()
        await _run_graph_retrieve(
            _plugin(complex_store, query_router=RuleQueryClassifier()),
            "Compare the goals of subspace A and subspace B",
        )
        assert complex_store.query_calls[0][2] > simple_store.query_calls[0][2]

    async def test_graph_path_disabled_still_retrieves_small_talk(self) -> None:
        store = MockKnowledgeStorePort()
        await _run_graph_retrieve(_plugin(store, n_results=7), "thanks!")
        assert len(store.query_calls) == 1
        assert store.query_calls[0][2] == 7
