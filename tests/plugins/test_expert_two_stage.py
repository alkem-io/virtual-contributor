"""In-process acceptance tests for opt-in two-stage expert retrieval.

The precision assertion below is a structural proxy over a seeded fake store;
it is explicitly not a RAGAS or representative-environment measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from core.ports.query_router import RouteClass, RoutingDecision
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


GRAPH = {"nodes": [{"name": "n"}], "edges": [{"from": "START", "to": "END"}]}


def _entries() -> list[dict]:
    return [
        {"id": "route-a", "document": "Alpha overview", "metadata": {"embeddingType": "overview", "spaceId": "a", "spaceName": "Alpha"}},
        {"id": "a-1", "document": "Alpha liability detail", "metadata": {"embeddingType": "chunk", "spaceId": "a", "spaceName": "Alpha", "source": "a-1"}},
        {"id": "a-2", "document": "Alpha evidence", "metadata": {"embeddingType": "chunk", "spaceId": "a", "source": "a-2"}},
        {"id": "b-1", "document": "Beta liability noise", "metadata": {"embeddingType": "chunk", "spaceId": "b", "source": "b-1"}},
    ]


def _store() -> MockKnowledgeStorePort:
    store = MockKnowledgeStorePort()
    store.collections["c-knowledge"] = _entries()
    return store


def _plugin(store: MockKnowledgeStorePort, **kwargs: object) -> ExpertPlugin:
    return ExpertPlugin(
        MockLLMPort(response="answer"), store, n_results=5,
        hierarchical_retrieval_enabled=True, **kwargs,
    )


def _event() -> object:
    return make_input(message="What is the Alpha liability decision?", bodyOfKnowledgeID="c")


async def _graph_retrieve(plugin: ExpertPlugin) -> None:
    captured: dict = {}
    graph = MagicMock()
    graph.compile.side_effect = lambda **kw: captured.update(kw) or graph
    graph.invoke = AsyncMock(return_value={"final_answer": "answer"})
    with patch("core.domain.prompt_graph.PromptGraph") as graph_type:
        graph_type.from_definition.return_value = graph
        await plugin.handle(make_input(message="Alpha liability", bodyOfKnowledgeID="c", promptGraph=GRAPH))
    await captured["special_nodes"]["retrieve"]({"current_question": "Alpha liability"})


async def test_simple_scoped_stage_uses_detail_predicate() -> None:
    store = _store()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]
    assert len(store.query_calls) == 2
    assert "spaceId" in str(store.query_calls[1][3]) and "overview" in str(store.query_calls[1][3])


async def test_graph_scoped_stage_uses_same_pipeline() -> None:
    store = _store()
    await _graph_retrieve(_plugin(store))
    assert len(store.query_calls) == 2
    assert "spaceId" in str(store.query_calls[-1][3])


async def test_simple_and_graph_share_typed_branch_selection() -> None:
    simple, graph = _store(), _store()
    await _plugin(simple).handle(_event())  # type: ignore[arg-type]
    await _graph_retrieve(_plugin(graph))
    assert simple.query_calls[-1][3] == graph.query_calls[-1][3]


async def test_graph_hierarchy_context_uses_scoped_detail_result() -> None:
    store = _store()
    await _graph_retrieve(_plugin(store))
    assert store.query_calls[-1][3] is not None and "spaceId" in str(store.query_calls[-1][3])


@dataclass
class _Hybrid:
    hybrid_retrieval_enabled: bool = True
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3


async def test_hybrid_propagates_scoped_predicate_to_dense_and_lexical_arms() -> None:
    store = _store()
    await _plugin(store, hybrid_config=_Hybrid()).handle(_event())  # type: ignore[arg-type]
    assert "spaceId" in str(store.query_calls[-1][3])
    assert store.lexical_calls and store.lexical_calls[-1][3] == store.query_calls[-1][3]


async def test_pipeline_order_keeps_short_nonempty_scoped_result() -> None:
    store = _store()
    store.collections["c-knowledge"] = [entry for entry in _entries() if entry["id"] != "a-2"]
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1"]
    assert len(store.query_calls) == 2  # no unscoped sibling backfill


async def test_pipeline_order_applies_hierarchy_after_detail_selection() -> None:
    store = _store()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]


async def test_hierarchy_context_and_row_alignment() -> None:
    store = _store()
    llm = MockLLMPort(response="answer")
    plugin = ExpertPlugin(llm, store, hierarchical_retrieval_enabled=True)
    response = await plugin.handle(_event())  # type: ignore[arg-type]
    prompt = llm.calls[-1][0]["content"]
    assert "Space: Alpha" in prompt
    assert "[Document 1" in prompt and [source.source for source in response.sources] == ["a-1", "a-2"]


async def test_row_alignment_preserves_source_order_with_hierarchy() -> None:
    store = _store()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]


async def test_disabled_is_single_flat_call_and_byte_parity() -> None:
    store = _store()
    off = ExpertPlugin(MockLLMPort(response="answer"), store)
    await off.handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 1
    assert store.query_calls[0][3] is not None


class _Conversational:
    def classify(self, message: str) -> RoutingDecision:
        return RoutingDecision(RouteClass.CONVERSATIONAL, "test")


async def test_conversational_route_makes_zero_hierarchy_calls() -> None:
    store = _store()
    await _plugin(store, query_router=_Conversational()).handle(_event())  # type: ignore[arg-type]
    assert store.query_calls == []


async def test_disabled_graph_makes_one_flat_call() -> None:
    store = _store()
    await _graph_retrieve(ExpertPlugin(MockLLMPort(response="answer"), store))
    assert len(store.query_calls) == 1


async def test_fallback_missing_orienting_rows_uses_flat_once() -> None:
    store = _store()
    store.collections["c-knowledge"] = [entry for entry in _entries() if entry["metadata"].get("embeddingType") == "chunk"]
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert response.sources and len(store.query_calls) == 2


async def test_fallback_missing_branch_metadata_uses_flat_once() -> None:
    store = _store()
    store.collections["c-knowledge"][0]["metadata"].pop("spaceId")
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert response.sources and len(store.query_calls) == 2


async def test_fallback_empty_scoped_detail_uses_flat_once() -> None:
    store = _store()
    store.collections["c-knowledge"] = [entry for entry in _entries() if entry["id"] not in {"a-1", "a-2"}]
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert response.sources and len(store.query_calls) == 3


async def test_fallback_stage_one_failure_recovers_to_flat() -> None:
    class Store(MockKnowledgeStorePort):
        def __init__(self) -> None:
            super().__init__()
            self.collections["c-knowledge"] = _entries()
            self.first = True

        async def query(self, *args, **kwargs):
            if self.first:
                self.first = False
                raise RuntimeError("routing failed")
            return await super().query(*args, **kwargs)

    response = await _plugin(Store()).handle(_event())  # type: ignore[arg-type]
    assert response.sources


async def test_fallback_stage_two_failure_recovers_to_flat() -> None:
    class Store(MockKnowledgeStorePort):
        def __init__(self) -> None:
            super().__init__()
            self.collections["c-knowledge"] = _entries()
            self.calls = 0

        async def query(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("detail failed")
            return await super().query(*args, **kwargs)

    response = await _plugin(Store()).handle(_event())  # type: ignore[arg-type]
    assert response.sources


async def test_fallback_below_threshold_route_uses_flat_once() -> None:
    store = _store()
    await _plugin(store, score_threshold=0.95).handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 2


async def test_precision_proxy_scoped_results_reduce_off_branch_noise() -> None:
    """Structural proxy only: this is not RAGAS precision evidence."""
    flat_store, scoped_store = _store(), _store()
    flat = await ExpertPlugin(MockLLMPort(response="answer"), flat_store, n_results=5).handle(_event())  # type: ignore[arg-type]
    scoped = await _plugin(scoped_store).handle(_event())  # type: ignore[arg-type]
    flat_ids = {source.source for source in flat.sources}
    scoped_ids = {source.source for source in scoped.sources}
    relevant = {"a-1", "a-2"}
    assert scoped_ids == {"a-1", "a-2"}
    assert scoped_ids >= flat_ids & relevant
    assert len(scoped_ids & relevant) / len(scoped_ids) > len(flat_ids & relevant) / len(flat_ids)
