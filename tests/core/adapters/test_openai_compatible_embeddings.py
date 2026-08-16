"""Unit tests for OpenAICompatibleEmbeddingsAdapter query-side wrapping."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.adapters.openai_compatible_embeddings import (
    QWEN3_RETRIEVAL_INSTRUCTION,
    OpenAICompatibleEmbeddingsAdapter,
)
from core.ports.embeddings import EmbeddingInputError, EmbeddingPermanentError, EmbeddingTransientError


def _fake_response(dim: int = 4, n: int = 1):
    """Build a fake httpx response object that .json()/.raise_for_status()."""

    class R:
        def raise_for_status(self):
            pass

        def json(self_inner):
            return {"data": [{"embedding": [0.1] * dim} for _ in range(n)]}

    return R()


def _payload_from_post_call(mock_post) -> dict:
    """Extract the JSON body passed to httpx client.post."""
    return mock_post.call_args.kwargs["json"]


class TestQueryInstructionResolution:
    def test_qwen3_model_auto_wraps(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="qwen3-embedding-8b"
        )
        assert adapter._query_instruction == QWEN3_RETRIEVAL_INSTRUCTION

    def test_qwen3_case_insensitive(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="Qwen3-Embedding-0.6B"
        )
        assert adapter._query_instruction == QWEN3_RETRIEVAL_INSTRUCTION

    def test_non_qwen_no_wrap_by_default(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="text-embedding-3-small"
        )
        assert adapter._query_instruction == ""

    def test_explicit_instruction_overrides_auto(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k",
            endpoint="http://x",
            model_name="qwen3-embedding-8b",
            query_instruction="Custom: ",
        )
        assert adapter._query_instruction == "Custom: "

    def test_explicit_empty_string_disables_wrap(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k",
            endpoint="http://x",
            model_name="qwen3-embedding-8b",
            query_instruction="",
        )
        assert adapter._query_instruction == ""


@pytest.mark.asyncio
class TestWrappingBehaviour:
    async def test_embed_does_not_wrap(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="qwen3-embedding-8b"
        )
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(return_value=_fake_response(n=2))
            await adapter.embed(["doc a", "doc b"])
            sent = _payload_from_post_call(client.post)
        assert sent["input"] == ["doc a", "doc b"]

    async def test_embed_query_wraps_with_qwen3_prefix(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="qwen3-embedding-8b"
        )
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(return_value=_fake_response(n=1))
            await adapter.embed_query(["Who's Neil"])
            sent = _payload_from_post_call(client.post)
        assert sent["input"] == [f"{QWEN3_RETRIEVAL_INSTRUCTION}Who's Neil"]

    async def test_embed_query_no_wrap_when_instruction_empty(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k",
            endpoint="http://x",
            model_name="qwen3-embedding-8b",
            query_instruction="",
        )
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(return_value=_fake_response(n=1))
            await adapter.embed_query(["Who's Neil"])
            sent = _payload_from_post_call(client.post)
        assert sent["input"] == ["Who's Neil"]

    async def test_embed_query_uses_custom_instruction(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k",
            endpoint="http://x",
            model_name="something-else",
            query_instruction="Find: ",
        )
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(return_value=_fake_response(n=2))
            await adapter.embed_query(["a", "b"])
            sent = _payload_from_post_call(client.post)
        assert sent["input"] == ["Find: a", "Find: b"]

    async def test_embed_query_rejects_oversized_utf8_input_before_http(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(
            api_key="k", endpoint="http://x", model_name="model", query_max_utf8_bytes=3,
        )
        with patch("httpx.AsyncClient") as client_cls, pytest.raises(EmbeddingInputError):
            await adapter.embed_query(["éé"])
        assert not client_cls.called

    async def test_permanent_embedding_error_is_not_retried(self):
        adapter = OpenAICompatibleEmbeddingsAdapter(api_key="k", endpoint="http://x", model_name="model")
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=ValueError("bad request"))
            with pytest.raises(EmbeddingPermanentError):
                await adapter.embed_query(["q"])
        assert client.post.await_count == 1

    async def test_transient_embedding_error_honors_attempt_and_total_deadline(self, monkeypatch):
        import httpx
        adapter = OpenAICompatibleEmbeddingsAdapter(
            "k", "http://x", "model", max_attempts=2, attempt_timeout_seconds=1, total_deadline_seconds=2,
        )
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=httpx.ConnectError("temporary"))
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.asyncio.sleep", AsyncMock())
            with pytest.raises(Exception):
                await adapter.embed_query(["q"])
        assert client.post.await_count == 2

    async def test_embedding_retry_logs_only_safe_type_and_attempt(self, caplog, monkeypatch):
        import httpx
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=2)
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=httpx.ConnectError("private-query"))
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.asyncio.sleep", AsyncMock())
            with pytest.raises(Exception):
                await adapter.embed_query(["q"])
        assert "private-query" not in caplog.text and "error_type=ConnectError" in caplog.text

    async def test_local_attempt_timeout_is_retried_as_transient(self, monkeypatch):
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=2, attempt_timeout_seconds=.001, total_deadline_seconds=.1)
        async def slow(*args, **kwargs):
            await asyncio.sleep(.02)
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=slow)
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.BASE_DELAY", 0)
            with pytest.raises(EmbeddingTransientError):
                await adapter.embed_query(["q"])
        assert client.post.await_count == 2

    async def test_local_attempt_timeout_exhaustion_preserves_typed_transient_error(self, monkeypatch):
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=1, attempt_timeout_seconds=.001, total_deadline_seconds=.1)
        async def slow(*args, **kwargs): await asyncio.sleep(.02)
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=slow)
            with pytest.raises(EmbeddingTransientError) as raised:
                await adapter.embed_query(["q"])
        assert isinstance(raised.value.__cause__, TimeoutError) and client.post.await_count == 1

    async def test_total_deadline_preempts_local_attempt_timeout_retries(self, monkeypatch):
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=5, attempt_timeout_seconds=.05, total_deadline_seconds=.001)
        async def slow(*args, **kwargs): await asyncio.sleep(.02)
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=slow)
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.BASE_DELAY", 0)
            with pytest.raises(EmbeddingTransientError):
                await adapter.embed_query(["q"])
        assert client.post.await_count < 5

    async def test_local_attempt_timeout_respects_max_provider_calls(self, monkeypatch):
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=3, attempt_timeout_seconds=.001, total_deadline_seconds=.1)
        async def slow(*args, **kwargs): await asyncio.sleep(.02)
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=slow)
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.BASE_DELAY", 0)
            with pytest.raises(EmbeddingTransientError):
                await adapter.embed_query(["q"])
        assert client.post.await_count == 3

    async def test_document_embed_retries_decode_error_and_recovers_with_base_semantics(self, monkeypatch):
        import json
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model")
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=[json.JSONDecodeError("x", "x", 0), _fake_response()])
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.BASE_DELAY", 0)
            assert await adapter.embed(["document"]) == [[0.1] * 4]
        assert client.post.await_count == 2
        cls.assert_called_with(timeout=60.0)

    @pytest.mark.parametrize("make_exc", [
        lambda: __import__("httpx").RemoteProtocolError("server disconnected"),
        lambda: __import__("httpx").ProxyError("proxy refused"),
        lambda: __import__("json").JSONDecodeError("truncated", "x", 0),
    ])
    async def test_query_embedding_retries_mid_stream_and_proxy_and_decode_errors(self, monkeypatch, make_exc):
        """A dropped connection, a flaky proxy, or a truncated body must spend
        the configured attempt budget, not fail permanently after one send."""
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model", max_attempts=3)
        with patch("httpx.AsyncClient") as client_cls:
            client = client_cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=[make_exc(), make_exc(), _fake_response()])
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.asyncio.sleep", AsyncMock())
            result = await adapter.embed_query(["q"])
        assert result == [[0.1] * 4]
        assert client.post.await_count == 3

    async def test_document_embed_exhaustion_reraises_original_error(self, monkeypatch):
        import json
        error = json.JSONDecodeError("x", "x", 0)
        adapter = OpenAICompatibleEmbeddingsAdapter("k", "http://x", "model")
        with patch("httpx.AsyncClient") as cls:
            client = cls.return_value.__aenter__.return_value
            client.post = AsyncMock(side_effect=error)
            monkeypatch.setattr("core.adapters.openai_compatible_embeddings.BASE_DELAY", 0)
            with pytest.raises(json.JSONDecodeError) as raised:
                await adapter.embed(["document"])
        assert raised.value is error and client.post.await_count == 3
