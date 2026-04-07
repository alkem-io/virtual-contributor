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

    def __init__(self, llm, timeout: float = 120.0) -> None:
        self._llm = llm
        self._timeout = timeout

    def _sync_invoke(self, lc_messages: list[BaseMessage]) -> str:
        """Synchronous LLM call — runs in a thread to avoid blocking the event loop."""
        result = self._llm.invoke(lc_messages)
        # Log token usage if available (FR-011)
        usage = getattr(result, "usage_metadata", None)
        if usage:
            logger.debug(
                "Token usage — input: %s, output: %s",
                usage.get("input_tokens", "N/A"),
                usage.get("output_tokens", "N/A"),
            )
        return str(result.content)

    async def invoke(self, messages: list[dict]) -> str:
        lc_messages = _to_langchain_messages(messages)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                # Run sync invoke in a thread so the event loop stays free
                # for RabbitMQ heartbeats and other async tasks
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._sync_invoke, lc_messages),
                    timeout=self._timeout,
                )
                return result
            except asyncio.TimeoutError:
                last_exc = TimeoutError(
                    f"LLM call timed out after {self._timeout}s"
                )
                logger.warning(
                    "LLM invoke attempt %d timed out after %.0fs, retrying",
                    attempt + 1,
                    self._timeout,
                )
                await asyncio.sleep(BASE_DELAY * (2**attempt))
            except (ConnectionError, OSError) as exc:
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
