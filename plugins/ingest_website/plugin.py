"""IngestWebsitePlugin — crawl, extract, ingest website content."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from core.domain.ingest_pipeline import Document, DocumentMetadata, run_ingest_pipeline
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
    ) -> None:
        self._llm = llm
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
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

            # Delete existing collection for re-ingestion
            await self._knowledge_store.delete_collection(collection_name)

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
                return IngestWebsiteResult(
                    result=IngestionResult.SUCCESS,
                    error="No content extracted",
                )

            # Run ingest pipeline
            result = await run_ingest_pipeline(
                documents=documents,
                collection_name=collection_name,
                embeddings_port=self._embeddings,
                knowledge_store_port=self._knowledge_store,
                llm_port=self._llm,
                summarize=True,
            )

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
