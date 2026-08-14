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
from core.domain.hierarchy_retrieval import (
    ORIENTING_WHERE,
    scoped_detail_where,
    select_branches,
)
from core.ports.llm import LLMPort
from core.domain.faithfulness import safe_reason as _safe_reason
from core.ports.faithfulness import FaithfulnessValidatorPort
from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.ports.reranker import RerankerPort
from core.domain.routing import DEFAULT_ROUTING_TABLE, RetrievalProfile
from core.ports.query_router import QueryRouterPort, RouteClass, RoutingDecision
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
    result: QueryResult, score_threshold: float, *, hierarchy: bool = False,
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
        render_document_block(
            number, doc, kept_metadatas[number - 1], hierarchy=hierarchy,
        )
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
        query_router: QueryRouterPort | None = None,
        routing_table: dict | None = None,
        faithfulness_validator: FaithfulnessValidatorPort | None = None,
        rewrite_policy: RewritePolicy | None = None,
        max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
        max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS,
        max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
        hierarchical_retrieval_enabled: bool = False,
        hierarchy_max_branches: int = 3,
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
        # Absent unless routing is enabled, so an existing deployment takes its
        # current code path with its current constants — the disabled path is
        # literally today's branch, not a table that happens to agree with it.
        self._query_router = query_router
        self._routing_table = routing_table or DEFAULT_ROUTING_TABLE
        # Absent unless validation is enabled. Its absence is the off switch.
        self._faithfulness_validator = faithfulness_validator
        # None means "never skip" — see GuidancePlugin.
        self._rewrite_policy = rewrite_policy
        self._max_expansion_ratio = max_expansion_ratio
        self._max_history_turns = max_history_turns
        self._max_history_chars = max_history_chars
        self._hierarchical_retrieval_enabled = hierarchical_retrieval_enabled
        self._hierarchy_max_branches = hierarchy_max_branches

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

    def _validate_faithfulness(self, *, answer: str, context: str) -> None:
        """Observe whether the answer was supportable. Never changes it.

        Keyed off the CONTEXT STRING, never ``Response.sources``: the graph
        path returns no sources by design, so a sources-keyed check would flag
        every graph answer.

        Wrapped defensively because this is pure observation — a fault in a
        diagnostic must never cost a member their answer.
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
                # record goes to stdout and on to central logging — where it is
                # readable by anyone with log access rather than by space
                # membership. Never widen this to include verdict.detail.
                logger.warning(
                    "Unsupported answer: plugin=expert reason=%s answer_chars=%d",
                    _safe_reason(verdict.reason), len(answer),
                )
        except Exception as exc:
            # The exception TYPE, not the traceback: a substituted validator
            # raising ValueError(f"could not judge: {answer}") would otherwise
            # export the answer through the failure path.
            logger.warning(
                "Faithfulness validation failed: error_type=%s",
                type(exc).__name__,
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
        """Drop lowest-scoring chunks if rendered context exceeds its budget.

        The budget is per-query, not per-instance (#116): a route that widens
        retrieval must widen this too, or the extra chunks are fetched and
        then silently discarded here. Accounting is rendered-block based
        (#109): what is measured is what the model actually receives.
        """
        budget = (
            self._max_context_chars if max_context_chars is None
            else max_context_chars
        )
        raw_docs_check = filtered_result.documents[0] if filtered_result.documents else []
        total_budget_size = sum(
            rendered_document_budget_size(rendered, content)
            for rendered, content in zip(docs, raw_docs_check)
        )
        if total_budget_size <= budget:
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
            if accumulated + document_budget_size > budget:
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

    async def _retrieve_pipeline(
        self,
        collection: str,
        query: str,
        profile: RetrievalProfile,
        *,
        where: dict | None,
        hierarchy: bool,
    ) -> tuple[list[str], QueryResult, int]:
        """Run the unchanged composed retrieval pipeline for one predicate."""

        pool_n = (
            max(profile.n_results, self._rerank_candidate_n)
            if self._reranker is not None
            else profile.n_results
        )
        result = await hybrid_retrieval.retrieve(
            self._knowledge_store, collection, query, self._hybrid_config,
            n_results=pool_n, where=where,
        )
        result = self._maybe_rerank(query, result)
        docs, result = _filter_and_format(
            result, profile.score_threshold, hierarchy=hierarchy,
        )
        docs, result = self._truncate_to_top_k(docs, result)
        initial_count = len(docs)
        docs, result = self._enforce_context_budget(
            docs, result, profile.max_context_chars,
        )
        return docs, result, initial_count

    async def _retrieve_context(
        self,
        collection: str,
        query: str,
        profile: RetrievalProfile,
    ) -> tuple[list[str], QueryResult, int]:
        """Use the hierarchy enhancement when it is usable, otherwise flat.

        The compatibility path is deliberately invoked fresh after an unusable
        hierarchy stage.  It is not wrapped: if the current flat retrieval
        fails, that error remains the request's visible behaviour.
        """

        async def flat() -> tuple[list[str], QueryResult, int]:
            return await self._retrieve_pipeline(
                collection, query, profile, where=FACTUAL_WHERE, hierarchy=False,
            )

        if not self._hierarchical_retrieval_enabled:
            return await flat()

        try:
            routing_result = await self._knowledge_store.query(
                collection=collection,
                query_texts=[query],
                n_results=self._hierarchy_max_branches * 4,
                where=ORIENTING_WHERE,
            )
            branches = select_branches(
                routing_result,
                score_threshold=profile.score_threshold,
                max_branches=self._hierarchy_max_branches,
            )
            predicate = scoped_detail_where(branches)
            if predicate is None:
                return await flat()
            docs, result, initial_count = await self._retrieve_pipeline(
                collection, query, profile, where=predicate, hierarchy=True,
            )
            # A short but non-empty selected branch is an intended precision
            # result.  Only absence of usable detail re-enters flat retrieval.
            if docs:
                return docs, result, initial_count
            return await flat()
        except Exception as exc:
            # Metadata, query text, and passage content are member data.  The
            # stage and exception type explain the operational state safely.
            logger.warning(
                "Hierarchy retrieval fallback: error_type=%s", type(exc).__name__,
            )
            return await flat()

    async def _handle_with_graph(
        self, event: Input, collection: str, profile: RetrievalProfile,
    ) -> Response:
        from core.domain.prompt_graph import PromptGraph

        graph = PromptGraph.from_definition(event.prompt_graph)

        # Resolved before the graph runs so `retrieve_node` can close over it.
        resolved = await self._resolve_question(event)

        # Create retrieve special node
        # NOT captured from the profile resolved in handle(). The graph may
        # rephrase before retrieving — "yes" after "Shall I list the
        # templates?" becomes a real standalone question — so the closure
        # re-resolves on the query it is actually about to run. Capturing the
        # raw turn's decision would skip retrieval on a genuine question and
        # answer it ungrounded, which is the one mistake this feature is not
        # allowed to make.
        resolve_profile = self._resolve_profile
        retrieve_context = self._retrieve_context

        # What retrieval actually produced, captured where it happens rather
        # than read back from the final state. The graph definition arrives on
        # the event, so its state schema is caller-supplied: LangGraph drops
        # any key the schema does not declare, and a RAG graph omitting
        # ``combined_knowledge_docs`` would make a real zero-context answer
        # indistinguishable from a graph that never retrieved. This closure
        # knows the difference; the final state does not.
        retrieved: dict[str, str] = {}

        async def retrieve_node(state: dict) -> dict:
            from opentelemetry.trace import SpanKind
            from core.tracing import mark_empty_retrieval, optional_span

            # `resolved` sits between the graph's own rephrase and the raw
            # question, because it survives a caller schema that drops the key.
            # A graph node writing its own `rephrased_question` still wins.
            #
            # An *empty* `rephrased_question` falls through to `resolved`. That
            # is deliberate: a field the schema declares but no node writes
            # reads as "" too, and that — not a deliberate suppression — is the
            # common case. The two are indistinguishable through `state.get`,
            # and there was no rewriting on develop for a graph to suppress, so
            # treating "" as "nothing was written" is the reading that matches
            # every graph that exists today.
            query = (
                state.get("rephrased_question")
                or resolved
                or state.get("current_question")
                or event.message
            )
            # #116: classify what is being retrieved on, not what was typed.
            node_profile = resolve_profile(query)
            if not node_profile.retrieve:
                # Small talk. There is nothing in a knowledge base that answers
                # "thanks" — so no query is made at all, not a query whose
                # results are discarded.
                return {"combined_knowledge_docs": ""}
            # The same helper powers simple and graph execution, preserving
            # hybrid fusion, re-rank, threshold, top-K and budget ordering.
            with optional_span("vc.retrieval", kind=SpanKind.CLIENT) as span:
                docs, filtered_result, initial_count = await retrieve_context(
                    collection, query, node_profile,
                )
                if span is not None:
                    span.set_attribute("vc.retrieval.chunks_passed", len(docs))
                    span.set_attribute("vc.retrieval.chunks_dropped_budget", initial_count - len(docs))
                if not filtered_result.documents or not filtered_result.documents[0] or not docs:
                    mark_empty_retrieval()
            # #109: numbered blocks, so the model can cite [Document N].
            knowledge = join_document_blocks(docs)
            # #117: captured where retrieval happens — the graph's state
            # schema is caller-supplied and drops undeclared keys, so the
            # closure, not the state, carries what was actually retrieved.
            retrieved["context"] = knowledge
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
        # Bounded for the same reason the rewrite prompt is: the member
        # supplies the history, and every turn here is embedded in
        # `conversation` and `messages`, both of which go straight to the
        # graph's LLM nodes. Measured unbounded: 5 000 turns built a 2.5 MB
        # conversation string — larger than the rewrite prompt this feature
        # already bounded, so bounding only that one was incoherent.
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
        # `retrieve_node` already prefers `rephrased_question` — nothing ever
        # wrote it. Seeding it activates a dormant seam rather than adding one,
        # and only when it differs, so a graph whose own node writes that key is
        # not pre-empted.
        #
        # But the state alone cannot carry it: the graph definition arrives on
        # the event, so its schema is the *caller's*, and LangGraph drops any
        # key the schema does not declare. A graph omitting
        # `rephrased_question` would pay for the rewrite and silently discard
        # it — worse than not rewriting at all. The closure below is the
        # authority; the state seeding is for graphs that route it themselves.
        if resolved != event.message:
            initial_state["rephrased_question"] = resolved

        final_state = await graph.invoke(initial_state)

        answer = final_state.get("final_answer", final_state.get("result", ""))
        # Validate only when retrieval actually ran. A graph with no retrieve
        # node makes no claim about retrieved context — validating it would
        # flag every answer from every non-RAG graph, and prompt graphs are
        # configurable per space.
        if "context" in retrieved:
            self._validate_faithfulness(answer=answer, context=retrieved["context"])
        sources = self._extract_sources(final_state)

        return Response(
            result=answer,
            sources=sources,
            human_language=event.language,
            result_language=final_state.get("result_language"),
            knowledge_language=final_state.get("knowledge_language"),
            original_result=final_state.get("original_result"),
        )

    async def _resolve_question(self, event: Input) -> str:
        """Resolve a follow-up against its history before retrieval.

        Expert is the one plugin that genuinely matched the story's premise:
        it sent the raw message to the vector store, so "and the other one?"
        was searched for literally. Guidance's condense prompt is reused rather
        than a new one invented — its wording is plugin-neutral.
        """
        if not should_rewrite(event.message, event.history, self._rewrite_policy):
            return event.message
        from plugins.guidance.prompts import condense_prompt

        history_text = "\n".join(
            f"{h.role}: {h.content}" for h in recent_history(event.history, self._max_history_turns, self._max_history_chars)
        )
        return await rewrite_query(
            self._llm,
            [{
                "role": "human",
                "content": condense_prompt.format(
                    chat_history=history_text, question=event.message
                ),
            }],
            event.message,
            max_expansion_ratio=self._max_expansion_ratio,
        )

    async def _handle_simple(
        self, event: Input, collection: str, profile: RetrievalProfile,
    ) -> Response:
        """Simple RAG without graph execution."""
        from opentelemetry.trace import SpanKind

        from core.tracing import mark_empty_retrieval, optional_span

        question = await self._resolve_question(event)
        if profile.retrieve:
            with optional_span("vc.retrieval", kind=SpanKind.CLIENT) as span:
                docs, result, initial_count = await self._retrieve_context(
                    collection, question, profile,
                )
                if span is not None:
                    span.set_attribute("vc.retrieval.chunks_passed", len(docs))
                    span.set_attribute("vc.retrieval.chunks_dropped_budget", initial_count - len(docs))
                if not result.documents or not result.documents[0] or not docs:
                    mark_empty_retrieval()
        else:
            docs = []
            result = QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
        knowledge = join_document_blocks(docs)

        from plugins.expert.prompts import combined_expert_prompt
        prompt = combined_expert_prompt.format(
            vc_name=event.display_name or "Expert",
            knowledge=knowledge,
            question=question,
            empty_context_instruction=empty_context_instruction(bool(docs)),
            citation_scope_instruction=citation_scope_instruction(len(docs)),
        )
        complexity_instruction = self._complexity_instruction(event.message)
        if complexity_instruction:
            prompt = f"{prompt}\n\n{complexity_instruction}"

        answer = await self._invoke_answering(prompt)
        self._validate_faithfulness(answer=answer, context=knowledge)
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
