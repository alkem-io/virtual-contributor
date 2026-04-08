"""IngestWebsitePlugin — crawl, extract, ingest website content."""

from __future__ import annotations

import json
import logging

from core.domain.ingest_pipeline import Document, DocumentMetadata
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
from core.events.ingest_website import (
    IngestionMode,
    IngestionResult,
    IngestWebsite,
    IngestWebsiteResult,
    SourceResult,
    WebsiteSource,
)
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from plugins.ingest_website.crawler import crawl
from plugins.ingest_website.html_parser import extract_text, extract_title

logger = logging.getLogger(__name__)


class IngestWebsitePlugin:
    """Crawls a website and ingests content into the knowledge store."""

    name = "ingest-website"
    event_type = IngestWebsite

    def __init__(
        self,
        llm: LLMPort,
        embeddings: EmbeddingsPort,
        knowledge_store: KnowledgeStorePort,
        *,
        summarize_llm: LLMPort | None = None,
        chunk_threshold: int = 4,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
        self._summarize_llm = summarize_llm
        self._chunk_threshold = chunk_threshold
        self._default_page_limit = 20  # Overridden by config in startup

    async def startup(self) -> None:
        from core.config import IngestWebsiteConfig

        try:
            config = IngestWebsiteConfig()
            self._default_page_limit = config.process_pages_limit
        except Exception:
            pass  # Keep default if config loading fails
        logger.info("IngestWebsitePlugin started")

    async def shutdown(self) -> None:
        logger.info("IngestWebsitePlugin stopped")

    async def handle(self, event: IngestWebsite, **ports: object) -> IngestWebsiteResult:
        try:
            # Collection name based on personaId
            collection_name = f"{event.persona_id}-knowledge"

            # Handle FULL mode: delete collection before processing
            if event.mode == IngestionMode.FULL:
                logger.info("FULL mode: deleting collection %s", collection_name)
                await self._knowledge_store.delete_collection(collection_name)

            # Crawl all sources sequentially
            all_documents: list[Document] = []
            source_results: list[SourceResult] = []

            for source in event.sources:
                source_result = await self._crawl_source(source, all_documents)
                source_results.append(source_result)

            if not all_documents:
                return IngestWebsiteResult(
                    result=IngestionResult.SUCCESS,
                    error="No content extracted from any source",
                    source_results=source_results,
                )

            # Store source config as sentinel chunk
            await self._store_source_config(
                collection_name, event.sources
            )

            # Run ingest pipeline
            from core.config import BaseConfig

            config = BaseConfig()
            summary_llm = self._summarize_llm or self._llm
            steps: list = [
                ChunkStep(chunk_size=2000),
                ContentHashStep(),
                ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
            ]
            if config.summarize_concurrency > 0:
                steps.append(
                    DocumentSummaryStep(
                        llm_port=summary_llm,
                        concurrency=config.summarize_concurrency,
                        chunk_threshold=self._chunk_threshold,
                    )
                )
                steps.append(BodyOfKnowledgeSummaryStep(llm_port=summary_llm))
            steps.append(EmbedStep(embeddings_port=self._embeddings))
            steps.append(StoreStep(knowledge_store_port=self._knowledge_store))
            steps.append(OrphanCleanupStep(knowledge_store_port=self._knowledge_store))
            engine = IngestEngine(steps=steps)
            result = await engine.run(all_documents, collection_name)

            # Determine overall result
            has_source_errors = any(sr.error for sr in source_results)
            overall_success = result.success and not has_source_errors

            return IngestWebsiteResult(
                result=(
                    IngestionResult.SUCCESS
                    if overall_success
                    else IngestionResult.FAILURE
                ),
                error="; ".join(result.errors) if result.errors else "",
                source_results=source_results,
            )

        except Exception as exc:
            logger.exception("Website ingestion failed: %s", exc)
            return IngestWebsiteResult(
                result=IngestionResult.FAILURE,
                error=str(exc),
            )

    async def _crawl_source(
        self,
        source: WebsiteSource,
        all_documents: list[Document],
    ) -> SourceResult:
        """Crawl a single source and append documents to the aggregate list."""
        page_limit = (
            source.page_limit
            if source.page_limit is not None
            else self._default_page_limit
        )

        try:
            pages = await crawl(
                source.url,
                page_limit=page_limit,
                max_depth=source.max_depth,
                include_patterns=source.include_patterns,
                exclude_patterns=source.exclude_patterns,
            )

            pages_processed = 0
            for page in pages:
                text = extract_text(page["html"])
                if not text.strip():
                    continue
                title = extract_title(page["html"])
                doc = Document(
                    content=text,
                    metadata=DocumentMetadata(
                        document_id=page["url"],
                        source=page["url"],
                        type="knowledge",
                        title=title,
                    ),
                )
                all_documents.append(doc)
                pages_processed += 1

            return SourceResult(url=source.url, pages_processed=pages_processed)

        except Exception as exc:
            logger.warning("Failed to crawl source %s: %s", source.url, exc)
            return SourceResult(url=source.url, error=str(exc))

    async def _store_source_config(
        self,
        collection_name: str,
        sources: list[WebsiteSource],
    ) -> None:
        """Store source configuration as a sentinel chunk for refresh support."""
        config_data = json.dumps(
            [s.model_dump() for s in sources], indent=2
        )
        try:
            await self._knowledge_store.ingest(
                collection=collection_name,
                documents=[config_data],
                metadatas=[
                    {
                        "documentId": "__source_config__",
                        "source": "internal",
                        "type": "config",
                        "title": "Source Configuration",
                        "embeddingType": "config",
                        "chunkIndex": 0,
                    }
                ],
                ids=["__source_config__"],
            )
        except Exception as exc:
            logger.warning("Failed to store source config: %s", exc)
