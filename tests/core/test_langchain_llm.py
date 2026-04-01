"""Tests for LangChainLLMAdapter: invoke, stream, retry, message conversion."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.adapters.langchain_llm import LangChainLLMAdapter, _to_langchain_messages


class TestMessageConversion:
    """Test dict → LangChain message type conversion."""

    def test_system_role(self) -> None:
        msgs = _to_langchain_messages([{"role": "system", "content": "Be helpful."}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[0].content == "Be helpful."

    def test_human_role(self) -> None:
        msgs = _to_langchain_messages([{"role": "human", "content": "Hello"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)

    def test_assistant_role(self) -> None:
        msgs = _to_langchain_messages([{"role": "assistant", "content": "Hi"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], AIMessage)

    def test_ai_role_alias(self) -> None:
        msgs = _to_langchain_messages([{"role": "ai", "content": "Hi"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], AIMessage)

    def test_unknown_role_defaults_to_human(self) -> None:
        msgs = _to_langchain_messages([{"role": "user", "content": "Hi"}])
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)

    def test_mixed_roles(self) -> None:
        msgs = _to_langchain_messages([
            {"role": "system", "content": "System prompt"},
            {"role": "human", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ])
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert isinstance(msgs[2], AIMessage)


class TestInvoke:
    """Test invoke returns string from LLM response."""

    @pytest.mark.asyncio
    async def test_invoke_returns_string(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="Hello world")
        adapter = LangChainLLMAdapter(mock_llm)
        result = await adapter.invoke([{"role": "human", "content": "Hi"}])
        assert result == "Hello world"
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_retries_on_failure(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = [
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
            MagicMock(content="Success"),
        ]
        adapter = LangChainLLMAdapter(mock_llm)
        with patch("core.adapters.langchain_llm.asyncio.sleep", new_callable=AsyncMock):
            result = await adapter.invoke([{"role": "human", "content": "Hi"}])
        assert result == "Success"
        assert mock_llm.ainvoke.call_count == 3

    @pytest.mark.asyncio
    async def test_invoke_raises_after_max_retries(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("persistent failure")
        adapter = LangChainLLMAdapter(mock_llm)
        with patch("core.adapters.langchain_llm.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="persistent failure"):
                await adapter.invoke([{"role": "human", "content": "Hi"}])
        assert mock_llm.ainvoke.call_count == 3

    @pytest.mark.asyncio
    async def test_invoke_exponential_backoff(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = [
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
            MagicMock(content="ok"),
        ]
        adapter = LangChainLLMAdapter(mock_llm)
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with patch("core.adapters.langchain_llm.asyncio.sleep", side_effect=fake_sleep):
            await adapter.invoke([{"role": "human", "content": "Hi"}])
        assert sleep_calls == [1.0, 2.0]


class TestConnectionError:
    """Test connection error handling for unreachable local endpoints."""

    @pytest.mark.asyncio
    async def test_connection_error_fails_fast(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = ConnectionError("Connection refused")
        adapter = LangChainLLMAdapter(mock_llm)
        with pytest.raises(ConnectionError, match="Failed to connect to LLM endpoint"):
            await adapter.invoke([{"role": "human", "content": "Hi"}])
        # Should fail on first attempt, no retries for connection errors
        assert mock_llm.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_os_error_fails_fast(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = OSError("Network unreachable")
        adapter = LangChainLLMAdapter(mock_llm)
        with pytest.raises(ConnectionError, match="Failed to connect to LLM endpoint"):
            await adapter.invoke([{"role": "human", "content": "Hi"}])
        assert mock_llm.ainvoke.call_count == 1


class TestStream:
    """Test stream yields chunks."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self) -> None:
        chunk1 = MagicMock(content="Hello ")
        chunk2 = MagicMock(content="world")
        chunk3 = MagicMock(content="")  # empty chunk should be skipped

        async def fake_astream(messages):
            for chunk in [chunk1, chunk2, chunk3]:
                yield chunk

        mock_llm = MagicMock()
        mock_llm.astream = fake_astream
        adapter = LangChainLLMAdapter(mock_llm)
        chunks = []
        async for chunk in adapter.stream([{"role": "human", "content": "Hi"}]):
            chunks.append(chunk)
        assert chunks == ["Hello ", "world"]
