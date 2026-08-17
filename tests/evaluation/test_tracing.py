"""Tests for the evaluation knowledge-store tracing decorator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from core.ports.knowledge_store import GetResult, QueryResult
from core.domain.hybrid_retrieval import retrieve
from evaluation.tracing import TracingKnowledgeStore


async def test_query_forwards_where_and_captures_filtered_context() -> None:
    filtered_result = QueryResult(
        documents=[["eligible chunk"]],
        metadatas=[[{"embeddingType": "chunk"}]],
        distances=[[0.1]],
        ids=[["chunk-1"]],
    )
    delegate = MagicMock()
    delegate.query = AsyncMock(return_value=filtered_result)
    tracing_store = TracingKnowledgeStore(delegate)
    where = {"embeddingType": {"$ne": "summary"}}

    result = await tracing_store.query("knowledge", ["question"], 5, where=where)

    assert result is filtered_result
    delegate.query.assert_awaited_once_with("knowledge", ["question"], 5, where=where)
    assert tracing_store.get_retrieved_contexts() == ["eligible chunk"]


async def test_final_detail_context_excludes_hierarchy_routing_context() -> None:
    delegate = MagicMock()
    delegate.query = AsyncMock(side_effect=[
        QueryResult([["overview"]], [[{}]], [[0.1]], [["route"]]),
        QueryResult([["detail"]], [[{}]], [[0.1]], [["detail"]]),
    ])
    tracing_store = TracingKnowledgeStore(delegate)
    await tracing_store.query("knowledge", ["question"], where={"embeddingType": {"$eq": "overview"}})
    await tracing_store.query("knowledge", ["question"], where={"spaceId": "s"})
    tracing_store.capture_generation_context(["[Document 1]\ndetail"])
    # Both raw captures are visible as retrieval state, while the final
    # detail contexts hold only the published generation blocks — neither
    # raw captured document leaks through the boundary.
    assert tracing_store.get_retrieved_contexts() == ["overview", "detail"]
    assert tracing_store.get_final_detail_contexts() == ["[Document 1]\ndetail"]
    assert "overview" not in tracing_store.get_final_detail_contexts()
    assert "detail" not in tracing_store.get_final_detail_contexts()


async def test_final_detail_context_is_flat_result_when_only_one_query() -> None:
    delegate = MagicMock()
    delegate.query = AsyncMock(return_value=QueryResult([["detail"]], [[{}]], [[0.1]], [["detail"]]))
    tracing_store = TracingKnowledgeStore(delegate)
    await tracing_store.query("knowledge", ["question"])
    tracing_store.capture_generation_context(["[Document 1]\ndetail"])
    assert tracing_store.get_retrieved_contexts() == ["detail"]
    assert tracing_store.get_final_detail_contexts() == ["[Document 1]\ndetail"]
    assert "detail" not in tracing_store.get_final_detail_contexts()


async def test_transparent_wrapper_forwards_hybrid_lexical_and_store_operations() -> None:
    result = QueryResult([["lexical"]], [[{}]], [[None]], [["id"]])
    delegate = MagicMock()
    delegate.query_lexical = AsyncMock(return_value=result)
    delegate.get = AsyncMock(return_value=GetResult(ids=["id"]))
    delegate.delete = AsyncMock()
    tracing_store = TracingKnowledgeStore(delegate)
    where = {"subspaceId": {"$eq": "branch"}}

    assert await tracing_store.query_lexical("c", ["needle"], 7, where=where) is result
    assert await tracing_store.get("c", ["id"], where, ["documents"]) == GetResult(ids=["id"])
    await tracing_store.delete("c", ["id"], where)

    delegate.query_lexical.assert_awaited_once_with("c", ["needle"], 7, where=where)
    delegate.get.assert_awaited_once_with("c", ["id"], where, ["documents"])
    delegate.delete.assert_awaited_once_with("c", ["id"], where)
    assert tracing_store.get_retrieved_contexts() == ["lexical"]


async def test_hybrid_retrieval_uses_both_arms_through_evaluation_wrapper() -> None:
    class HybridConfig:
        hybrid_retrieval_enabled = True
        hybrid_dense_weight = 1.0
        hybrid_lexical_weight = 1.0
        hybrid_rrf_k = 60
        hybrid_max_terms = 8
        hybrid_min_term_len = 3

    delegate = MagicMock()
    delegate.query = AsyncMock(return_value=QueryResult(
        [["dense"]], [[{}]], [[0.1]], [["dense-id"]],
    ))
    delegate.query_lexical = AsyncMock(return_value=QueryResult(
        [["lexical"]], [[{}]], [[None]], [["lexical-id"]],
    ))
    store = TracingKnowledgeStore(delegate)
    predicate = {"subspaceId": {"$eq": "selected"}}

    result = await retrieve(store, "c", "Needle wording", HybridConfig(), n_results=3, where=predicate)

    assert set(result.ids[0]) == {"dense-id", "lexical-id"}
    assert delegate.query.await_args.kwargs["where"] == predicate
    assert delegate.query_lexical.await_args.kwargs["where"] == predicate
async def test_generation_context_publication_tracks_presence_separately_from_empty_value():
    from tests.conftest import MockKnowledgeStorePort
    store = TracingKnowledgeStore(MockKnowledgeStorePort())
    assert not store.generation_context_published
    store.capture_generation_context([])
    assert store.generation_context_published
    assert store.get_final_detail_contexts() == []
