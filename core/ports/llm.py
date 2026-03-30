from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Port for LLM chat completion interactions."""

    async def invoke(self, messages: list[dict]) -> str:
        """Single chat completion call."""
        ...

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Streaming chat completion call."""
        ...
