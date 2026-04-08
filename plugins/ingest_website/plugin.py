"""IngestWebsitePlugin -- crawl, extract, ingest website content."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from core.config import BaseConfig
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
    WebsiteSource,
)
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from plugins.ingest_website.crawler import crawl
from plugins.ingest_website.html_parser import extract_text, extract_title

logger = logging.getLogger(__name__)


class IngestWebsitePlugin:
    """Crawls website sources and ingests content into the knowledge store."""

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

    async def startup(self) -> None:
        logger.info("IngestWebsitePlugin started")

    async def shutdown(self) -> None:
        logger.info("IngestWebsitePlugin stopped")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_collection_name(event: IngestWebsite) -> str:
        """Determine the target collection name.

        When the enriched ``sources`` field is provided **and**
        ``persona_id`` is set, the collection is named after the
        persona so that all sources land in the same knowledge base.

        For legacy payloads that only carry ``baseUrl``, the existing
        netloc-based naming is preserved to avoid breaking data in
        production.
        """
        # Enriched path: persona-based naming
        if event.persona_id:
            return f"{event.persona_id}-knowledge"

        # Legacy fallback: netloc-based naming
        if event.base_url:
            netloc = urlparse(event.base_url).netloc.replace(":", "-")
            return f"{netloc}-knowledge"

        return "unknown-knowledge"

    async def _crawl_source(self, source: WebsiteSource) -> list[Document]:
        """Crawl a single source and convert pages to Documents."""
        pages = await crawl(
            source.url,
            page_limit=source.page_limit,
            max_depth=source.max_depth,
            include_patterns=source.include_patterns,
            exclude_patterns=source.exclude_patterns,
        )

        documents: list[Document] = []
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
        return documents

    def _build_pipeline_steps(self) -> list:
        """Build the ingest pipeline step chain."""
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
            bok_llm = self._bok_llm or summary_llm
            steps.append(BodyOfKnowledgeSummaryStep(llm_port=bok_llm))
        steps.append(EmbedStep(embeddings_port=self._embeddings))
        steps.append(StoreStep(knowledge_store_port=self._knowledge_store))
        steps.append(OrphanCleanupStep(knowledge_store_port=self._knowledge_store))
        return steps

    async def _store_source_config(
        self,
        collection_name: str,
        event: IngestWebsite,
    ) -> None:
        """Persist source configuration in collection metadata for refresh."""
        try:
            await self._knowledge_store.set_collection_metadata(
                collection_name,
                {
                    "_source_config": event.get_source_config_json(),
                    "_ingestion_mode": event.mode.value,
                    "_last_ingested_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to store source config in collection metadata: %s", exc
            )

    # ------------------------------------------------------------------
    # Main handler
    # ------------------------------------------------------------------

    async def handle(
        self, event: IngestWebsite, **ports  # noqa: ARG002
    ) -> IngestWebsiteResult:
        try:
            collection_name = self._resolve_collection_name(event)
            sources = event.sources or []

            if not sources:
                return IngestWebsiteResult(
                    result=IngestionResult.SUCCESS,
                    error="No sources provided",
                )

            # FULL mode: wipe collection before ingesting
            if event.mode == IngestionMode.FULL:
                logger.info(
                    "FULL ingestion mode: deleting collection %s",
                    collection_name,
                )
                await self._knowledge_store.delete_collection(collection_name)

            # Crawl each source, aggregating documents
            all_documents: list[Document] = []
            source_errors: list[str] = []

            for source in sources:
                try:
                    docs = await self._crawl_source(source)
                    all_documents.extend(docs)
                    logger.info(
                        "Crawled %d documents from %s", len(docs), source.url
                    )
                except Exception as exc:
                    msg = f"Failed to crawl {source.url}: {exc}"
                    logger.warning(msg)
                    source_errors.append(msg)

            if not all_documents and not source_errors:
                return IngestWebsiteResult(
                    result=IngestionResult.SUCCESS,
                    error="No content extracted from any source",
                )

            if not all_documents and source_errors:
                return IngestWebsiteResult(
                    result=IngestionResult.FAILURE,
                    error="; ".join(source_errors),
                )

            # Run ingest pipeline on aggregated documents
            steps = self._build_pipeline_steps()
            engine = IngestEngine(steps=steps)
            result = await engine.run(all_documents, collection_name)

            # Store source config for future refresh
            await self._store_source_config(collection_name, event)

            # Combine pipeline errors with per-source errors
            all_errors = source_errors + (result.errors or [])

            return IngestWebsiteResult(
                result=(
                    IngestionResult.SUCCESS
                    if result.success
                    else IngestionResult.FAILURE
                ),
                error="; ".join(all_errors) if all_errors else "",
            )

        except Exception as exc:
            logger.exception("Website ingestion failed: %s", exc)
            return IngestWebsiteResult(
                result=IngestionResult.FAILURE,
                error=str(exc),
            )
