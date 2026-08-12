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
