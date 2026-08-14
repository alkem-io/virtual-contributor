"""Tests for Chroma query metadata-filter forwarding."""

from __future__ import annotations

import asyncio
import contextvars
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.adapters.chromadb import ChromaDBAdapter
from core.domain.retrieval_filters import FACTUAL_WHERE
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
    # Use the real production filter so the pinned example is a shape Chroma
    # actually accepts ($and requires >= 2 operands on a live server).
    where = FACTUAL_WHERE

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

    async def call_query(fn, **kwargs):
        return await asyncio.to_thread(fn)

    with patch.object(adapter, "_retry", new=AsyncMock(side_effect=call_query)) as retry:
        await adapter.query("knowledge", ["question"], where=where)

    retry.assert_awaited_once()
    assert collection.query.call_args.kwargs["where"] is where


async def test_retry_fast_fails_validation_errors_but_retries_decode_errors() -> None:
    """CQ-5 contract: deterministic ValueError → one attempt; transient
    JSONDecodeError (a ValueError subclass — truncated/non-JSON response
    bodies at the client's orjson parse step) → full retries."""
    import json as _json

    attempts = {"validation": 0, "decode": 0}

    def raise_validation():
        attempts["validation"] += 1
        raise ValueError("Expected where to have exactly one operator")

    def raise_decode():
        attempts["decode"] += 1
        _json.loads("<html>502 Bad Gateway</html>")

    with patch("core.adapters.chromadb.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ValueError, match="exactly one operator"):
            await ChromaDBAdapter._retry(raise_validation)
        with pytest.raises(_json.JSONDecodeError):
            await ChromaDBAdapter._retry(raise_decode)

    assert attempts["validation"] == 1  # fast-fail, no backoff burn
    assert attempts["decode"] == 3  # transient — full retry ladder


async def test_chromadb_embedding_scope_reuses_exact_input_only(adapter: ChromaDBAdapter) -> None:
    adapter._query_embedding_cache = contextvars.ContextVar("test-cache", default=None)
    async with adapter.query_embedding_scope():
        await adapter._embed_query(["same"])
        await adapter._embed_query(["same"])
        await adapter._embed_query(["different"])
    assert adapter._embeddings.embed_query.await_count == 2


async def test_chromadb_embedding_scope_does_not_reuse_across_requests(adapter: ChromaDBAdapter) -> None:
    adapter._query_embedding_cache = contextvars.ContextVar("test-cache-2", default=None)
    async with adapter.query_embedding_scope():
        await adapter._embed_query(["same"])
    async with adapter.query_embedding_scope():
        await adapter._embed_query(["same"])
    assert adapter._embeddings.embed_query.await_count == 2


def test_chromadb_query_signature_remains_knowledge_store_compatible() -> None:
    from core.ports.knowledge_store import KnowledgeStorePort
    assert isinstance(ChromaDBAdapter.__new__(ChromaDBAdapter), KnowledgeStorePort)
