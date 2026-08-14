"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import time
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
from core.domain import hybrid_retrieval
from core.events.input import Input
from core.events.response import Response, Source
from core.domain.retrieval_filters import FACTUAL_WHERE
from core.ports.llm import LLMPort
from core.domain.faithfulness import safe_reason as _safe_reason
from core.ports.faithfulness import FaithfulnessValidatorPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.reranker import RerankerPort
from core.domain.routing import DEFAULT_ROUTING_TABLE, RetrievalProfile
from core.ports.query_router import QueryRouterPort, RouteClass, RoutingDecision

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
        hybrid_config: Any = None,
        reranker: RerankerPort | None = None,
        rerank_candidate_n: int = 20,
        rerank_top_k: int = 5,
        query_router: QueryRouterPort | None = None,
        routing_table: dict | None = None,        faithfulness_validator: FaithfulnessValidatorPort | None = None,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        # Absent unless re-ranking is enabled, so an existing deployment keeps
        # exactly its current merge behaviour.
        self._reranker = reranker
        self._rerank_candidate_n = rerank_candidate_n
        self._rerank_top_k = rerank_top_k        # Absent unless validation is enabled. Its absence is the off switch.
        self._faithfulness_validator = faithfulness_validator
        self._max_context_chars = max_context_chars
        self._answering_temperature = answering_temperature
        self._chain_of_thought_enabled = chain_of_thought_enabled
        # None keeps retrieval exactly as it was — the helper reads the flag
        # off this and falls through to the dense path.
        self._hybrid_config = hybrid_config        # Absent unless routing is enabled, so an existing deployment keeps
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
            # Validated, not trusted. The port is a Protocol with no runtime
            # return-type enforcement, so a substituted router may hand back
            # None, a bare string, or an object with no `route`. Every one of
            # those would raise out of here and turn a query that would
            # otherwise be answered into a retried, then failed, request —
            # breaking the promise this method's docstring makes.
            if not isinstance(decision, RoutingDecision):
                logger.warning(
                    "Query router returned %s, not a RoutingDecision; "
                    "using unrouted defaults",
                    type(decision).__name__,
                )
                return unrouted
            if not isinstance(decision.route, RouteClass):
                logger.warning(
                    "Query router returned an unknown route type (%s); "
                    "using unrouted defaults",
                    type(decision.route).__name__,
                )
                return unrouted
            profile = self._routing_table.get(decision.route)
            if profile is None:
                logger.warning(
                    "No profile for route %s; using defaults", decision.route,
                )
                return unrouted
            # The route, never the reason. `reason` is free text a substituted
            # classifier could build from the member's own question, and this
            # line goes to stdout and on to central logging.
            logger.info(
                "Routed query as %s: retrieve=%s n_results=%d budget=%d",
                decision.route.value,
                profile.retrieve, profile.n_results, profile.max_context_chars,
            )
            logger.debug("Routing reason: %s", decision.reason)
        except Exception:
            logger.warning(
                "Query classification failed; using unrouted defaults",
                exc_info=True,
            )
            return unrouted
        return profile

    def _validate_faithfulness(self, *, answer: str, context: str) -> None:
        """Observe whether the answer was supportable. Never changes it.

        Guidance represents "nothing retrieved" as a sentinel string rather
        than an empty one, which the detector handles explicitly — checking
        only for emptiness would silently do nothing here.

        Wrapped defensively: a fault in a diagnostic must never cost a member
        their answer.
        """
        if self._faithfulness_validator is None:
            return
        try:
            verdict = self._faithfulness_validator.validate(
                answer=answer, context=context,
            )
            if not verdict.supported:
                # The reason CODE only. `detail` is free text a substituted
                # validator could build from the member's own answer, and this
                # record goes to stdout and on to central logging.
                logger.warning(
                    "Unsupported answer: plugin=guidance reason=%s answer_chars=%d",
                    _safe_reason(verdict.reason), len(answer),
                )
        except Exception as exc:
            # The exception TYPE, not the traceback: a raised message could
            # otherwise carry the answer out through the failure path.
            logger.warning(
                "Faithfulness validation failed: error_type=%s",
                type(exc).__name__,
            )

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

        # One decision per query, resolved on the condensed question — that is
        # what retrieval will actually run against.
        profile = self._resolve_profile(question)

        # Query multiple collections in parallel
        # #116's profile decides the base width; #115's reranker needs its
        # candidate pool regardless, so the fetch is the larger of the two.
        # Truncation back down happens after dedupe.
        n_results = (
            max(profile.n_results, self._rerank_candidate_n)
            if self._reranker
            else profile.n_results
        )
        # Which ordering applies below. Read once here, from the same flag the
        # retrieval helper reads, so the ordering can never disagree with the
        # shape of the results it is ordering.
        hybrid_enabled = bool(
            getattr(self._hybrid_config, "hybrid_retrieval_enabled", False)
        )

        async def _query_collection(collection: str):
            # Rank within the collection is carried out of here: it is the
            # fused order, the only ordering that means anything across arms.
            # A score cannot stand in for it — a literally-matched passage has
            # none. The metadata rides alongside solely for the LLM-visible
            # context label (#109); the factual filter (#107) applies to both
            # arms inside the retrieval span (#108).
            entries: list[tuple[int, str, Source, dict]] = []
            from opentelemetry.trace import SpanKind

            from core.tracing import optional_span

            try:
                # optional_span records any failure (content-gated) and
                # re-raises; the outer handler isolates this collection.
                with optional_span("vc.retrieval", kind=SpanKind.CLIENT):
                    result = await hybrid_retrieval.retrieve(
                        self._knowledge_store, collection, question,
                        self._hybrid_config, n_results=n_results,
                        where=FACTUAL_WHERE,
                    )
                    if result.documents:
                        for i, doc in enumerate(result.documents[0]):
                            distance = (
                                result.distances[0][i] if result.distances else 1.0
                            )
                            # No distance means the passage was matched
                            # literally, not by similarity — inventing a score
                            # would misrepresent it as a semantic hit.
                            score = None if distance is None else 1.0 - distance
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
                            entries.append((i, doc, source, metadata))
            except Exception:
                logger.warning("Failed to query collection %s", collection)
            return entries

        ranked: list[tuple[int, str, Source, dict]] = []
        if profile.retrieve:
            query_results = await asyncio.gather(
                *[_query_collection(c) for c in DEFAULT_COLLECTIONS]
            )
            for entries in query_results:
                ranked.extend(entries)
        # Otherwise: small talk. All three collection queries are skipped
        # outright rather than run and discarded.

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
        all_pairs: list[tuple[str, Source, dict]] = [(d, s, m) for _, d, s, m in ranked]
        # Re-rank the merged pool (#115). One scorer applied uniformly is what
        # makes the cross-collection merge sound: three separately-populated
        # collections produce only loosely comparable distances, so a sparse
        # corpus loses every comparison regardless of how well it answers.
        # Runs AFTER the hybrid/dense ordering above — it reorders whatever
        # that produced — and no truncation happens here: cutting to top-K
        # before the dedupe below would let several chunks from one page
        # consume the budget and return fewer distinct sources than asked.
        if self._reranker is not None:
            docs_only = [doc for doc, _, _ in all_pairs]
            vector_scores = [src.score or 0.0 for _, src, _ in all_pairs]
            started = time.perf_counter()
            order = self._reranker.rerank(question, docs_only, vector_scores)
            all_pairs = [all_pairs[i] for i in order]
            logger.info(
                "Re-ranked %d merged candidates across %d collections in %.1fms",
                len(docs_only), len(DEFAULT_COLLECTIONS),
                (time.perf_counter() - started) * 1000,
            )

        # Filter by score threshold — discard low-relevance chunks. A passage
        # with no score was matched literally rather than by similarity, so the
        # threshold does not apply to it; treating its absent score as 0 would
        # drop exactly the exact-name matches the lexical arm exists to find.
        all_pairs = [
            (doc, src, metadata) for doc, src, metadata in all_pairs
            if src.score is None or src.score >= profile.score_threshold
        ]

        # Deduplicate by source URL, keeping the highest-scoring chunk per page
        seen_sources: set[str] = set()
        deduped: list[tuple[str, Source, dict]] = []
        for idx, (doc, src, metadata) in enumerate(all_pairs):
            key = src.source or f"__no_source_{idx}__"
            if key not in seen_sources:
                seen_sources.add(key)
                deduped.append((doc, src, metadata))

        # Truncate only now, after dedupe, so K distinct sources are returned
        # whenever K distinct sources exist. The width is the profile's (#116)
        # — applying it at the query but not here would fetch extra evidence
        # and silently discard it — narrowed to top-K when re-ranking (#115).
        deduped = deduped[
            : (self._rerank_top_k if self._reranker else profile.n_results)
        ]

        # Context budget enforcement — drop lowest-scoring chunks if over budget
        # #109's rendered-block budgeting, keeping #108's `dropped` counter
        # so the span attribute still reports what the budget discarded; the
        # budget itself is the profile's (#116).
        dropped = 0
        formatted_blocks = [
            render_document_block(number, doc, metadata)
            for number, (doc, _, metadata) in enumerate(deduped, start=1)
        ]
        total_budget_size = sum(
            rendered_document_budget_size(block, doc)
            for block, (doc, _, _) in zip(formatted_blocks, deduped)
        )
        if total_budget_size > profile.max_context_chars:
            kept: list[tuple[str, Source, dict]] = []
            kept_blocks: list[str] = []
            accumulated = 0
            for block, (doc, src, metadata) in zip(formatted_blocks, deduped):
                document_budget_size = rendered_document_budget_size(block, doc)
                if accumulated + document_budget_size > profile.max_context_chars:
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

        # Validate the string the MEMBER receives, not the JSON envelope.
        # retrieve_prompt asks for {"answer": ..., "sources": [...]}, and the
        # envelope's own "sources" key is an information-noun — so validating
        # the raw output made detection depend on the model's serialisation
        # format rather than on what it said. It also made the logged
        # answer_chars the envelope's length instead of the answer's, which
        # corrupts the measurement this feature exists to collect.
        member_answer = (
            parsed_sources.get("answer", answer)
            if parsed_sources is not None
            else answer
        )
        self._validate_faithfulness(answer=member_answer, context=context)

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
