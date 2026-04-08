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
        chunk_threshold: int = 4,
        summarize_enabled: bool = True,
        summarize_concurrency: int = 8,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
        self._graphql_client = graphql_client
        self._summarize_llm = summarize_llm
        self._chunk_threshold = chunk_threshold
        self._summarize_enabled = summarize_enabled
        self._summarize_concurrency = summarize_concurrency

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
                return IngestBodyOfKnowledgeResult(
                    body_of_knowledge_id=bok_id,
                    type=event.type,
                    purpose=event.purpose,
                    persona_id=event.persona_id,
                    result="success",
                )

            # Run ingest pipeline with ingest-space specific settings
            summary_llm = self._summarize_llm or self._llm
            steps: list = [
                ChunkStep(chunk_size=9000, chunk_overlap=500),
                ContentHashStep(),
                ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
            ]
            if self._summarize_enabled:
                steps.append(DocumentSummaryStep(
                    llm_port=summary_llm,
                    concurrency=max(1, self._summarize_concurrency),
                    chunk_threshold=self._chunk_threshold,
                ))
                steps.append(BodyOfKnowledgeSummaryStep(llm_port=summary_llm))
            steps.append(EmbedStep(embeddings_port=self._embeddings))
            steps.append(StoreStep(knowledge_store_port=self._knowledge_store))
            steps.append(OrphanCleanupStep(knowledge_store_port=self._knowledge_store))
            engine = IngestEngine(steps=steps)
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
