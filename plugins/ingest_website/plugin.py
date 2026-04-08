"""IngestWebsitePlugin — crawl, extract, ingest website content."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

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
from core.events.ingest_website import IngestWebsite, IngestWebsiteResult, IngestionResult
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
        bok_llm: LLMPort | None = None,
        chunk_threshold: int = 4,
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
        self._summarize_llm = summarize_llm
        self._bok_llm = bok_llm
        self._chunk_threshold = chunk_threshold
        self._page_limit = 20  # Default, can be overridden by config

    async def startup(self) -> None:
        logger.info("IngestWebsitePlugin started")

    async def shutdown(self) -> None:
        logger.info("IngestWebsitePlugin stopped")

    async def handle(self, event: IngestWebsite, **ports) -> IngestWebsiteResult:
        try:
            # Determine collection name: {netloc}-knowledge
            netloc = urlparse(event.base_url).netloc.replace(":", "-")
            collection_name = f"{netloc}-knowledge"

            # Crawl
            pages = await crawl(event.base_url, page_limit=self._page_limit)

            # Convert to Documents
            documents = []
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
                documents.append(doc)

            if not documents:
                # Crawl succeeded but produced zero documents — run cleanup
                # so previously-stored chunks are identified as removed and deleted.
                logger.info(
                    "Source returned zero documents for collection %s; running cleanup pipeline",
                    collection_name,
                )
                cleanup_engine = IngestEngine(steps=[
                    ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
                    OrphanCleanupStep(knowledge_store_port=self._knowledge_store),
                ])
                cleanup_result = await cleanup_engine.run([], collection_name)

                return IngestWebsiteResult(
                    result=IngestionResult.SUCCESS if cleanup_result.success else IngestionResult.FAILURE,
                    error="; ".join(cleanup_result.errors) if cleanup_result.errors else "",
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
                steps.append(DocumentSummaryStep(
                    llm_port=summary_llm,
                    concurrency=config.summarize_concurrency,
                    chunk_threshold=self._chunk_threshold,
                ))
                bok_llm = self._bok_llm or summary_llm
                steps.append(BodyOfKnowledgeSummaryStep(llm_port=bok_llm))
            steps.append(EmbedStep(embeddings_port=self._embeddings))
            steps.append(StoreStep(knowledge_store_port=self._knowledge_store))
            steps.append(OrphanCleanupStep(knowledge_store_port=self._knowledge_store))
            engine = IngestEngine(steps=steps)
            result = await engine.run(documents, collection_name)

            return IngestWebsiteResult(
                result=IngestionResult.SUCCESS if result.success else IngestionResult.FAILURE,
                error="; ".join(result.errors) if result.errors else "",
            )

        except Exception as exc:
            logger.exception("Website ingestion failed: %s", exc)
            return IngestWebsiteResult(
                result=IngestionResult.FAILURE,
                error=str(exc),
            )
