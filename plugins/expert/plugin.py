"""ExpertPlugin — PromptGraph-based expert with knowledge retrieval."""

from __future__ import annotations

import logging
from typing import Any
import time

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
from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.ports.reranker import RerankerPort

logger = logging.getLogger(__name__)


def _apply_rerank(
    reranker: RerankerPort,
    query: str,
    result: QueryResult,
) -> QueryResult:
    """Re-order a result set, keeping its four parallel lists in step.

    The re-ranker returns a permutation of indices, and every list a caller
    holds must be permuted the same way. Getting this wrong would not raise —
    it would attribute one passage's text to another passage's source URL and
    cite it confidently, which is worse than an error.

    **Reorders only; never truncates.** Cutting to top-K here would hand the
    relevance threshold a pre-filtered list, and re-ranking legitimately lifts
    term-matching passages that are *below* the threshold. Those would then
    occupy the whole top-K and be discarded by the threshold immediately
    after, leaving the answer with fewer sources than it had before
    re-ranking — or none at all, silently ungrounded. Truncation belongs
    after the threshold, where the caller does it.

    Distances are carried through **unmodified**, only reordered. The blended
    ranking score is deliberately not written back: it is normalised across the
    candidate pool, so persisting it would corrupt the relevance threshold
    downstream, which is judged on the real vector distance.
    """
    docs = result.documents[0] if result.documents else []
    if not docs:
        return result

    started = time.perf_counter()
    distances = result.distances[0] if result.distances else []
    metadatas = result.metadatas[0] if result.metadatas else []
    ids = result.ids[0] if result.ids else []

    # The port takes similarity (higher is better), not distance. Passing raw
    # distances would silently invert the ranking. A literally-matched passage
    # (#114) has distance None — no semantic score exists, and 1.0 - None
    # would crash the re-rank; it enters neutral at 0.0 and lets the lexical
    # component of the blend speak for it.
    vector_scores = [
        1.0 - d
        if i < len(distances) and (d := distances[i]) is not None
        else 0.0
        for i in range(len(docs))
    ]

    order = reranker.rerank(query, docs, vector_scores)

    # Logged so an operator can see the stage is running and what it costs
    # without having to reason about it from answer quality alone.
    logger.info(
        "Re-ranked %d candidates in %.1fms",
        len(docs), (time.perf_counter() - started) * 1000,
    )

    return QueryResult(
        documents=[[docs[i] for i in order]],
        metadatas=[[metadatas[i] if i < len(metadatas) else {} for i in order]],
        distances=[[distances[i] if i < len(distances) else 1.0 for i in order]],
        ids=[[ids[i] if i < len(ids) else "" for i in order]],
    )


def _filter_and_format(
    result: QueryResult, score_threshold: float
) -> tuple[list[str], QueryResult]:
    """Filter results by score threshold and render labelled document blocks.

    Returns the formatted doc list and a new QueryResult containing only
    the entries that passed the threshold.
    """
    docs = result.documents[0] if result.documents else []
    distances = result.distances[0] if result.distances else []
    metadatas = result.metadatas[0] if result.metadatas else []
    ids = result.ids[0] if result.ids else []

    kept_docs, kept_distances, kept_metadatas, kept_ids = [], [], [], []
    for i, doc in enumerate(docs):
        # Two different things look like "no distance" and must not be
        # conflated. A distance explicitly recorded as None means the passage
        # was matched literally: the threshold is defined on semantic distance,
        # so it has nothing to say, and dropping the passage would discard
        # exactly the exact-name match the lexical arm exists to find.
        #
        # A distance simply missing from a short list is a malformed result,
        # not a literal match. It scored zero before this feature and is
        # dropped exactly as it was, so turning the feature off restores what
        # the code did before it.
        if i < len(distances):
            distance = distances[i]
            keep = True if distance is None else (1.0 - distance) >= score_threshold
        else:
            distance = None
            keep = 0.0 >= score_threshold
        if keep:
            kept_docs.append(doc)
            kept_distances.append(distance)
            kept_metadatas.append(metadatas[i] if i < len(metadatas) else {})
            kept_ids.append(ids[i] if i < len(ids) else "")

    formatted = [
        render_document_block(number, doc, kept_metadatas[number - 1])
        for number, doc in enumerate(kept_docs, start=1)
    ]
    filtered_result = QueryResult(
        documents=[kept_docs],
        metadatas=[kept_metadatas],
        distances=[kept_distances],
        ids=[kept_ids],
    )
    return formatted, filtered_result


