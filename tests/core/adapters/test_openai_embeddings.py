"""C-29 standard OpenAI embedding adapter contracts."""
from __future__ import annotations
from unittest.mock import AsyncMock
import pytest
from core.adapters.openai_embeddings import OpenAIEmbeddingsAdapter
from core.ports.embeddings import EmbeddingInputError, EmbeddingPermanentError, EmbeddingTransientError


async def test_openai_embedding_input_limit_precedes_client_call() -> None:
    adapter = OpenAIEmbeddingsAdapter("k", query_max_utf8_bytes=3)
    adapter._client.embeddings.create = AsyncMock()
    with pytest.raises(EmbeddingInputError):
        await adapter.embed_query(["éé"])
    adapter._client.embeddings.create.assert_not_awaited()

async def test_openai_embedding_errors_are_typed() -> None:
    adapter = OpenAIEmbeddingsAdapter("k")
    adapter._client.embeddings.create = AsyncMock(side_effect=ValueError("provider detail"))
    with pytest.raises(EmbeddingPermanentError):
        await adapter.embed_query(["q"])

async def test_openai_embedding_retry_budget_is_bounded(monkeypatch) -> None:
    adapter = OpenAIEmbeddingsAdapter(
        "k", max_attempts=2, attempt_timeout_seconds=1, total_deadline_seconds=2,
    )
    adapter._client.embeddings.create = AsyncMock(side_effect=ConnectionError("temporary"))
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    with pytest.raises(EmbeddingTransientError):
        await adapter.embed_query(["q"])
    assert adapter._client.embeddings.create.await_count == 2
