"""Standard OpenAI embedding adapter contracts: query retries are adapter-owned."""
from __future__ import annotations
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from core.adapters.openai_embeddings import OpenAIEmbeddingsAdapter
from core.ports.embeddings import EmbeddingInputError, EmbeddingPermanentError, EmbeddingTransientError


async def test_openai_embedding_input_limit_precedes_client_call() -> None:
    adapter = OpenAIEmbeddingsAdapter("k", query_max_utf8_bytes=3)
    adapter._query_client.embeddings.create = AsyncMock()
    with pytest.raises(EmbeddingInputError):
        await adapter.embed_query(["éé"])
    adapter._query_client.embeddings.create.assert_not_awaited()

async def test_openai_embedding_errors_are_typed() -> None:
    adapter = OpenAIEmbeddingsAdapter("k")
    adapter._query_client.embeddings.create = AsyncMock(side_effect=ValueError("provider detail"))
    with pytest.raises(EmbeddingPermanentError):
        await adapter.embed_query(["q"])

async def test_openai_embedding_retry_budget_is_bounded(monkeypatch) -> None:
    adapter = OpenAIEmbeddingsAdapter(
        "k", max_attempts=2, attempt_timeout_seconds=1, total_deadline_seconds=2,
    )
    adapter._query_client.embeddings.create = AsyncMock(side_effect=ConnectionError("temporary"))
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    with pytest.raises(EmbeddingTransientError):
        await adapter.embed_query(["q"])
    assert adapter._query_client.embeddings.create.await_count == 2


async def test_openai_document_embed_retries_base_errors_and_recovers(monkeypatch) -> None:
    """Ingestion retains the historical retry-any-exception policy."""
    import json

    adapter = OpenAIEmbeddingsAdapter("k")
    response = type("Response", (), {"data": [type("Item", (), {"embedding": [.1]})()]})()
    adapter._client.embeddings.create = AsyncMock(
        side_effect=[json.JSONDecodeError("bad", "{", 0), response]
    )
    monkeypatch.setattr("core.adapters.openai_embeddings.BASE_DELAY", 0)
    assert await adapter.embed(["document"]) == [[.1]]
    assert adapter._client.embeddings.create.await_count == 2


async def test_openai_document_embed_exhaustion_reraises_original_error(monkeypatch) -> None:
    import json

    error = json.JSONDecodeError("bad", "{", 0)
    adapter = OpenAIEmbeddingsAdapter("k")
    adapter._client.embeddings.create = AsyncMock(side_effect=error)
    monkeypatch.setattr("core.adapters.openai_embeddings.BASE_DELAY", 0)
    with pytest.raises(json.JSONDecodeError) as raised:
        await adapter.embed(["document"])
    assert raised.value is error
    assert adapter._client.embeddings.create.await_count == 3


async def test_openai_query_disables_sdk_retries_and_honors_exact_max_attempts(monkeypatch) -> None:
    """The outer retry loop, rather than the SDK, owns every HTTP send."""
    sends = 0

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal sends
        sends += 1
        return httpx.Response(500, request=request, json={"error": {"message": "retry"}})

    adapter = OpenAIEmbeddingsAdapter("k", max_attempts=3)
    transport = httpx.MockTransport(fail)
    http_client = httpx.AsyncClient(transport=transport)
    adapter._query_client = AsyncOpenAI(api_key="k", max_retries=0, http_client=http_client)
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    try:
        for attempts in (1, 2, 3, 5):
            adapter._max_attempts = attempts
            sends = 0
            with pytest.raises(EmbeddingTransientError):
                await adapter.embed_query(["query"])
            assert sends == attempts
        assert adapter._query_client.max_retries == 0
    finally:
        await http_client.aclose()


async def test_openai_query_total_deadline_preempts_real_transport_attempts(monkeypatch) -> None:
    import asyncio

    adapter = OpenAIEmbeddingsAdapter("k", max_attempts=5, total_deadline_seconds=.01)

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"data": [{"embedding": [.1]}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    adapter._query_client = AsyncOpenAI(api_key="k", max_retries=0, http_client=http_client)
    try:
        with pytest.raises(EmbeddingTransientError):
            await adapter.embed_query(["query"])
    finally:
        await http_client.aclose()


async def test_openai_query_policy_preserves_frozen_document_client_behavior() -> None:
    adapter = OpenAIEmbeddingsAdapter("k")
    assert adapter._client.max_retries == 2
    assert adapter._query_client.max_retries == 0


async def test_openai_query_api_connection_error_is_transient_and_recovers(monkeypatch) -> None:
    import httpx
    from openai import APIConnectionError
    response = type("Response", (), {"data": [type("Item", (), {"embedding": [.1]})()]})()
    adapter = OpenAIEmbeddingsAdapter("k", max_attempts=2)
    adapter._query_client.embeddings.create = AsyncMock(side_effect=[APIConnectionError(request=httpx.Request("POST", "https://example.test")), response])
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    assert await adapter.embed_query(["query"]) == [[.1]]


async def test_openai_query_api_timeout_error_is_transient_and_recovers(monkeypatch) -> None:
    import httpx
    from openai import APITimeoutError
    response = type("Response", (), {"data": [type("Item", (), {"embedding": [.1]})()]})()
    adapter = OpenAIEmbeddingsAdapter("k", max_attempts=2)
    adapter._query_client.embeddings.create = AsyncMock(side_effect=[APITimeoutError(request=httpx.Request("POST", "https://example.test")), response])
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    assert await adapter.embed_query(["query"]) == [[.1]]


async def test_openai_query_native_transport_exhaustion_keeps_typed_transient_boundary(monkeypatch) -> None:
    import httpx
    from openai import APIConnectionError
    adapter = OpenAIEmbeddingsAdapter("k", max_attempts=2)
    adapter._query_client.embeddings.create = AsyncMock(side_effect=APIConnectionError(request=httpx.Request("POST", "https://example.test")))
    monkeypatch.setattr("core.adapters.openai_embeddings.asyncio.sleep", AsyncMock())
    with pytest.raises(EmbeddingTransientError):
        await adapter.embed_query(["query"])
