"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from core.domain.prompts_shared import (
    STEP_BY_STEP_ANSWER_INSTRUCTIONS,
    citation_scope_instruction,
    empty_context_instruction,
    join_document_blocks,
    render_document_block,
    rendered_document_budget_size,
)
from core.domain.query_complexity import QueryComplexity, classify_question
from core.events.input import Input
from core.events.response import Response, Source
from core.domain.retrieval_filters import FACTUAL_WHERE
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort

logger = logging.getLogger(__name__)

# Default collections for guidance
DEFAULT_COLLECTIONS = [
    "alkem.io-knowledge",
    "welcome.alkem.io-knowledge",
    "www.alkemio.org-knowledge",
]


class GuidancePlugin:
    """Multi-collection RAG guidance plugin.

    Condenses history, queries 3 knowledge collections, filters by
    relevance score, and generates a response with source references.
    """

    name = "guidance"
    event_type = Input

    def __init__(
        self,
        llm: LLMPort,
        knowledge_store: KnowledgeStorePort,
        *,
        n_results: int = 5,
        score_threshold: float = 0.3,
        max_context_chars: int = 20000,
        answering_temperature: float | None = None,
        chain_of_thought_enabled: bool = True,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        self._answering_temperature = answering_temperature
        self._chain_of_thought_enabled = chain_of_thought_enabled

    async def startup(self) -> None:
        logger.info("GuidancePlugin started")

    async def shutdown(self) -> None:
        logger.info("GuidancePlugin stopped")

    def _complexity_instruction(self, question: str) -> str:
        """Return the private-reasoning instruction only for complex questions."""

        if not self._chain_of_thought_enabled:
            return ""
        complexity, _ = classify_question(question)
        if complexity is QueryComplexity.COMPLEX:
            return STEP_BY_STEP_ANSWER_INSTRUCTIONS
        return ""

    async def _invoke_answering(self, prompt: str) -> str:
        """Invoke the shared adapter without changing non-answering calls."""

        messages = [{"role": "human", "content": prompt}]
        if self._answering_temperature is None:
            return await self._llm.invoke(messages)
        return await self._llm.invoke(
            messages, temperature=self._answering_temperature
        )

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message
        language = event.language or "EN"

        # Condense history if present
        if event.history:
            from plugins.guidance.prompts import condense_prompt

            history_text = "\n".join(
                f"{h.role}: {h.content}" for h in event.history
            )
            from core.tracing import optional_span

            with optional_span("vc.stage query_processing") as span:
                if span is not None:
                    span.set_attribute("vc.history_turns", len(event.history))
                condensed = await self._llm.invoke([{
                    "role": "human",
                    "content": condense_prompt.format(
                        chat_history=history_text, question=question
                    ),
                }])
            question = condensed

        # Query multiple collections in parallel
        n_results = self._n_results

        async def _query_collection(collection: str) -> list[tuple[str, Source, dict]]:
            pairs: list[tuple[str, Source, dict]] = []
            from opentelemetry.trace import SpanKind

            from core.tracing import optional_span

            try:
                # #107's factual filter inside #108's retrieval span, over
                # #109's 3-tuple shape (the metadata travels alongside the
                # Source solely for the LLM-visible context label).
                # optional_span records any failure (content-gated) and
                # re-raises; the outer handler isolates this collection.
                with optional_span("vc.retrieval", kind=SpanKind.CLIENT):
                    result = await self._knowledge_store.query(
                        collection=collection,
                        query_texts=[question],
                        n_results=n_results,
                        where=FACTUAL_WHERE,
                    )
                    if result.documents:
                        for i, doc in enumerate(result.documents[0]):
                            distance = (
                                result.distances[0][i] if result.distances else 1.0
                            )
                            score = 1.0 - distance
                            metadata = (
                                result.metadatas[0][i] if result.metadatas else {}
                            )
                            source_url = metadata.get("source", collection)
                            # Source construction stays byte-for-byte
                            # compatible with the pre-feature envelope.
                            source = Source(
                                source=source_url,
                                title=metadata.get("title"),
                                uri=source_url,
                                score=score,
                            )
                            pairs.append((doc, source, metadata))
            except Exception:
                logger.warning("Failed to query collection %s", collection)
            return pairs

        query_results = await asyncio.gather(
            *[_query_collection(c) for c in DEFAULT_COLLECTIONS]
        )
        all_pairs: list[tuple[str, Source, dict]] = []
        for pairs in query_results:
            all_pairs.extend(pairs)

        # Sort by relevance (highest score first)
        all_pairs.sort(key=lambda p: p[1].score or 0, reverse=True)

        # Filter by score threshold — discard low-relevance chunks
        all_pairs = [
            (doc, src, metadata) for doc, src, metadata in all_pairs
            if (src.score or 0) >= self._score_threshold
        ]

        # Deduplicate by source URL, keeping the highest-scoring chunk per page
        seen_sources: set[str] = set()
        deduped: list[tuple[str, Source, dict]] = []
        for idx, (doc, src, metadata) in enumerate(all_pairs):
            key = src.source or f"__no_source_{idx}__"
            if key not in seen_sources:
                seen_sources.add(key)
                deduped.append((doc, src, metadata))

        deduped = deduped[:self._n_results]

        # Context budget enforcement — drop lowest-scoring chunks if over budget
        # #109's rendered-block budgeting, keeping #108's `dropped` counter
        # so the span attribute still reports what the budget discarded.
        dropped = 0
        formatted_blocks = [
            render_document_block(number, doc, metadata)
            for number, (doc, _, metadata) in enumerate(deduped, start=1)
        ]
        total_budget_size = sum(
            rendered_document_budget_size(block, doc)
            for block, (doc, _, _) in zip(formatted_blocks, deduped)
        )
        if total_budget_size > self._max_context_chars:
            kept: list[tuple[str, Source, dict]] = []
            kept_blocks: list[str] = []
            accumulated = 0
            for block, (doc, src, metadata) in zip(formatted_blocks, deduped):
                document_budget_size = rendered_document_budget_size(block, doc)
                if accumulated + document_budget_size > self._max_context_chars:
                    break
                kept.append((doc, src, metadata))
                kept_blocks.append(block)
                accumulated += document_budget_size
            dropped = len(deduped) - len(kept)
            dropped_budget = total_budget_size - accumulated
            logger.warning(
                "Context budget exceeded: dropped %d chunks (%d budget units)",
                dropped, dropped_budget,
            )
            deduped = kept
            formatted_blocks = kept_blocks

        all_sources = [src for _, src, _ in deduped]

        # Cross-collection signals belong on the root rather than incorrectly
        # attributing merged filtering to one query.
        from core.tracing import current_root_span, mark_empty_retrieval

        root = current_root_span()
        root.set_attribute("vc.retrieval.chunks_passed", len(deduped))
        root.set_attribute("vc.retrieval.chunks_dropped_budget", dropped)
        if not deduped:
            mark_empty_retrieval()

        # #109 supersedes the old [source:N] prefixing: numbered blocks the
        # model can cite as [Document N], with the empty case handled inside.
        context = join_document_blocks(formatted_blocks)

        # Generate response
        from plugins.guidance.prompts import retrieve_prompt
        prompt = retrieve_prompt.format(
            context=context,
            question=question,
            language=language,
            empty_context_instruction=empty_context_instruction(bool(deduped)),
            citation_scope_instruction=citation_scope_instruction(len(deduped)),
        )
        complexity_instruction = self._complexity_instruction(question)
        if complexity_instruction:
            # Keep the pre-existing structured JSON contract as the final
            # instruction.  The conditional guidance is additive, but placing
            # it before context avoids competing with the required response
            # shape at the end of the prompt.
            prompt = prompt.replace(
                "\n\nContext:\n",
                f"\n\n{complexity_instruction}\n\nContext:\n",
                1,
            )
        answer = await self._invoke_answering(prompt)

        # Try to parse JSON response for source scores
        parsed_sources = self._parse_json_sources(answer)
        if parsed_sources is not None:
            return Response(
                result=parsed_sources.get("answer", answer),
                sources=all_sources,
                human_language=language,
            )

        logger.warning("Structured JSON parsing failed, returning raw LLM text")
        current_root_span().add_event("vc.parse_fallback")
        return Response(
            result=answer,
            sources=all_sources,
            human_language=language,
        )

    @staticmethod
    def _parse_json_sources(text: str) -> dict | None:
        """Try to extract and parse JSON from LLM response.

        Handles: fenced JSON (```json...```), preamble text before JSON,
        trailing text after JSON, and bare JSON objects.
        """
        if not isinstance(text, str) or not text.strip():
            return None

        # 1. Try fenced JSON block (```json ... ``` or ``` ... ```)
        fence_match = re.search(
            r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL
        )
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. Try to find a bare JSON object ({...}) in the text
        brace_start = text.find("{")
        if brace_start != -1:
            # Find the matching closing brace
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[brace_start : i + 1]
                        try:
                            return json.loads(candidate)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        break

        return None
