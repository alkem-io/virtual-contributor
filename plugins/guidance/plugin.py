"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import re

from core.domain import hybrid_retrieval
from core.events.input import Input
from core.events.response import Response, Source
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
        hybrid_config: Any = None,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        # None keeps retrieval exactly as it was — the helper reads the flag
        # off this and falls through to the dense path.
        self._hybrid_config = hybrid_config

    async def startup(self) -> None:
        logger.info("GuidancePlugin started")

    async def shutdown(self) -> None:
        logger.info("GuidancePlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message
        language = event.language or "EN"

        # Condense history if present
        if event.history:
            from plugins.guidance.prompts import condense_prompt
            history_text = "\n".join(
                f"{h.role}: {h.content}" for h in event.history
            )
            condensed = await self._llm.invoke([{
                "role": "human",
                "content": condense_prompt.format(
                    chat_history=history_text, question=question
                ),
            }])
            question = condensed

        # Query multiple collections in parallel
        n_results = self._n_results
        # Which ordering applies below. Read once here, from the same flag the
        # retrieval helper reads, so the ordering can never disagree with the
        # shape of the results it is ordering.
        hybrid_enabled = bool(
            getattr(self._hybrid_config, "hybrid_retrieval_enabled", False)
        )

        async def _query_collection(collection: str):
            # Rank within the collection is carried out of here: it is the
            # fused order, and it is the only ordering that means anything
            # across arms. A score cannot stand in for it — a passage matched
            # literally has none.
            docs, sources, ranks = [], [], []
            try:
                result = await hybrid_retrieval.retrieve(
                    self._knowledge_store, collection, question,
                    self._hybrid_config, n_results=n_results,
                )
                if result.documents:
                    for i, doc in enumerate(result.documents[0]):
                        distance = result.distances[0][i] if result.distances else 1.0
                        # No distance means the passage was matched literally,
                        # not by similarity — there is no score to report, and
                        # inventing one would misrepresent it as a semantic hit.
                        score = None if distance is None else 1.0 - distance
                        docs.append(doc)
                        ranks.append(i)
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
            return docs, sources, ranks

        query_results = await asyncio.gather(
            *[_query_collection(c) for c in DEFAULT_COLLECTIONS]
        )
        ranked: list[tuple[int, str, Source]] = []
        for docs, sources, ranks in query_results:
            ranked.extend(zip(ranks, docs, sources))

        if hybrid_enabled:
            # Merge the collections by each passage's rank within its own
            # collection, so the best of each competes with the best of the
            # others. Ordering by score instead would sink every
            # literally-matched passage below every scored one and then slice
            # it away — discarding exactly what the lexical arm contributes.
            #
            # Within one rank, a passage with no score comes first. It was
            # matched literally — a different kind of evidence, not weaker
            # evidence — and it already earned its rank against the semantic
            # hits inside its own collection. Ordering it behind its scored
            # peers puts it just past wherever the list is truncated, which is
            # how it was being discarded despite ranking well: three
            # collections each contribute a rank-1, and the cut lands mid-tier.
            ranked.sort(
                key=lambda r: (
                    r[0],
                    r[2].score is not None,
                    -(r[2].score if r[2].score is not None else 0.0),
                )
            )
        else:
            # Dense-only. Every passage has a comparable semantic score, so the
            # collections merge on that score globally — which is what this
            # code did before hybrid retrieval existed.
            #
            # Rank-first ordering must NOT be used here. It interleaves the
            # collections round-robin, so a weak collection's best hit outranks
            # a strong collection's second — and since the list is truncated to
            # n_results straight after, that does not merely reorder the
            # sources, it changes which ones survive. This path is reached
            # whenever the feature is off, so it must be a true rollback.
            ranked.sort(key=lambda r: -(r[2].score if r[2].score is not None else 0.0))
        all_pairs: list[tuple[str, Source]] = [(d, s) for _, d, s in ranked]

        # Filter by score threshold — discard low-relevance chunks. A passage
        # with no score was matched literally rather than by similarity, so the
        # threshold does not apply to it; treating its absent score as 0 would
        # drop exactly the exact-name matches the lexical arm exists to find.
        all_pairs = [
            (doc, src) for doc, src in all_pairs
            if src.score is None or src.score >= self._score_threshold
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
