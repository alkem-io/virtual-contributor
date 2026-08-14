"""Tests for the evaluation knowledge-store tracing decorator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from core.ports.knowledge_store import QueryResult
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
    assert tracing_store.get_final_detail_contexts() == ["[Document 1]\ndetail"]


async def test_final_detail_context_is_flat_result_when_only_one_query() -> None:
    delegate = MagicMock()
    delegate.query = AsyncMock(return_value=QueryResult([["detail"]], [[{}]], [[0.1]], [["detail"]]))
    tracing_store = TracingKnowledgeStore(delegate)
    await tracing_store.query("knowledge", ["question"])
    tracing_store.capture_generation_context(["[Document 1]\ndetail"])
    assert tracing_store.get_final_detail_contexts() == ["[Document 1]\ndetail"]
