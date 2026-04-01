"""Unified LangChain LLM adapter — wraps any BaseChatModel, implements LLMPort."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


def _to_langchain_messages(messages: list[dict]) -> list[BaseMessage]:
    """Convert dict messages to LangChain message objects."""
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "human")
        content = msg.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role in ("assistant", "ai"):
            result.append(AIMessage(content=content))
        else:
            result.append(HumanMessage(content=content))
    return result


class LangChainLLMAdapter:
    """Unified LLM adapter wrapping any LangChain BaseChatModel.

    Implements LLMPort with retry logic (3 attempts, exponential backoff)
    for invoke and streaming support via astream.
    """

    def __init__(self, llm) -> None:
        self._llm = llm

    async def invoke(self, messages: list[dict]) -> str:
        lc_messages = _to_langchain_messages(messages)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                result = await self._llm.ainvoke(lc_messages)
                return str(result.content)
            except (ConnectionError, OSError) as exc:
                # Connection errors to local endpoints — fail fast with clear message
                raise ConnectionError(
                    f"Failed to connect to LLM endpoint: {exc}. "
                    "If using a local model, ensure the server is running."
                ) from exc
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2**attempt)
                    logger.warning(
                        "LLM invoke attempt %d failed, retrying in %.1fs: %s",
                        attempt + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        lc_messages = _to_langchain_messages(messages)
        async for chunk in self._llm.astream(lc_messages):
            if chunk.content:
                yield str(chunk.content)
