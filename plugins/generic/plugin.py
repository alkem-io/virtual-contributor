"""GenericPlugin — direct LLM invocation with optional history condensation."""

from __future__ import annotations

import logging

from core.events.input import Input
from core.events.response import Response
from core.ports.llm import LLMPort
from plugins.generic.prompts import condenser_system_prompt
from core.domain.query_rewrite import (
    DEFAULT_MAX_EXPANSION_RATIO,
    RewritePolicy,
    recent_history,
    rewrite_query,
    should_rewrite,
)

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

    def __init__(
        self,
        llm: LLMPort,
        *,
        rewrite_policy: RewritePolicy | None = None,
        max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
    ) -> None:
        self._llm = llm
        # None means "never skip" — see GuidancePlugin.
        self._rewrite_policy = rewrite_policy
        self._max_expansion_ratio = max_expansion_ratio

    async def startup(self) -> None:
        logger.info("GenericPlugin started")

    async def shutdown(self) -> None:
        logger.info("GenericPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message

        # Resolve the question against history when that is worth a call.
        if should_rewrite(question, event.history, self._rewrite_policy):
            history_text = _history_as_text(recent_history(event.history))
            condenser_messages = [
                {"role": "system", "content": condenser_system_prompt},
                {"role": "human", "content": f"History:\n{history_text}\n\nLatest question: {question}"},
            ]
            question = await rewrite_query(
                self._llm,
                condenser_messages,
                question,
                max_expansion_ratio=self._max_expansion_ratio,
            )
            logger.info("Condensed question from history")

        # Build final messages
        messages: list[dict] = []
        if event.prompt:
            for sys_msg in event.prompt:
                messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "human", "content": question})

        result = await self._llm.invoke(messages)
        return Response(result=result)
