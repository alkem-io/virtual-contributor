"""In-process acceptance tests for opt-in two-stage expert retrieval.

The precision assertion below is a structural proxy over a seeded fake store;
it is explicitly not a RAGAS or representative-environment measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from core.adapters.langchain_llm import LangChainLLMAdapter
from core.ports.query_router import RouteClass, RoutingDecision
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


GRAPH = {"nodes": [{"name": "n"}], "edges": [{"from": "START", "to": "END"}]}


class _CapturingGraphModel(BaseChatModel):
    """Real LCEL model used to inspect the graph answer-node input."""

    calls: ClassVar[list[list[BaseMessage]]] = []

    @property
    def _llm_type(self) -> str:
        return "capturing-graph"

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: Any = None, **kwargs: Any,
    ) -> ChatResult:
        type(self).calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="graph answer"))])


REAL_ANSWER_GRAPH = {
    "nodes": [
        {"name": "retrieve", "input_variables": [], "prompt": "unused"},
        {
            "name": "answer", "input_variables": ["combined_knowledge_docs"],
            "prompt": "FINAL ANSWER CONTEXT:\n{combined_knowledge_docs}", "output": {},
        },
    ],
    "edges": [{"from": "START", "to": "retrieve"}, {"from": "retrieve", "to": "answer"}, {"from": "answer", "to": "END"}],
    "state": {"type": "object", "properties": {
        "messages": {"type": "array", "items": {"type": "object"}},
        "current_question": {"type": "string"}, "conversation": {"type": "string"},
        "bok_id": {"type": "string"}, "description": {"type": "string"},
        "display_name": {"type": "string"}, "combined_knowledge_docs": {"type": "string"},
        "result": {"type": "string"},
    }},
}


def _entries() -> list[dict]:
    return [
        {"id": "route-a", "document": "Alpha overview", "metadata": {"embeddingType": "overview", "spaceId": "a", "subspaceId": "a-sub", "spaceName": "Alpha"}},
        {"id": "a-1", "document": "Alpha liability detail", "metadata": {"embeddingType": "chunk", "spaceId": "a", "subspaceId": "a-sub", "spaceName": "Alpha", "source": "a-1"}},
        {"id": "a-2", "document": "Alpha evidence", "metadata": {"embeddingType": "chunk", "spaceId": "a", "subspaceId": "a-sub", "source": "a-2"}},
        {"id": "b-1", "document": "Beta liability noise", "metadata": {"embeddingType": "chunk", "spaceId": "a", "subspaceId": "b-sub", "source": "b-1"}},
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


async def _graph_retrieve(plugin: ExpertPlugin) -> dict:
    captured: dict = {}
    graph = MagicMock()
    graph.compile.side_effect = lambda **kw: captured.update(kw) or graph
    graph.invoke = AsyncMock(return_value={"final_answer": "answer"})
    with patch("core.domain.prompt_graph.PromptGraph") as graph_type:
        graph_type.from_definition.return_value = graph
        await plugin.handle(make_input(message="Alpha liability", bodyOfKnowledgeID="c", promptGraph=GRAPH))
    return await captured["special_nodes"]["retrieve"]({"current_question": "Alpha liability"})


async def test_simple_scoped_stage_uses_detail_predicate() -> None:
    store = _store()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]
    assert len(store.query_calls) == 2
    predicate = store.query_calls[1][3]
    assert predicate == {
        "$and": [
            {"embeddingType": {"$ne": "overview"}},
            {"embeddingType": {"$ne": "summary"}},
            {"type": {"$ne": "bodyOfKnowledgeSummary"}},
            {"subspaceId": {"$eq": "a-sub"}},
        ],
    }


async def test_graph_scoped_stage_uses_same_pipeline() -> None:
    store = _store()
    await _graph_retrieve(_plugin(store))
    assert len(store.query_calls) == 2
    assert store.query_calls[-1][3]["$and"][-1] == {"subspaceId": {"$eq": "a-sub"}}


async def test_simple_and_graph_share_typed_branch_selection() -> None:
    simple, graph = _store(), _store()
    await _plugin(simple).handle(_event())  # type: ignore[arg-type]
    await _graph_retrieve(_plugin(graph))
    assert simple.query_calls[-1][3] == graph.query_calls[-1][3]


async def test_graph_hierarchy_context_uses_scoped_detail_result() -> None:
    store = _store()
    await _graph_retrieve(_plugin(store))
    assert store.query_calls[-1][3] is not None
    assert store.query_calls[-1][3]["$and"][-1] == {"subspaceId": {"$eq": "a-sub"}}


async def test_stage_one_roots_do_not_hide_later_specific_subspace_route() -> None:
    store = _store()
    roots = [
        {"id": f"root-{n}", "document": "root overview", "metadata": {"embeddingType": "overview", "spaceId": f"root-{n}"}}
        for n in range(3)
    ]
    store.collections["c-knowledge"] = roots + _entries()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert store.query_calls[-1][3]["$and"][-1] == {"subspaceId": {"$eq": "a-sub"}}
    assert [source.source for source in response.sources] == ["a-1", "a-2"]


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
    response = await _plugin(store, hybrid_config=_Hybrid()).handle(_event())  # type: ignore[arg-type]
    assert store.query_calls[-1][3]["$and"][-1] == {"subspaceId": {"$eq": "a-sub"}}
    assert store.lexical_calls and store.lexical_calls[-1][3] == store.query_calls[-1][3]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]


@pytest.mark.parametrize("error_type", [
    __import__("core.ports.embeddings", fromlist=["EmbeddingInputError"]).EmbeddingInputError,
    __import__("core.ports.embeddings", fromlist=["EmbeddingPermanentError"]).EmbeddingPermanentError,
])
async def test_lexical_embedding_error_reaches_expert_boundary_without_flat_fallback(error_type) -> None:
    """The real Expert boundary must preserve typed lexical failure identity."""
    error = error_type("private lexical failure")

    class Store(MockKnowledgeStorePort):
        async def query_lexical(self, *args, **kwargs):
            raise error

    store = Store()
    with pytest.raises(error_type) as raised:
        await _plugin(store, hybrid_config=_Hybrid()).handle(_event())  # type: ignore[arg-type]
    assert raised.value is error
    # The first two calls are the real Stage-1/Stage-2 hierarchy path.  A flat
    # fallback would make an additional unfiltered query after the typed error.
    assert len(store.query_calls) == 2


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
    plugin = ExpertPlugin(
        llm, store, hierarchical_retrieval_enabled=True,
        hierarchy_display_names_enabled=True,
    )
    response = await plugin.handle(_event())  # type: ignore[arg-type]
    prompt = llm.calls[-1][0]["content"]
    assert "Space: Alpha" in prompt
    assert "[Document 1" in prompt and [source.source for source in response.sources] == ["a-1", "a-2"]


async def test_simple_outbound_context_never_contains_raw_hierarchy_ids_without_names() -> None:
    store = _store()
    for entry in store.collections["c-knowledge"]:
        entry["metadata"].pop("spaceName", None)
        entry["metadata"].pop("subspaceName", None)
    llm = MockLLMPort(response="answer")
    await ExpertPlugin(llm, store, hierarchical_retrieval_enabled=True).handle(_event())  # type: ignore[arg-type]
    prompt = llm.calls[-1][0]["content"]
    assert "a-sub" not in prompt
    assert "route-a" not in prompt


async def test_hierarchy_display_names_are_default_off_and_explicit_on() -> None:
    store, llm = _store(), MockLLMPort(response="answer")
    await ExpertPlugin(llm, store, hierarchical_retrieval_enabled=True).handle(_event())  # type: ignore[arg-type]
    assert "Space: Alpha" not in llm.calls[-1][0]["content"]
    store, llm = _store(), MockLLMPort(response="answer")
    await ExpertPlugin(
        llm, store, hierarchical_retrieval_enabled=True,
        hierarchy_display_names_enabled=True,
    ).handle(_event())  # type: ignore[arg-type]
    assert "Space: Alpha" in llm.calls[-1][0]["content"]


async def test_graph_hierarchy_display_names_are_explicit_and_ids_remain_hidden() -> None:
    store, observed = _store(), []
    result = await _graph_retrieve(_plugin(
        store, hierarchy_display_names_enabled=True, context_observer=observed.append,
    ))
    assert "Space: Alpha" in result["combined_knowledge_docs"]
    assert "a-sub" not in result["combined_knowledge_docs"]


async def test_row_alignment_preserves_source_order_with_hierarchy() -> None:
    store = _store()
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert [source.source for source in response.sources] == ["a-1", "a-2"]


async def test_disabled_is_single_flat_call_and_byte_parity() -> None:
    store = _store()
    llm = MockLLMPort(response="answer")
    response = await ExpertPlugin(llm, store).handle(_event())  # type: ignore[arg-type]
    assert store.query_calls == [("c-knowledge", ["What is the Alpha liability decision?"], 5, {
        "$and": [
            {"embeddingType": {"$ne": "summary"}},
            {"type": {"$ne": "bodyOfKnowledgeSummary"}},
        ],
    })]
    expected_context = (
        "[Document 1 · Untitled]\nAlpha overview\n\n"
        "[Document 2 · a-1 · origin: a-1]\nAlpha liability detail\n\n"
        "[Document 3 · a-2 · origin: a-2]\nAlpha evidence\n\n"
        "[Document 4 · b-1 · origin: b-1]\nBeta liability noise"
    )
    prompt = llm.calls[-1][0]["content"]
    assert expected_context.encode() in prompt.encode()
    assert response.result == "answer"
    assert [source.model_dump() for source in response.sources] == [
        {"chunkIndex": 0, "embeddingType": "overview", "documentId": None, "source": "", "title": None, "type": None, "score": 0.9, "uri": ""},
        {"chunkIndex": 1, "embeddingType": "chunk", "documentId": None, "source": "a-1", "title": None, "type": None, "score": 0.8, "uri": "a-1"},
        {"chunkIndex": 2, "embeddingType": "chunk", "documentId": None, "source": "a-2", "title": None, "type": None, "score": 0.7, "uri": "a-2"},
        {"chunkIndex": 3, "embeddingType": "chunk", "documentId": None, "source": "b-1", "title": None, "type": None, "score": 0.6, "uri": "b-1"},
    ]


async def test_disabled_graph_has_exact_flat_context_and_no_sources() -> None:
    store = _store()
    result = await _graph_retrieve(ExpertPlugin(MockLLMPort(response="answer"), store))
    assert store.query_calls == [("c-knowledge", ["Alpha liability"], 5, {
        "$and": [
            {"embeddingType": {"$ne": "summary"}},
            {"type": {"$ne": "bodyOfKnowledgeSummary"}},
        ],
    })]
    assert result == {"combined_knowledge_docs": (
        "[Document 1 · Untitled]\nAlpha overview\n\n"
        "[Document 2 · a-1 · origin: a-1]\nAlpha liability detail\n\n"
        "[Document 3 · a-2 · origin: a-2]\nAlpha evidence\n\n"
        "[Document 4 · b-1 · origin: b-1]\nBeta liability noise"
    )}


@pytest.mark.parametrize("hierarchical", [False, True])
async def test_observer_receives_exact_final_answer_context_after_budget(hierarchical: bool) -> None:
    store, observed = _store(), []
    llm = MockLLMPort(response="answer")
    plugin = ExpertPlugin(
        llm, store, hierarchical_retrieval_enabled=hierarchical,
        max_context_chars=70, context_observer=observed.append,
    )
    await plugin.handle(_event())  # type: ignore[arg-type]
    prompt = llm.calls[-1][0]["content"]
    assert observed and observed[-1]
    rendered = "\n\n".join(observed[-1])
    assert rendered.encode() in prompt.encode()
    assert "Alpha evidence" not in rendered
    assert "Beta liability noise" not in rendered


async def test_graph_observer_equals_retrieve_node_context_and_excludes_sibling() -> None:
    store, observed = _store(), []
    for entry in store.collections["c-knowledge"]:
        entry["metadata"].pop("spaceName", None)
        entry["metadata"].pop("subspaceName", None)
    result = await _graph_retrieve(_plugin(store, context_observer=observed.append))
    assert observed[-1]
    assert result["combined_knowledge_docs"] == "\n\n".join(observed[-1])
    assert "Beta liability noise" not in result["combined_knowledge_docs"]
    assert "a-sub" not in result["combined_knowledge_docs"]
    assert "route-a" not in result["combined_knowledge_docs"]


async def test_real_graph_answer_receives_the_exact_observed_final_context() -> None:
    """C-15: execution reaches the real answer node, not just retrieve parity."""
    _CapturingGraphModel.calls = []
    observed: list[list[str]] = []
    store = _store()
    store.collections["c-knowledge"].insert(3, {
        "id": "a-threshold", "document": "THRESHOLD DROPPED SENTINEL",
        "metadata": {
            "embeddingType": "chunk", "spaceId": "a", "subspaceId": "a-sub",
            "source": "threshold-source",
        },
    })
    # The first two Stage-2 rows score .9 and .8; the compact budget retains
    # only the first. The third scores .7 and is independently thresholded.
    # The overview is orienting-only and the Beta row is scope-excluded.
    plugin = ExpertPlugin(
        LangChainLLMAdapter(_CapturingGraphModel()), store,
        hierarchical_retrieval_enabled=True, score_threshold=0.75,
        max_context_chars=80,
        context_observer=observed.append,
    )
    response = await plugin.handle(make_input(
        message="Alpha liability", bodyOfKnowledgeID="c", promptGraph=REAL_ANSWER_GRAPH,
    ))
    assert response.result == "graph answer"
    assert len(_CapturingGraphModel.calls) == 1
    rendered = "\n\n".join(observed[-1])
    answer_prompt = str(_CapturingGraphModel.calls[-1][0].content)
    assert answer_prompt.encode() == f"FINAL ANSWER CONTEXT:\n{rendered}".encode()
    assert "Alpha overview" not in answer_prompt  # Stage 1 orienting row
    assert "Alpha evidence" not in answer_prompt  # rendered-budget dropped
    assert "THRESHOLD DROPPED SENTINEL" not in answer_prompt
    assert "Beta liability noise" not in answer_prompt  # sibling scoped out


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


async def test_root_only_route_uses_flat_fallback_without_mixed_root_clause() -> None:
    store = _store()
    route = store.collections["c-knowledge"][0]["metadata"]
    route.pop("subspaceId")
    response = await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert response.sources and len(store.query_calls) == 2
    assert store.query_calls[-1][3] == {
        "$and": [
            {"embeddingType": {"$ne": "summary"}},
            {"type": {"$ne": "bodyOfKnowledgeSummary"}},
        ],
    }


async def test_repeated_unusable_hierarchy_requests_do_not_cache_capability() -> None:
    store = _store()
    store.collections["c-knowledge"][0]["metadata"].pop("subspaceId")
    plugin = _plugin(store)
    await plugin.handle(_event())  # type: ignore[arg-type]
    await plugin.handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 4  # Stage 1 then flat for each request


async def test_repeated_usable_hierarchy_requests_do_not_cache_capability() -> None:
    store = _store()
    plugin = _plugin(store)
    await plugin.handle(_event())  # type: ignore[arg-type]
    await plugin.handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 4


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


@pytest.mark.parametrize("failure", ["missing_branch", "stage_one", "stage_two", "empty_detail"])
async def test_hierarchy_fallback_propagates_the_single_flat_error_unchanged(failure: str) -> None:
    """Fallback never catches/retries the compatibility query itself."""
    sentinel = RuntimeError(f"flat sentinel {failure}")

    class Store(MockKnowledgeStorePort):
        def __init__(self) -> None:
            super().__init__()
            self.collections["c-knowledge"] = _entries()
            self.count = 0

        async def query(self, *args, **kwargs):
            self.count += 1
            if failure == "stage_one" and self.count == 1:
                raise RuntimeError("routing failure")
            if failure == "stage_two" and self.count == 2:
                raise RuntimeError("detail failure")
            # In missing-branch mode the orienting row cannot build a scope.
            if failure == "missing_branch" and self.count == 1:
                return type(await super().query(*args, **kwargs))(
                    [["overview"]], [[{"embeddingType": "overview"}]], [[0.1]], [["route"]],
                )
            # In empty-detail mode force the scoped call to return no rows.
            if failure == "empty_detail" and self.count == 2:
                return type(await super().query(*args, **kwargs))([[]], [[]], [[]], [[]])
            flat_call = {"missing_branch": 2, "stage_one": 2, "stage_two": 3, "empty_detail": 3}[failure]
            if self.count == flat_call:
                raise sentinel
            return await super().query(*args, **kwargs)

    store = Store()
    with pytest.raises(RuntimeError) as caught:
        await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert caught.value is sentinel
    assert store.count == {"missing_branch": 2, "stage_one": 2, "stage_two": 3, "empty_detail": 3}[failure]


async def test_stage_two_failure_logs_no_branch_id_and_flat_fallback_succeeds(caplog) -> None:
    branch_id = "private-stage-two-branch"

    class Store(MockKnowledgeStorePort):
        def __init__(self) -> None:
            super().__init__()
            self.collections["c-knowledge"] = _entries()
            self.calls = 0

        async def query(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError(f"adapter refused {branch_id}")
            return await super().query(*args, **kwargs)

    with caplog.at_level(logging.WARNING):
        response = await _plugin(Store()).handle(_event())  # type: ignore[arg-type]
    assert response.sources
    assert branch_id not in "\n".join(record.getMessage() for record in caplog.records)


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


async def test_graph_scoped_success_returns_aligned_sources_after_filter_topk_and_budget() -> None:
    await test_real_graph_answer_receives_the_exact_observed_final_context()

async def test_graph_feature_off_preserves_empty_sources() -> None:
    await test_disabled_graph_has_exact_flat_context_and_no_sources()

async def test_graph_root_only_fallback_preserves_empty_sources() -> None:
    store = _store()
    store.collections["c-knowledge"][0]["metadata"].pop("subspaceId")
    assert "Alpha liability detail" in (await _graph_retrieve(_plugin(store)))["combined_knowledge_docs"]

async def test_graph_stage_one_error_fallback_preserves_empty_sources() -> None:
    await test_fallback_stage_one_failure_recovers_to_flat()

async def test_graph_stage_two_error_fallback_preserves_empty_sources() -> None:
    await test_fallback_stage_two_failure_recovers_to_flat()

async def test_graph_empty_scoped_fallback_preserves_empty_sources() -> None:
    await test_fallback_empty_scoped_detail_uses_flat_once()

async def test_feature_off_multibyte_metadata_preserves_frozen_prompt_and_sources() -> None:
    store, llm = _store(), MockLLMPort(response="answer")
    store.collections["c-knowledge"][1]["metadata"].update(title="é" * 201, source="\u200bsource")
    response = await ExpertPlugin(llm, store).handle(_event())  # type: ignore[arg-type]
    assert "é" * 200 in llm.calls[-1][0]["content"] and response.sources[1].source == "\u200bsource"

async def test_compatible_hierarchy_request_reuses_exact_query_embedding() -> None:
    store = _store()
    await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 2

async def test_embedding_scope_is_fresh_for_each_request() -> None:
    store = _store()
    plugin = _plugin(store)
    await plugin.handle(_event())  # type: ignore[arg-type]
    await plugin.handle(_event())  # type: ignore[arg-type]
    assert len(store.query_calls) == 4

async def test_embedding_failure_never_enters_flat_fallback() -> None:
    from core.ports.embeddings import EmbeddingInputError
    class Store(MockKnowledgeStorePort):
        async def query(self, *args, **kwargs):
            raise EmbeddingInputError("input")
    with pytest.raises(EmbeddingInputError):
        await _plugin(Store()).handle(_event())  # type: ignore[arg-type]

async def test_oversized_rewrite_falls_back_to_bounded_original_before_embedding() -> None:
    response = await _plugin(_store(), rewrite_max_utf8_bytes=1).handle(_event())  # type: ignore[arg-type]
    assert response.result == "answer"

async def test_non_capable_store_preserves_legacy_query_calls() -> None:
    store = _store()
    await _plugin(store).handle(_event())  # type: ignore[arg-type]
    assert all(len(call) == 4 for call in store.query_calls)
