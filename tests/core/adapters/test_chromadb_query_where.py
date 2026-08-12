"""Tests for Chroma query metadata-filter forwarding."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adapters.chromadb import ChromaDBAdapter
from core.ports.knowledge_store import QueryResult


@pytest.fixture
def adapter() -> ChromaDBAdapter:
    adapter = ChromaDBAdapter.__new__(ChromaDBAdapter)
    adapter._client = MagicMock()
    adapter._embeddings = MagicMock()
    adapter._embeddings.embed_query = AsyncMock(return_value=[[0.1, 0.2]])
    adapter._distance_fn = "cosine"
    return adapter


def _configured_collection(adapter: ChromaDBAdapter) -> MagicMock:
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [["doc"]],
        "metadatas": [[{"source": "test"}]],
        "distances": [[0.1]],
        "ids": [["id"]],
    }
    adapter._client.get_or_create_collection.return_value = collection
    return collection


async def test_query_forwards_where_verbatim(adapter: ChromaDBAdapter) -> None:
    collection = _configured_collection(adapter)
    where = {"$and": [{"embeddingType": {"$ne": "summary"}}]}

    result = await adapter.query("knowledge", ["question"], 3, where=where)

    assert isinstance(result, QueryResult)
    assert collection.query.call_args.kwargs["where"] is where
    assert collection.query.call_args.kwargs["n_results"] == 3


async def test_query_omits_where_when_unfiltered(adapter: ChromaDBAdapter) -> None:
    collection = _configured_collection(adapter)

    await adapter.query("knowledge", ["question"])

    assert "where" not in collection.query.call_args.kwargs


async def test_filtered_query_uses_the_existing_retry_path(adapter: ChromaDBAdapter) -> None:
    collection = _configured_collection(adapter)
    where = {"embeddingType": {"$ne": "summary"}}

    async def call_query(fn):
        return await asyncio.to_thread(fn)

    with patch.object(adapter, "_retry", new=AsyncMock(side_effect=call_query)) as retry:
        await adapter.query("knowledge", ["question"], where=where)

    retry.assert_awaited_once()
    assert collection.query.call_args.kwargs["where"] is where