class ExpertPlugin:
    """Expert plugin using PromptGraph + knowledge retrieval.

    Compiles a prompt graph from input definition, injects a 'retrieve'
    special node that queries the knowledge store, and assembles a
    response with source references.
    """

    name = "expert"
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
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        self._answering_temperature = answering_temperature
        self._chain_of_thought_enabled = chain_of_thought_enabled
        # None keeps retrieval exactly as it was: hybrid_retrieval.retrieve
        # reads the flag off this and falls through to the dense path.
        self._hybrid_config = hybrid_config
        # Absent unless re-ranking is enabled, so an existing deployment keeps
        # exactly its current retrieval behaviour with no new code path.
        self._reranker = reranker
        self._rerank_candidate_n = rerank_candidate_n
        self._rerank_top_k = rerank_top_k

    @property
    def _retrieval_n_results(self) -> int:
        """How many candidates to fetch.

        Re-ranking can only reorder what retrieval returned, so it needs a
        wider pool to choose from. Without it, the count is unchanged — which
        is what makes disabling re-ranking a genuine rollback rather than a
        differently-shaped request.
        """
        return self._rerank_candidate_n if self._reranker else self._n_results

    def _maybe_rerank(self, query: str, result: QueryResult) -> QueryResult:
        """Re-order candidates when re-ranking is on; otherwise pass through."""
        if self._reranker is None:
            return result
        return _apply_rerank(self._reranker, query, result)

    def _truncate_to_top_k(
        self, docs: list[str], result: QueryResult,
    ) -> tuple[list[str], QueryResult]:
        """Keep the best K of what survived the threshold.

        Deliberately after `_filter_and_format`, not before. Re-ranking lifts
        term-matching passages that may sit below the relevance threshold; if
        the cut happened first those would fill the whole top-K and then be
        discarded, leaving fewer sources than before re-ranking — possibly
        none. Filtering first, then cutting, means K good passages are kept
        whenever K good passages exist.
        """
        if self._reranker is None:
            return docs, result

        k = self._rerank_top_k
        return docs[:k], QueryResult(
            documents=[(result.documents[0] if result.documents else [])[:k]],
            metadatas=[(result.metadatas[0] if result.metadatas else [])[:k]],
            distances=[(result.distances[0] if result.distances else [])[:k]],
            ids=[(result.ids[0] if result.ids else [])[:k]],
        )


    async def startup(self) -> None:
        logger.info("ExpertPlugin started")

    async def shutdown(self) -> None:
        logger.info("ExpertPlugin stopped")

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
        bok_id = event.body_of_knowledge_id or ""
        collection = f"{bok_id}-knowledge" if bok_id else "default-knowledge"

        # If prompt_graph is defined, use graph execution
        if event.prompt_graph:
            return await self._handle_with_graph(event, collection)

        # Fallback: simple RAG
        return await self._handle_simple(event, collection)

    def _enforce_context_budget(
        self, docs: list[str], filtered_result: QueryResult,
    ) -> tuple[list[str], QueryResult]:
        """Drop lowest-scoring chunks if rendered context exceeds its budget."""
        raw_docs_check = filtered_result.documents[0] if filtered_result.documents else []
        total_budget_size = sum(
            rendered_document_budget_size(rendered, content)
            for rendered, content in zip(docs, raw_docs_check)
        )
        if total_budget_size <= self._max_context_chars:
            return docs, filtered_result

        # docs are already in score order from _filter_and_format
        kept_docs, kept_distances, kept_metadatas, kept_ids = [], [], [], []
        accumulated = 0
        raw_docs = filtered_result.documents[0] if filtered_result.documents else []
        raw_distances = filtered_result.distances[0] if filtered_result.distances else []
        raw_metadatas = filtered_result.metadatas[0] if filtered_result.metadatas else []
        raw_ids = filtered_result.ids[0] if filtered_result.ids else []

        kept_formatted = []
        for i, doc in enumerate(docs):
            raw_content = raw_docs[i] if i < len(raw_docs) else ""
            document_budget_size = rendered_document_budget_size(doc, raw_content)
            if accumulated + document_budget_size > self._max_context_chars:
                break
            kept_formatted.append(doc)
            kept_docs.append(raw_content)
            if i < len(raw_distances):
                kept_distances.append(raw_distances[i])
            if i < len(raw_metadatas):
                kept_metadatas.append(raw_metadatas[i])
            if i < len(raw_ids):
                kept_ids.append(raw_ids[i])
            accumulated += document_budget_size

        dropped = len(docs) - len(kept_formatted)
        dropped_budget = total_budget_size - accumulated
        logger.warning(
            "Context budget exceeded: dropped %d chunks (%d budget units)",
            dropped, dropped_budget,
        )

        new_result = QueryResult(
            documents=[kept_docs],
            metadatas=[kept_metadatas],
            distances=[kept_distances],
            ids=[kept_ids],
        )
        return kept_formatted, new_result

    async def _handle_with_graph(self, event: Input, collection: str) -> Response:
        from core.domain.prompt_graph import PromptGraph

        graph = PromptGraph.from_definition(event.prompt_graph)

        # Create retrieve special node
        n_results = self._retrieval_n_results
        score_threshold = self._score_threshold
        enforce_budget = self._enforce_context_budget
        maybe_rerank = self._maybe_rerank
        truncate_to_top_k = self._truncate_to_top_k

        async def retrieve_node(state: dict) -> dict:
            from opentelemetry.trace import SpanKind
            from core.tracing import mark_empty_retrieval, optional_span

            query = (
                state.get("rephrased_question")
                or state.get("current_question")
                or event.message
            )
            # #114's hybrid retrieval inside #108's span, carrying #107's
            # factual filter through to both arms; #115 re-ranks the pool and
            # truncates AFTER threshold filtering (order is load-bearing —
            # truncating first once turned 5 grounded sources into 0).
            with optional_span("vc.retrieval", kind=SpanKind.CLIENT) as span:
                result = await hybrid_retrieval.retrieve(
                    self._knowledge_store, collection, query,
                    self._hybrid_config, n_results=n_results,
                    where=FACTUAL_WHERE,
                )
                # Re-rank against the question actually asked at this point in
                # the graph — the rephrased one when there is one, since that
                # is what was retrieved on.
                result = maybe_rerank(query, result)
                docs, filtered_result = _filter_and_format(result, score_threshold)
                docs, filtered_result = truncate_to_top_k(docs, filtered_result)
                initial_count = len(docs)
                docs, filtered_result = enforce_budget(docs, filtered_result)
                if span is not None:
                    span.set_attribute("vc.retrieval.chunks_passed", len(docs))
                    span.set_attribute("vc.retrieval.chunks_dropped_budget", initial_count - len(docs))
                if not result.documents or not result.documents[0] or not docs:
                    mark_empty_retrieval()
            # #109: numbered blocks, so the model can cite [Document N].
            knowledge = join_document_blocks(docs)
            # The expert state schema expects ``combined_knowledge_docs``
            # — that's what the answer_question node reads via its
            # ``{combined_knowledge_docs}`` prompt variable.  ``sources``
            # is not in the schema and would be dropped on state merge,
            # so the Response ends up with an empty sources list and the
            # server won't append the "- [title](uri)" block.
            return {"combined_knowledge_docs": knowledge}

        graph.compile(llm=self._llm, special_nodes={"retrieve": retrieve_node})

        # Build messages list and conversation text from event history +
        # the current user message.  The graph's `check_input` node expects
        # a formatted `conversation` string of ``role:\ncontent`` turns.
        history = list(event.history or [])
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

        answer = final_state.get("final_answer", final_state.get("result", ""))
        sources = self._extract_sources(final_state)

        return Response(
            result=answer,
            sources=sources,
            human_language=event.language,
            result_language=final_state.get("result_language"),
            knowledge_language=final_state.get("knowledge_language"),
            original_result=final_state.get("original_result"),
        )

    async def _handle_simple(self, event: Input, collection: str) -> Response:
        """Simple RAG without graph execution."""
        from opentelemetry.trace import SpanKind

        from core.tracing import mark_empty_retrieval, optional_span

        with optional_span("vc.retrieval", kind=SpanKind.CLIENT) as span:
            result = await hybrid_retrieval.retrieve(
                self._knowledge_store, collection, event.message,
                self._hybrid_config, n_results=self._retrieval_n_results,
                where=FACTUAL_WHERE,
            )
            result = self._maybe_rerank(event.message, result)
            docs, result = _filter_and_format(result, self._score_threshold)
            docs, result = self._truncate_to_top_k(docs, result)
            initial_count = len(docs)
            docs, result = self._enforce_context_budget(docs, result)
            if span is not None:
                span.set_attribute("vc.retrieval.chunks_passed", len(docs))
                span.set_attribute("vc.retrieval.chunks_dropped_budget", initial_count - len(docs))
            if not result.documents or not result.documents[0] or not docs:
                mark_empty_retrieval()
        knowledge = join_document_blocks(docs)

        from plugins.expert.prompts import combined_expert_prompt
        prompt = combined_expert_prompt.format(
            vc_name=event.display_name or "Expert",
            knowledge=knowledge,
            question=event.message,
            empty_context_instruction=empty_context_instruction(bool(docs)),
            citation_scope_instruction=citation_scope_instruction(len(docs)),
        )
        complexity_instruction = self._complexity_instruction(event.message)
        if complexity_instruction:
            prompt = f"{prompt}\n\n{complexity_instruction}"

        answer = await self._invoke_answering(prompt)
        sources = self._build_sources(result)

        return Response(
            result=answer,
            sources=sources,
            human_language=event.language,
        )

    @staticmethod
    def _extract_sources(state: dict) -> list[Source]:
        """Extract sources from graph final state."""
        query_result = state.get("sources")
        if query_result is None:
            return []
        return ExpertPlugin._build_sources(query_result)

    @staticmethod
    def _build_sources(query_result) -> list[Source]:
        """Build Source list from a QueryResult, deduplicated by source URL."""
        if not query_result.metadatas:
            return []
        seen: dict[str, Source] = {}
        for i, meta in enumerate(query_result.metadatas[0]):
            distance = query_result.distances[0][i] if query_result.distances else None
            source_key = meta.get("source", "")
            if source_key in seen:
                continue
            src = Source(
                chunk_index=meta.get("chunkIndex", meta.get("chunk_index", i)),
                embedding_type=meta.get("embeddingType", meta.get("embedding_type")),
                document_id=meta.get("documentId", meta.get("document_id")),
                source=source_key,
                title=meta.get("title"),
                type=meta.get("type"),
                score=1.0 - distance if distance is not None else None,
                uri=meta.get("uri") or source_key,
            )
            seen[source_key] = src
        return list(seen.values())
