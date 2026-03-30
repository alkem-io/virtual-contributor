from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIAssistantAdapter:
    """OpenAI Assistants API adapter for thread-based interactions.

    This adapter wraps the OpenAI Assistants API (threads/runs/files),
    which is fundamentally different from chat completion. It does NOT
    implement LLMPort — the openai-assistant plugin uses it directly.
    """

    def __init__(self, default_timeout: int = 300) -> None:
        self._default_timeout = default_timeout

    def create_client(self, api_key: str) -> AsyncOpenAI:
        """Create a per-request AsyncOpenAI client."""
        return AsyncOpenAI(api_key=api_key)

    async def create_thread(self, client: AsyncOpenAI, message: str) -> Any:
        """Create a new thread with an initial message."""
        thread = await client.beta.threads.create()
        await client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message,
        )
        return thread

    async def get_thread(self, client: AsyncOpenAI, thread_id: str) -> Any:
        """Retrieve an existing thread."""
        return await client.beta.threads.retrieve(thread_id)

    async def add_message(
        self, client: AsyncOpenAI, thread_id: str, message: str
    ) -> None:
        """Add a user message to an existing thread."""
        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message,
        )

    async def attach_files(
        self, client: AsyncOpenAI, assistant_id: str
    ) -> list[str]:
        """List files attached to the assistant for file_search."""
        files = await client.files.list()
        return [f.id for f in files.data]

    async def run_and_poll(
        self,
        client: AsyncOpenAI,
        thread_id: str,
        assistant_id: str,
        timeout: int | None = None,
    ) -> str:
        """Create a run and poll until completion or timeout."""
        timeout = timeout or self._default_timeout
        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )

        start = time.monotonic()
        while True:
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id,
            )
            if run.status == "completed":
                break
            if run.status in ("failed", "cancelled", "expired"):
                raise RuntimeError(f"Run {run.id} ended with status: {run.status}")
            if time.monotonic() - start > timeout:
                raise TimeoutError(
                    f"Run {run.id} timed out after {timeout}s (status: {run.status})"
                )
            await asyncio.sleep(1)

        # Extract the latest assistant message
        messages = await client.beta.threads.messages.list(
            thread_id=thread_id, order="desc", limit=1
        )
        for msg in messages.data:
            if msg.role == "assistant":
                return self._extract_text(msg)

        return ""

    @staticmethod
    def _extract_text(message) -> str:
        """Extract text content from a thread message, stripping citations."""
        parts = []
        for block in message.content:
            if hasattr(block, "text"):
                text = block.text.value
                # Strip citation annotations like 【4:0†source】
                text = re.sub(r"【[^】]*】", "", text)
                parts.append(text.strip())
        return "\n".join(parts)
