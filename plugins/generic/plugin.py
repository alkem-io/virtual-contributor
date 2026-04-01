"""GenericPlugin — direct LLM invocation with optional history condensation."""

from __future__ import annotations

import logging

from core.events.input import Input
from core.events.response import Response
from core.ports.llm import LLMPort
from plugins.generic.prompts import condenser_system_prompt

logger = logging.getLogger(__name__)


def _history_as_text(history: list) -> str:
    """Convert history items to a readable text block."""
    lines = []
    for item in history:
        role = item.role if hasattr(item, "role") else item.get("role", "human")
        content = item.content if hasattr(item, "content") else item.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


class GenericPlugin:
    """Handles generic LLM queries with per-request engine selection.

    Supports optional history condensation when chat history is present.
    LLM provider is selected per-request via input.engine + external_config.api_key.
    """

    name = "generic"
    event_type = Input

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def startup(self) -> None:
        logger.info("GenericPlugin started")

    async def shutdown(self) -> None:
        logger.info("GenericPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message

        # Condense history if present
        if event.history:
            history_text = _history_as_text(event.history)
            condenser_messages = [
                {"role": "system", "content": condenser_system_prompt},
                {"role": "human", "content": f"History:\n{history_text}\n\nLatest question: {question}"},
            ]
            question = await self._llm.invoke(condenser_messages)
            logger.info("Condensed question from history")

        # Build final messages
        messages: list[dict] = []
        if event.prompt:
            for sys_msg in event.prompt:
                messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "human", "content": question})

        result = await self._llm.invoke(messages)
        return Response(result=result)
