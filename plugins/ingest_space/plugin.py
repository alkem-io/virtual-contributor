"""IngestSpacePlugin — fetch Alkemio space tree and ingest into knowledge store."""

from __future__ import annotations

import logging
from typing import Any

from core.domain.pipeline import (
    BodyOfKnowledgeSummaryStep,
    ChangeDetectionStep,
    ChunkStep,
    ContentHashStep,
    DocumentSummaryStep,
    EmbedStep,
    IngestEngine,
    OrphanCleanupStep,
    StoreStep,
)
from core.events.ingest_space import (
    ErrorDetail,
    IngestBodyOfKnowledge,
    IngestBodyOfKnowledgeResult,
)
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort

logger = logging.getLogger(__name__)


class IngestSpacePlugin:
    """Fetches space tree via GraphQL and ingests into knowledge store."""

    name = "ingest-space"
    event_type = IngestBodyOfKnowledge

    def __init__(
        self,
        llm: LLMPort,
        embeddings: EmbeddingsPort,
        knowledge_store: KnowledgeStorePort,
        graphql_client: Any = None,
        *,
        summarize_llm: LLMPort | None = None,
        bok_llm: LLMPort | None = None,
        chunk_threshold: int = 4,
        summarize_enabled: bool = True,
        summarize_concurrency: int = 8,
        ingest_batch_size: int = 5,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
        self._graphql_client = graphql_client
        self._summarize_llm = summarize_llm
        self._bok_llm = bok_llm
        self._chunk_threshold = chunk_threshold
        self._summarize_enabled = summarize_enabled
        self._summarize_concurrency = max(1, summarize_concurrency)
        self._ingest_batch_size = max(1, ingest_batch_size)

    async def startup(self) -> None:
        logger.info("IngestSpacePlugin started")

    async def shutdown(self) -> None:
        logger.info("IngestSpacePlugin stopped")

    async def handle(self, event: IngestBodyOfKnowledge, **ports) -> IngestBodyOfKnowledgeResult:
        try:
            bok_id = event.body_of_knowledge_id
            collection_name = f"{bok_id}-{event.purpose}"

            # Fetch space tree BEFORE deleting the old collection
            if self._graphql_client is None:
                raise RuntimeError("GraphQL client not configured")

            from plugins.ingest_space.space_reader import read_space_tree
            documents = await read_space_tree(self._graphql_client, bok_id)

            if not documents:
                # Fetch succeeded but returned zero documents — run cleanup
                # pipeline to remove any previously stored chunks.
                logger.info(
                    "Space %s returned zero documents; running cleanup pipeline for collection %s",
                    bok_id,
                    collection_name,
                )
                cleanup_engine = IngestEngine(steps=[
                    ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
                    OrphanCleanupStep(knowledge_store_port=self._knowledge_store),
                ])
                cleanup_result = await cleanup_engine.run([], collection_name)
                return IngestBodyOfKnowledgeResult(
                    body_of_knowledge_id=bok_id,
                    type=event.type,
                    purpose=event.purpose,
                    persona_id=event.persona_id,
                    result="success" if cleanup_result.success else "failure",
                    error=ErrorDetail(message="; ".join(cleanup_result.errors)) if cleanup_result.errors else None,
                )

            # Run ingest pipeline in batched mode
            summary_llm = self._summarize_llm or self._llm
            batch_steps: list = [
                ChunkStep(chunk_size=9000, chunk_overlap=500),
                ContentHashStep(),
                ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
            ]
            if self._summarize_enabled:
                batch_steps.append(DocumentSummaryStep(
                    llm_port=summary_llm,
                    reduce_llm_port=self._bok_llm or summary_llm,
                    concurrency=self._summarize_concurrency,
                    chunk_threshold=self._chunk_threshold,
                    embeddings_port=self._embeddings,
                ))
            batch_steps.extend([
                EmbedStep(embeddings_port=self._embeddings),
                StoreStep(knowledge_store_port=self._knowledge_store),
            ])

            finalize_steps: list = []
            if self._summarize_enabled:
                finalize_steps.append(BodyOfKnowledgeSummaryStep(
                    llm_port=self._bok_llm or summary_llm,
                    map_llm_port=summary_llm,
                    knowledge_store_port=self._knowledge_store,
                    embeddings_port=self._embeddings,
                ))
                finalize_steps.append(EmbedStep(embeddings_port=self._embeddings))
                finalize_steps.append(StoreStep(knowledge_store_port=self._knowledge_store))
            finalize_steps.append(OrphanCleanupStep(knowledge_store_port=self._knowledge_store))

            engine = IngestEngine(
                batch_steps=batch_steps,
                finalize_steps=finalize_steps,
                batch_size=self._ingest_batch_size,
            )
            result = await engine.run(documents, collection_name)

            return IngestBodyOfKnowledgeResult(
                body_of_knowledge_id=bok_id,
                type=event.type,
                purpose=event.purpose,
                persona_id=event.persona_id,
                result="success" if result.success else "failure",
                error=ErrorDetail(message="; ".join(result.errors)) if result.errors else None,
            )

        except Exception as exc:
            logger.exception("Space ingestion failed: %s", exc)
            return IngestBodyOfKnowledgeResult(
                body_of_knowledge_id=event.body_of_knowledge_id,
                type=event.type,
                purpose=event.purpose,
                persona_id=event.persona_id,
                result="failure",
                error=ErrorDetail(message=str(exc)),
            )
