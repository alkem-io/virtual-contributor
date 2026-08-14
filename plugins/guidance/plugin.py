"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from core.events.input import Input
from core.events.response import Response, Source
from core.domain.routing import DEFAULT_ROUTING_TABLE, RetrievalProfile
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.query_router import QueryRouterPort

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
        query_router: QueryRouterPort | None = None,
        routing_table: dict | None = None,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        # Absent unless routing is enabled, so an existing deployment keeps
        # exactly its current behaviour on its current code path.
        self._query_router = query_router
        self._routing_table = routing_table or DEFAULT_ROUTING_TABLE

    def _resolve_profile(self, message: str) -> RetrievalProfile:
        """Decide this query's retrieval settings.

        Classification is an optimisation, never a dependency of answering: a
        failure here serves the query with the configured defaults, which is
        what happens with routing switched off.
        """
        unrouted = RetrievalProfile(
            retrieve=True,
            n_results=self._n_results,
            score_threshold=self._score_threshold,
            max_context_chars=self._max_context_chars,
        )
        if self._query_router is None:
            return unrouted
        try:
            decision = self._query_router.classify(message)
        except Exception:
            logger.warning(
                "Query classification failed; using unrouted defaults",
                exc_info=True,
            )
            return unrouted
        profile = self._routing_table.get(decision.route)
        if profile is None:
            logger.warning("No profile for route %s; using defaults", decision.route)
            return unrouted
        logger.info(
            "Routed query as %s (%s): retrieve=%s n_results=%d budget=%d",
            decision.route.value, decision.reason,
            profile.retrieve, profile.n_results, profile.max_context_chars,
        )
        return profile

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

        # One decision per query, resolved on the condensed question — that is
        # what retrieval will actually run against.
        profile = self._resolve_profile(question)

        # Query multiple collections in parallel
        n_results = profile.n_results

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

        all_pairs: list[tuple[str, Source]] = []
        if profile.retrieve:
            query_results = await asyncio.gather(
                *[_query_collection(c) for c in DEFAULT_COLLECTIONS]
            )
            for docs, sources in query_results:
                all_pairs.extend(zip(docs, sources))
        # Otherwise: small talk. All three collection queries are skipped
        # outright rather than run and discarded.

        # Sort by relevance (highest score first)
        all_pairs.sort(key=lambda p: p[1].score or 0, reverse=True)

        # Filter by score threshold — discard low-relevance chunks
        all_pairs = [
            (doc, src) for doc, src in all_pairs
            if (src.score or 0) >= profile.score_threshold
        ]

        # Deduplicate by source URL, keeping the highest-scoring chunk per page
        seen_sources: set[str] = set()
        deduped: list[tuple[str, Source]] = []
        for idx, (doc, src) in enumerate(all_pairs):
            key = src.source or f"__no_source_{idx}__"
            if key not in seen_sources:
                seen_sources.add(key)
                deduped.append((doc, src))

        # The SAME width the store was asked for. Applying the profile at the
        # query but not here would fetch the extra evidence and then discard
        # it at truncation — the widening would be invisible downstream.
        deduped = deduped[:profile.n_results]

        # Context budget enforcement — drop lowest-scoring chunks if over budget
        total_chars = sum(len(doc) for doc, _ in deduped)
        if total_chars > profile.max_context_chars:
            kept: list[tuple[str, Source]] = []
            accumulated = 0
            for doc, src in deduped:
                if accumulated + len(doc) > profile.max_context_chars:
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
