"""Concrete pipeline step implementations."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace

from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.domain.ingest_pipeline import Chunk, DocumentMetadata
from core.domain.pipeline.engine import PipelineContext
from core.domain.pipeline.prompts import (
    BOK_OVERVIEW_INITIAL,
    BOK_OVERVIEW_SUBSEQUENT,
    BOK_OVERVIEW_SYSTEM,
    DOCUMENT_REFINE_INITIAL,
    DOCUMENT_REFINE_SUBSEQUENT,
    DOCUMENT_REFINE_SYSTEM,
)
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared refine helper
# ---------------------------------------------------------------------------

async def _refine_summarize(
    chunks: list[str],
    llm_invoke,
    max_length: int,
    system_prompt: str,
    initial_template: str,
    subsequent_template: str,
) -> str:
    """Refine-pattern summarization with progressive length budgeting."""
    if not chunks:
        return ""

    summary = ""
    for i, chunk in enumerate(chunks):
        progress = 1.0 if len(chunks) == 1 else i / (len(chunks) - 1)
        budget = int(max_length * (0.4 + 0.6 * progress))

        if i == 0:
            human = initial_template.format(budget=budget, text=chunk)
        else:
            human = subsequent_template.format(
                summary=summary, text=chunk, budget=budget,
            )

        summary = await llm_invoke([
            {"role": "system", "content": system_prompt},
            {"role": "human", "content": human},
        ])

    return summary


# ---------------------------------------------------------------------------
# ChunkStep
# ---------------------------------------------------------------------------

class ChunkStep:
    """Split documents into chunks with embeddingType='chunk'."""

    def __init__(
        self,
        chunk_size: int = 2000,
        chunk_overlap: int = 400,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    @property
    def name(self) -> str:
        return "chunk"

    async def execute(self, context: PipelineContext) -> None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        for doc in context.documents:
            try:
                text_chunks = splitter.split_text(doc.content)
                if not text_chunks:
                    continue
                for i, text in enumerate(text_chunks):
                    meta = replace(doc.metadata, embedding_type="chunk")
                    context.chunks.append(
                        Chunk(content=text, metadata=meta, chunk_index=i)
                    )
            except Exception as exc:
                context.errors.append(
                    f"ChunkStep: chunking failed for {doc.metadata.document_id}: {exc}"
                )


# ---------------------------------------------------------------------------
# ContentHashStep
# ---------------------------------------------------------------------------


class ContentHashStep:
    """Compute SHA-256 content fingerprint for each content chunk."""

    @property
    def name(self) -> str:
        return "content_hash"

    async def execute(self, context: PipelineContext) -> None:
        for chunk in context.chunks:
            if chunk.metadata.embedding_type != "chunk":
                continue
            canonical = "\0".join([
                chunk.content,
                chunk.metadata.title,
                chunk.metadata.source,
                chunk.metadata.type,
                chunk.metadata.document_id,
            ])
            chunk.content_hash = hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest()


# ---------------------------------------------------------------------------
# ChangeDetectionStep
# ---------------------------------------------------------------------------


class ChangeDetectionStep:
    """Query store for existing chunks, mark unchanged, identify orphans."""

    def __init__(self, knowledge_store_port: KnowledgeStorePort) -> None:
        self._store = knowledge_store_port

    @property
    def name(self) -> str:
        return "change_detection"

    async def execute(self, context: PipelineContext) -> None:
        try:
            await self._detect(context)
        except Exception as exc:
            logger.warning(
                "Change detection failed, treating all chunks as new: %s", exc
            )
            context.unchanged_chunk_hashes.clear()
            context.orphan_ids.clear()
            context.removed_document_ids.clear()
            context.changed_document_ids.clear()
            context.chunks_skipped = 0
            for chunk in context.chunks:
                if chunk.metadata.embedding_type == "chunk":
                    chunk.embedding = None

    async def _detect(self, context: PipelineContext) -> None:
        # Collect current document IDs from content chunks
        current_doc_ids: set[str] = set()
        chunks_by_doc: dict[str, list] = {}
        for chunk in context.chunks:
            if chunk.metadata.embedding_type != "chunk":
                continue
            doc_id = chunk.metadata.document_id
            current_doc_ids.add(doc_id)
            chunks_by_doc.setdefault(doc_id, []).append(chunk)

        # Get all existing document IDs from store (content chunks only)
        all_existing = await self._store.get(
            collection=context.collection_name,
            include=["metadatas"],
        )
        existing_doc_ids: set[str] = set()
        if all_existing.metadatas:
            for meta in all_existing.metadatas:
                if meta.get("embeddingType") != "chunk":
                    continue
                doc_id_val = meta.get("documentId")
                if doc_id_val:
                    existing_doc_ids.add(doc_id_val)

        # Detect removed documents
        context.removed_document_ids = existing_doc_ids - current_doc_ids

        # Per-document change detection
        for doc_id, doc_chunks in chunks_by_doc.items():
            existing = await self._store.get(
                collection=context.collection_name,
                where={"documentId": doc_id},
                include=["metadatas", "embeddings"],
            )

            existing_ids = set(existing.ids)
            existing_embeddings: dict[str, list[float]] = {}
            if existing.embeddings:
                for eid, emb in zip(existing.ids, existing.embeddings):
                    existing_embeddings[eid] = emb

            new_hashes: set[str] = set()
            for chunk in doc_chunks:
                h = chunk.content_hash
                if h is None:
                    continue
                new_hashes.add(h)
                if h in existing_ids:
                    # Unchanged — pre-load embedding so EmbedStep skips it
                    if h in existing_embeddings:
                        chunk.embedding = existing_embeddings[h]
                    context.unchanged_chunk_hashes.add(h)
                    context.chunks_skipped += 1
                else:
                    context.changed_document_ids.add(doc_id)

            # Orphan detection for this document
            orphans = existing_ids - new_hashes
            if orphans:
                context.changed_document_ids.add(doc_id)
            context.orphan_ids.update(orphans)

        context.change_detection_ran = True
        logger.info(
            "Change detection: %d skipped, %d changed docs, %d orphans, %d removed docs",
            context.chunks_skipped,
            len(context.changed_document_ids),
            len(context.orphan_ids),
            len(context.removed_document_ids),
        )


# ---------------------------------------------------------------------------
# DocumentSummaryStep
# ---------------------------------------------------------------------------

class DocumentSummaryStep:
    """Generate per-document summaries for docs with >= chunk_threshold chunks."""

    def __init__(
        self,
        llm_port: LLMPort,
        summary_length: int = 10000,
        concurrency: int = 8,
        chunk_threshold: int = 4,
    ) -> None:
        if chunk_threshold < 1:
            raise ValueError("chunk_threshold must be >= 1")
        self._llm = llm_port
        self._summary_length = summary_length
        self._concurrency = concurrency
        self._chunk_threshold = chunk_threshold
        self._model_name = getattr(
            getattr(llm_port, "_llm", None), "model", "unknown"
        )

    @property
    def name(self) -> str:
        return "document_summary"

    async def execute(self, context: PipelineContext) -> None:
        # Group chunks by document_id
        chunks_by_doc: dict[str, list[Chunk]] = {}
        for chunk in context.chunks:
            chunks_by_doc.setdefault(chunk.metadata.document_id, []).append(chunk)

        docs_to_summarize = [
            (doc_id, doc_chunks)
            for doc_id, doc_chunks in chunks_by_doc.items()
            if len(doc_chunks) >= self._chunk_threshold
            and (
                not context.change_detection_ran
                or doc_id in context.changed_document_ids
            )
        ]

        for doc_id, doc_chunks in docs_to_summarize:
            try:
                logger.info(
                    "Summarizing document %s (%d chunks) [model=%s]",
                    doc_id, len(doc_chunks), self._model_name,
                )
                summary = await _refine_summarize(
                    [c.content for c in doc_chunks],
                    self._llm.invoke,
                    self._summary_length,
                    DOCUMENT_REFINE_SYSTEM,
                    DOCUMENT_REFINE_INITIAL,
                    DOCUMENT_REFINE_SUBSEQUENT,
                )
                context.document_summaries[doc_id] = summary

                source_meta = doc_chunks[0].metadata
                summary_meta = DocumentMetadata(
                    document_id=f"{doc_id}-summary",
                    source=source_meta.source,
                    type=source_meta.type,
                    title=source_meta.title,
                    embedding_type="summary",
                )
                context.chunks.append(
                    Chunk(content=summary, metadata=summary_meta, chunk_index=0)
                )
                logger.info("Summarized document %s", doc_id)
            except Exception as exc:
                logger.warning("Summarization failed for %s: %s", doc_id, exc)
                context.errors.append(
                    f"DocumentSummaryStep: summarization failed for {doc_id}: {exc}"
                )


# ---------------------------------------------------------------------------
# BodyOfKnowledgeSummaryStep
# ---------------------------------------------------------------------------

class BodyOfKnowledgeSummaryStep:
    """Generate a single overview entry for the entire knowledge base."""

    def __init__(
        self,
        llm_port: LLMPort,
        summary_length: int = 10000,
    ) -> None:
        self._llm = llm_port
        self._summary_length = summary_length
        self._model_name = getattr(
            getattr(llm_port, "_llm", None), "model", "unknown"
        )

    @property
    def name(self) -> str:
        return "body_of_knowledge_summary"

    async def execute(self, context: PipelineContext) -> None:
        # Skip if change detection ran and found no changes or removals
        if (
            context.change_detection_ran
            and not context.changed_document_ids
            and not context.removed_document_ids
        ):
            return

        # Collect unique document IDs from raw chunks (exclude summaries)
        seen_doc_ids: list[str] = []
        for chunk in context.chunks:
            doc_id = chunk.metadata.document_id
            if doc_id not in seen_doc_ids and chunk.metadata.embedding_type != "summary":
                seen_doc_ids.append(doc_id)

        if not seen_doc_ids:
            return

        # For each doc: prefer document_summaries, else concatenate raw chunk content
        sections: list[str] = []
        chunks_by_doc: dict[str, list[str]] = {}
        for chunk in context.chunks:
            if chunk.metadata.embedding_type != "summary":
                chunks_by_doc.setdefault(chunk.metadata.document_id, []).append(chunk.content)

        for doc_id in seen_doc_ids:
            if doc_id in context.document_summaries:
                sections.append(context.document_summaries[doc_id])
            elif doc_id in chunks_by_doc:
                sections.append("\n".join(chunks_by_doc[doc_id]))

        if not sections:
            return

        try:
            logger.info(
                "Generating body-of-knowledge summary (%d sections) [model=%s]",
                len(sections), self._model_name,
            )
            bok_summary = await _refine_summarize(
                sections,
                self._llm.invoke,
                self._summary_length,
                BOK_OVERVIEW_SYSTEM,
                BOK_OVERVIEW_INITIAL,
                BOK_OVERVIEW_SUBSEQUENT,
            )
            bok_meta = DocumentMetadata(
                document_id="body-of-knowledge-summary",
                source="generated",
                type="bodyOfKnowledgeSummary",
                title="Body of Knowledge Overview",
                embedding_type="summary",
            )
            context.chunks.append(
                Chunk(content=bok_summary, metadata=bok_meta, chunk_index=0)
            )
        except Exception as exc:
            context.errors.append(
                f"BodyOfKnowledgeSummaryStep: overview generation failed: {exc}"
            )


# ---------------------------------------------------------------------------
# EmbedStep
# ---------------------------------------------------------------------------

class EmbedStep:
    """Embed all chunks via EmbeddingsPort. Always embeds chunk.content."""

    def __init__(
        self,
        embeddings_port: EmbeddingsPort,
        batch_size: int = 50,
    ) -> None:
        self._embeddings = embeddings_port
        self._batch_size = batch_size

    @property
    def name(self) -> str:
        return "embed"

    async def execute(self, context: PipelineContext) -> None:
        # Filter to chunks that don't already have embeddings
        to_embed = [c for c in context.chunks if c.embedding is None]

        for i in range(0, len(to_embed), self._batch_size):
            batch = to_embed[i : i + self._batch_size]
            texts = [c.content for c in batch]
            try:
                embeddings = await self._embeddings.embed(texts)
                for chunk, embedding in zip(batch, embeddings):
                    chunk.embedding = embedding
            except Exception as exc:
                context.errors.append(
                    f"EmbedStep: embedding failed for batch {i // self._batch_size}: {exc}"
                )


# ---------------------------------------------------------------------------
# StoreStep
# ---------------------------------------------------------------------------

class StoreStep:
    """Persist chunks to ChromaDB via KnowledgeStorePort."""

    def __init__(
        self,
        knowledge_store_port: KnowledgeStorePort,
        batch_size: int = 50,
    ) -> None:
        self._store = knowledge_store_port
        self._batch_size = batch_size

    @property
    def name(self) -> str:
        return "store"

    async def execute(self, context: PipelineContext) -> None:
        storable = [c for c in context.chunks if c.embedding is not None]
        skipped = len(context.chunks) - len(storable)
        if skipped > 0:
            context.errors.append(
                f"StoreStep: skipped {skipped} chunks without embeddings"
            )

        for i in range(0, len(storable), self._batch_size):
            batch = storable[i : i + self._batch_size]

            documents = [c.content for c in batch]
            metadatas = []
            ids = []
            for c in batch:
                if c.metadata.embedding_type == "chunk" and c.content_hash:
                    # Content-addressable: use content hash as storage ID
                    storage_id = c.content_hash
                elif c.metadata.embedding_type == "summary":
                    # Deterministic summary ID
                    storage_id = f"{c.metadata.document_id}-{c.chunk_index}"
                else:
                    # BoK summary or fallback
                    storage_id = f"{c.metadata.document_id}-{c.chunk_index}"
                metadatas.append({
                    "documentId": c.metadata.document_id,
                    "source": c.metadata.source,
                    "type": c.metadata.type,
                    "title": c.metadata.title,
                    "embeddingType": c.metadata.embedding_type,
                    "chunkIndex": c.chunk_index,
                })
                ids.append(storage_id)
            batch_embeddings = [c.embedding for c in batch]

            try:
                await self._store.ingest(
                    collection=context.collection_name,
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                    embeddings=batch_embeddings,
                )
                context.chunks_stored += len(batch)
            except Exception as exc:
                context.errors.append(
                    f"StoreStep: storage failed for batch {i // self._batch_size}: {exc}"
                )


# ---------------------------------------------------------------------------
# OrphanCleanupStep
# ---------------------------------------------------------------------------


class OrphanCleanupStep:
    """Delete orphaned chunks and chunks from removed documents."""

    destructive = True

    def __init__(self, knowledge_store_port: KnowledgeStorePort) -> None:
        self._store = knowledge_store_port

    @property
    def name(self) -> str:
        return "orphan_cleanup"

    async def execute(self, context: PipelineContext) -> None:
        deleted = 0

        # Delete orphan chunk IDs
        if context.orphan_ids:
            try:
                await self._store.delete(
                    collection=context.collection_name,
                    ids=list(context.orphan_ids),
                )
                deleted += len(context.orphan_ids)
            except Exception as exc:
                context.errors.append(
                    f"OrphanCleanupStep: failed to delete orphan chunks: {exc}"
                )

        # Delete all chunks for removed documents (content + summary)
        for doc_id in context.removed_document_ids:
            try:
                await self._store.delete(
                    collection=context.collection_name,
                    where={"documentId": doc_id},
                )
                # Also delete the document's summary chunks
                await self._store.delete(
                    collection=context.collection_name,
                    where={"documentId": f"{doc_id}-summary"},
                )
                deleted += 1
            except Exception as exc:
                context.errors.append(
                    f"OrphanCleanupStep: failed to delete chunks for removed document {doc_id}: {exc}"
                )

        context.chunks_deleted = deleted
        if deleted > 0:
            logger.info(
                "Orphan cleanup: deleted %d orphan chunks, cleaned %d removed documents",
                len(context.orphan_ids),
                len(context.removed_document_ids),
            )

