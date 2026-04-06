"""ExpertPlugin — PromptGraph-based expert with knowledge retrieval."""

from __future__ import annotations

import logging

from core.events.input import Input
from core.events.response import Response, Source
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort, QueryResult

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
    ) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store
        self._n_results = n_results
        self._score_threshold = score_threshold

    async def startup(self) -> None:
        logger.info("ExpertPlugin started")

    async def shutdown(self) -> None:
        logger.info("ExpertPlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        bok_id = event.body_of_knowledge_id or ""
        collection = f"{bok_id}-knowledge" if bok_id else "default-knowledge"

        # If prompt_graph is defined, use graph execution
        if event.prompt_graph:
            return await self._handle_with_graph(event, collection)

        # Fallback: simple RAG
        return await self._handle_simple(event, collection)

    async def _handle_with_graph(self, event: Input, collection: str) -> Response:
        from core.domain.prompt_graph import PromptGraph

        graph = PromptGraph.from_definition(event.prompt_graph)

        # Create retrieve special node
        n_results = self._n_results
        score_threshold = self._score_threshold

        async def retrieve_node(state: dict) -> dict:
            query = state.get("current_question", event.message)
            result = await self._knowledge_store.query(
                collection=collection, query_texts=[query], n_results=n_results,
            )
            docs, filtered_result = _filter_and_format(result, score_threshold)
            knowledge = "\n".join(docs)
            return {"knowledge": knowledge, "sources": filtered_result}

        graph.compile(llm=self._llm, special_nodes={"retrieve": retrieve_node})

        initial_state = {
            "messages": [],
            "current_question": event.message,
            "conversation": "",
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
        result = await self._knowledge_store.query(
            collection=collection, query_texts=[event.message], n_results=self._n_results,
        )
        docs, result = _filter_and_format(result, self._score_threshold)
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
