"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from core.events.input import Input
from core.events.response import Response, Source
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort
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
        rewrite_policy: RewritePolicy | None = None,
        max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
        max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS,
        max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        # None means "never skip" — the gate is opt-in, so an unconfigured
        # deployment behaves exactly as before apart from output validation.
        self._rewrite_policy = rewrite_policy
        self._max_expansion_ratio = max_expansion_ratio
        self._max_history_turns = max_history_turns
        self._max_history_chars = max_history_chars

    async def startup(self) -> None:
        logger.info("GuidancePlugin started")

    async def shutdown(self) -> None:
        logger.info("GuidancePlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message
        language = event.language or "EN"

        # Resolve the question against history when that is worth a call.
        # Was: an unconditional LLM round-trip on ANY history, whose output was
        # assigned verbatim however malformed, and whose failure aborted the
        # whole request.
        if should_rewrite(question, event.history, self._rewrite_policy):
            from plugins.guidance.prompts import condense_prompt
            history_text = "\n".join(
                f"{h.role}: {h.content}" for h in recent_history(event.history, self._max_history_turns, self._max_history_chars)
            )
            question = await rewrite_query(
                self._llm,
                [{
                    "role": "human",
                    "content": condense_prompt.format(
                        chat_history=history_text, question=question
                    ),
                }],
                question,
                max_expansion_ratio=self._max_expansion_ratio,
            )

        # Query multiple collections in parallel
        n_results = self._n_results

        async def _query_collection(collection: str):
            docs, sources = [], []
            try:
                result = await self._knowledge_store.query(
                    collection=collection, query_texts=[question], n_results=n_results,
                )
                if result.documents:
                    for i, doc in enumerate(result.documents[0]):
                        distance = result.distances[0][i] if result.distances else 1.0
                        score = 1.0 - distance
                        docs.append(doc)
                        meta = result.metadatas[0][i] if result.metadatas else {}
                        source_url = meta.get("source", collection)
                        sources.append(Source(
                            source=source_url,
                            title=meta.get("title"),
                            uri=source_url,
                            score=score,
                        ))
            except Exception:
                logger.warning("Failed to query collection %s", collection)
            return docs, sources

        query_results = await asyncio.gather(
            *[_query_collection(c) for c in DEFAULT_COLLECTIONS]
        )
        all_pairs: list[tuple[str, Source]] = []
        for docs, sources in query_results:
            all_pairs.extend(zip(docs, sources))

        # Sort by relevance (highest score first)
        all_pairs.sort(key=lambda p: p[1].score or 0, reverse=True)

        # Filter by score threshold — discard low-relevance chunks
        all_pairs = [
            (doc, src) for doc, src in all_pairs
            if (src.score or 0) >= self._score_threshold
        ]

        # Deduplicate by source URL, keeping the highest-scoring chunk per page
        seen_sources: set[str] = set()
        deduped: list[tuple[str, Source]] = []
        for idx, (doc, src) in enumerate(all_pairs):
            key = src.source or f"__no_source_{idx}__"
            if key not in seen_sources:
                seen_sources.add(key)
                deduped.append((doc, src))

        deduped = deduped[:self._n_results]

        # Context budget enforcement — drop lowest-scoring chunks if over budget
        total_chars = sum(len(doc) for doc, _ in deduped)
        if total_chars > self._max_context_chars:
            kept: list[tuple[str, Source]] = []
            accumulated = 0
            for doc, src in deduped:
                if accumulated + len(doc) > self._max_context_chars:
                    break
                kept.append((doc, src))
                accumulated += len(doc)
            dropped = len(deduped) - len(kept)
            dropped_chars = total_chars - accumulated
            logger.warning(
                "Context budget exceeded: dropped %d chunks (%d chars)",
                dropped, dropped_chars,
            )
            deduped = kept

        all_docs = [doc for doc, _ in deduped]
        all_sources = [src for _, src in deduped]

        # Prefix each chunk with [source:N] for LLM source attribution
        if all_docs:
            context = "\n\n".join(
                f"[source:{i}] {doc}" for i, doc in enumerate(all_docs)
            )
        else:
            context = "No relevant context found."

        # Generate response
        from plugins.guidance.prompts import retrieve_prompt
        answer = await self._llm.invoke([{
            "role": "human",
            "content": retrieve_prompt.format(
                context=context, question=question, language=language
            ),
        }])

        # Try to parse JSON response for source scores
        parsed_sources = self._parse_json_sources(answer)
        if parsed_sources is not None:
            return Response(
                result=parsed_sources.get("answer", answer),
                sources=all_sources,
                human_language=language,
            )

        logger.warning("Structured JSON parsing failed, returning raw LLM text")
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
