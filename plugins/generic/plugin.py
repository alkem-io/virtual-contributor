"""GenericPlugin — direct LLM invocation with optional history condensation."""

from __future__ import annotations

import logging

from core.domain.retrieval_filters import FACTUAL_WHERE
from core.events.input import Input
from core.events.response import Response
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from plugins.generic.prompts import condenser_system_prompt
from core.domain.query_rewrite import (
    DEFAULT_MAX_EXPANSION_RATIO,
    DEFAULT_MAX_HISTORY_CHARS,
    DEFAULT_MAX_HISTORY_TURNS,
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
        knowledge_store: KnowledgeStorePort | None = None,
        rewrite_policy: RewritePolicy | None = None,
        max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
        max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS,
        max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
    ) -> None:
        self._llm = llm
        # Absent unless the deployment registered a vector store (container
        # auto-injects it iff `config.vector_db_host` is configured). Its
        # absence is the signal a retrieve-bearing graph payload fails
        # loudly on, never silently skips (FR-005).
        self._knowledge_store = knowledge_store
        # None means "never skip" — see GuidancePlugin.
        self._rewrite_policy = rewrite_policy
        self._max_expansion_ratio = max_expansion_ratio
        self._max_history_turns = max_history_turns
        self._max_history_chars = max_history_chars

    async def startup(self) -> None:
        logger.info("GenericPlugin started")

    async def shutdown(self) -> None:
        logger.info("GenericPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        # A prompt-graph payload takes the entire flow over — BEFORE
        # condensation. The graph's own steps (input check, message
        # analysis, design extraction) consume the whole bounded
        # conversation; condensing it first would destroy multi-turn
        # slot-filling (FR-004). Invocations without a payload are
        # completely unaffected by everything below this branch.
        if event.prompt_graph:
            return await self._handle_with_graph(event)

        question = event.message

        # Resolve the question against history when that is worth a call.
        if should_rewrite(question, event.history, self._rewrite_policy):
            history_text = _history_as_text(recent_history(event.history, self._max_history_turns, self._max_history_chars))
            condenser_messages = [
                {"role": "system", "content": condenser_system_prompt},
                {"role": "human", "content": f"History:\n{history_text}\n\nLatest question: {question}"},
            ]
            from core.tracing import optional_span

            with optional_span("vc.stage query_processing") as span:
                if span is not None:
                    span.set_attribute("vc.history_turns", len(event.history))
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

    async def _handle_with_graph(self, event: Input) -> Response:
        """Execute the caller-supplied prompt-graph payload (FR-004, FR-005, FR-012).

        Config-error and runtime exceptions (e.g.
        :class:`PromptGraphConfigError`, a knowledge-store failure) are not
        caught here — they propagate to the caller's standard error-response
        path (``main.py``), matching expert's graph path and FR-009's
        fail-loudly philosophy.
        """
        from core.domain.prompt_graph import PromptGraph

        # Resolved server-side, exactly once, the same way expert's `collection`
        # is computed in `handle()` — never from the graph's rendered
        # `collection_template` argument. `collection_template` may only
        # reference `{bok_id}` (enforced at PromptGraph parse time), but a
        # payload's own nodes can still overwrite the `bok_id` *state* value
        # before a retrieve node runs (e.g. an upstream LLM node's structured
        # output). Ignoring the retriever's `collection` argument entirely
        # closes that gap: whatever the payload computes, retrieval is always
        # scoped to the caller's own body of knowledge.
        bok_id = event.body_of_knowledge_id or ""
        collection_name = f"{bok_id}-knowledge" if bok_id else "default-knowledge"

        retriever = None
        if self._knowledge_store is not None:
            store = self._knowledge_store

            async def _retrieve(collection: str, query: str, n_results: int) -> list[str]:
                result = await store.query(
                    collection_name, [query], n_results=n_results, where=FACTUAL_WHERE,
                )
                return result.documents[0] if result.documents else []

            retriever = _retrieve

        graph = PromptGraph.from_definition(event.prompt_graph)
        graph.compile(llm=self._llm, retriever=retriever)

        # Expert-parity initial state seeding (contracts/prompt-graph-json.md
        # §Execution contract) — the same seed keys keep payloads portable
        # across engines. History is bounded exactly as elsewhere in this
        # plugin, and NOT condensed — the flow's own steps analyse it raw.
        history = recent_history(event.history, self._max_history_turns, self._max_history_chars)
        messages = [
            {
                "role": h.role.value if hasattr(h.role, "value") else str(h.role),
                "content": h.content,
            }
            for h in history
        ]
        messages.append({"role": "human", "content": event.message})
        conversation = "\n".join(
            f"{m['role']}:\n{m['content']}" for m in messages
        )

        initial_state = {
            "messages": messages,
            "current_question": event.message,
            "conversation": conversation,
            "bok_id": event.body_of_knowledge_id or "",
            "description": event.description,
            "display_name": event.display_name,
        }

        final_state = await graph.invoke(initial_state)

        answer = final_state.get("final_answer") or final_state.get("result", "")
        return Response(
            result=answer,
            human_language=event.language,
            result_language=final_state.get("result_language"),
            knowledge_language=final_state.get("knowledge_language"),
            original_result=final_state.get("original_result"),
            sources=[],
        )
