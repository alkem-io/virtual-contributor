from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


def _to_langchain_messages(messages: list[dict]) -> list[BaseMessage]:
    """Convert dict messages to LangChain message objects."""
    result = []
    for msg in messages:
        role = msg.get("role", "human")
        content = msg.get("content", "")
        if role in ("system",):
            result.append(SystemMessage(content=content))
        elif role in ("assistant", "ai"):
            result.append(AIMessage(content=content))
        else:
            result.append(HumanMessage(content=content))
    return result


class OpenAILLMAdapter:
    """LLM adapter for OpenAI models via langchain-openai."""

    def __init__(self, api_key: str, model_name: str = "gpt-4o") -> None:
        self._llm = ChatOpenAI(
            api_key=api_key,
            model=model_name,
        )

    async def invoke(self, messages: list[dict]) -> str:
        lc_messages = _to_langchain_messages(messages)
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                result = await self._llm.ainvoke(lc_messages)
                return str(result.content)
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "OpenAI invoke attempt %d failed, retrying in %.1fs: %s",
                        attempt + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        lc_messages = _to_langchain_messages(messages)
        async for chunk in self._llm.astream(lc_messages):
            if chunk.content:
                yield str(chunk.content)
