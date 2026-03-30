"""OpenAIAssistantPlugin — thread-based interactions via Assistants API."""

from __future__ import annotations

import logging

from core.adapters.openai_assistant import OpenAIAssistantAdapter
from core.events.input import Input
from core.events.response import Response
from plugins.openai_assistant.utils import strip_citations

logger = logging.getLogger(__name__)


class OpenAIAssistantPlugin:
    """OpenAI Assistant plugin using threads/runs/files.

    Creates or resumes conversation threads with the OpenAI Assistants API.
    Per-request client creation via external_config.api_key.
    """

    name = "openai-assistant"
    event_type = Input

    def __init__(self, openai_assistant: OpenAIAssistantAdapter) -> None:
        self._assistant = openai_assistant

    async def startup(self) -> None:
        logger.info("OpenAIAssistantPlugin started")

    async def shutdown(self) -> None:
        logger.info("OpenAIAssistantPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        if not event.external_config or not event.external_config.api_key:
            return Response(result="Error: Missing API key in externalConfig")
        if not event.external_config.assistant_id:
            return Response(result="Error: Missing assistantId in externalConfig")

        api_key = event.external_config.api_key
        assistant_id = event.external_config.assistant_id
        client = self._assistant.create_client(api_key)

        # Resume or create thread
        thread_id = None
        if event.external_metadata and event.external_metadata.thread_id:
            thread_id = event.external_metadata.thread_id
            await self._assistant.add_message(client, thread_id, event.message)
        else:
            thread = await self._assistant.create_thread(client, event.message)
            thread_id = thread.id

        # Run and poll
        answer = await self._assistant.run_and_poll(
            client=client,
            thread_id=thread_id,
            assistant_id=assistant_id,
        )

        return Response(
            result=strip_citations(answer),
            thread_id=thread_id,
        )
