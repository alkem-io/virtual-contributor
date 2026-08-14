"""ExpertPlugin — PromptGraph-based expert with knowledge retrieval."""

from __future__ import annotations

import logging

from core.events.input import Input
from core.events.response import Response, Source
from core.domain.routing import DEFAULT_ROUTING_TABLE, RetrievalProfile
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.ports.query_router import QueryRouterPort, RouteClass, RoutingDecision

logger = logging.getLogger(__name__)


def _filter_and_format(
    result: QueryResult, score_threshold: float
) -> tuple[list[str], QueryResult]:
    """Filter results by score threshold and prefix with [source:N].

    Returns the formatted doc list and a new QueryResult containing only
    the entries that passed the threshold.
    """
    docs = result.documents[0] if result.documents else []
    distances = result.distances[0] if result.distances else []
    metadatas = result.metadatas[0] if result.metadatas else []
    ids = result.ids[0] if result.ids else []

    kept_docs, kept_distances, kept_metadatas, kept_ids = [], [], [], []
    for i, doc in enumerate(docs):
        score = 1.0 - distances[i] if i < len(distances) else 0.0
        if score >= score_threshold:
            kept_docs.append(doc)
            kept_distances.append(distances[i] if i < len(distances) else 1.0)
            kept_metadatas.append(metadatas[i] if i < len(metadatas) else {})
            kept_ids.append(ids[i] if i < len(ids) else "")

    formatted = [f"[source:{i}] {doc}" for i, doc in enumerate(kept_docs)]
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
        query_router: QueryRouterPort | None = None,
        routing_table: dict | None = None,
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold
        self._max_context_chars = max_context_chars
        # Absent unless routing is enabled, so an existing deployment takes its
        # current code path with its current constants — the disabled path is
        # literally today's branch, not a table that happens to agree with it.
        self._query_router = query_router
        self._routing_table = routing_table or DEFAULT_ROUTING_TABLE

    def _resolve_profile(self, message: str) -> RetrievalProfile:
        """Decide this query's retrieval settings.

        Classification is an optimisation, never a dependency of answering: if
        it fails for any reason the query is served with the configured
        defaults, which is exactly what happens with routing switched off.
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

    async def startup(self) -> None:
        logger.info("ExpertPlugin started")

    async def shutdown(self) -> None:
        logger.info("ExpertPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        bok_id = event.body_of_knowledge_id or ""
        collection = f"{bok_id}-knowledge" if bok_id else "default-knowledge"

        # One decision per query, made before either path branches, so the
        # two paths cannot drift apart in how they route.
        profile = self._resolve_profile(event.message)

        # If prompt_graph is defined, use graph execution
        if event.prompt_graph:
            return await self._handle_with_graph(event, collection, profile)

        # Fallback: simple RAG
        return await self._handle_simple(event, collection, profile)

    def _enforce_context_budget(
        self, docs: list[str], filtered_result: QueryResult,
        max_context_chars: int | None = None,
    ) -> tuple[list[str], QueryResult]:
        """Drop lowest-scoring chunks if total chars exceed the budget.

        The budget is per-query, not per-instance: a route that widens
        retrieval must widen this too, or the extra chunks are fetched and
        then silently discarded here.
        """
        budget = (
            self._max_context_chars if max_context_chars is None
            else max_context_chars
        )
        raw_docs_check = filtered_result.documents[0] if filtered_result.documents else []
        total_raw_chars = sum(len(d) for d in raw_docs_check)
        if total_raw_chars <= budget:
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
            if accumulated + len(raw_content) > budget:
                break
            kept_formatted.append(doc)
            kept_docs.append(raw_content)
            if i < len(raw_distances):
                kept_distances.append(raw_distances[i])
            if i < len(raw_metadatas):
                kept_metadatas.append(raw_metadatas[i])
            if i < len(raw_ids):
                kept_ids.append(raw_ids[i])
            accumulated += len(raw_content)

        dropped = len(docs) - len(kept_formatted)
        dropped_chars = total_raw_chars - accumulated
        logger.warning(
            "Context budget exceeded: dropped %d chunks (%d chars)",
            dropped, dropped_chars,
        )

        new_result = QueryResult(
            documents=[kept_docs],
            metadatas=[kept_metadatas],
            distances=[kept_distances],
            ids=[kept_ids],
        )
        return kept_formatted, new_result

    async def _handle_with_graph(
        self, event: Input, collection: str, profile: RetrievalProfile,
    ) -> Response:
        from core.domain.prompt_graph import PromptGraph

        graph = PromptGraph.from_definition(event.prompt_graph)

        # Create retrieve special node
        # Read from the profile, not from self: the closure below captures
        # these, and capturing instance constants is how one path silently
        # keeps today's behaviour while the other routes.
        n_results = profile.n_results
        score_threshold = profile.score_threshold
        budget_chars = profile.max_context_chars
        should_retrieve = profile.retrieve
        enforce_budget = self._enforce_context_budget

        async def retrieve_node(state: dict) -> dict:
            query = (
                state.get("rephrased_question")
                or state.get("current_question")
                or event.message
            )
            if not should_retrieve:
                # Small talk. There is nothing in a knowledge base that answers
                # "thanks" — so no query is made at all, not a query whose
                # results are discarded.
                return {"combined_knowledge_docs": ""}
            result = await self._knowledge_store.query(
                collection=collection, query_texts=[query], n_results=n_results,
            )
            docs, filtered_result = _filter_and_format(result, score_threshold)
            docs, filtered_result = enforce_budget(docs, filtered_result, budget_chars)
            knowledge = "\n".join(docs)
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

    async def _handle_simple(
        self, event: Input, collection: str, profile: RetrievalProfile,
    ) -> Response:
        """Simple RAG without graph execution."""
        if profile.retrieve:
            result = await self._knowledge_store.query(
                collection=collection,
                query_texts=[event.message],
                n_results=profile.n_results,
            )
            docs, result = _filter_and_format(result, profile.score_threshold)
            docs, result = self._enforce_context_budget(
                docs, result, profile.max_context_chars,
            )
        else:
            docs = []
            result = QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
        knowledge = "\n".join(docs)

        from plugins.expert.prompts import combined_expert_prompt
        prompt = combined_expert_prompt.format(
            vc_name=event.display_name or "Expert",
            knowledge=knowledge,
            question=event.message,
        )

        answer = await self._llm.invoke([{"role": "human", "content": prompt}])
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
