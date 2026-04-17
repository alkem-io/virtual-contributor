"""Concrete pipeline step implementations."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, replace

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
    """Refine-pattern summarization with progressive length budgeting.

    If a refinement round fails after a partial summary has been built,
    the last successful summary is returned instead of raising.  A
    partial summary covering rounds 1..N-1 is strictly better than no
    summary at all.
    """
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

        try:
            summary = await llm_invoke([
                {"role": "system", "content": system_prompt},
                {"role": "human", "content": human},
            ])
            logger.debug(
                "Refine round %d/%d complete (%d chars)",
                i + 1, len(chunks), len(summary),
            )
        except Exception:
            if summary:
                logger.warning(
                    "Refine round %d/%d failed; returning partial summary "
                    "from %d completed round(s)",
                    i + 1, len(chunks), i,
                )
                return summary
            raise

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
            context.errors.append(
                f"ChangeDetectionStep: store read failed: {exc}"
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
        all_ids = context.all_document_ids if context.all_document_ids else current_doc_ids
        context.removed_document_ids = existing_doc_ids - all_ids

        # Per-document change detection
        for doc_id, doc_chunks in chunks_by_doc.items():
            existing = await self._store.get(
                collection=context.collection_name,
                where={"documentId": doc_id},
                include=["metadatas", "embeddings"],
            )

            existing_ids = set(existing.ids)
            existing_embeddings: dict[str, list[float]] = {}
            if existing.embeddings is not None and len(existing.embeddings) > 0:
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


@dataclass
class _SummaryResult:
    """Outcome of a single document summarization task."""

    doc_id: str
    summary: str | None = None
    chunk: Chunk | None = None
    doc_chunks: list[Chunk] | None = None
    error: str | None = None


class DocumentSummaryStep:
    """Generate per-document summaries for docs with >= chunk_threshold chunks.

    Summarizations run concurrently, bounded by ``concurrency`` via
    ``asyncio.Semaphore``.  All shared-state mutations on
    ``PipelineContext`` happen *after* ``asyncio.gather`` completes
    (collect-and-apply pattern) to avoid race conditions.

    When ``embeddings_port`` is provided, each document's content chunks and
    its summary chunk are embedded as a background task after summarization
    completes, overlapping LLM-bound summarization I/O with GPU-bound
    embedding I/O.
    """

    def __init__(
        self,
        llm_port: LLMPort,
        summary_length: int = 10000,
        concurrency: int = 8,
        chunk_threshold: int = 4,
        embeddings_port: EmbeddingsPort | None = None,
        embed_batch_size: int = 50,
    ) -> None:
        if chunk_threshold < 1:
            raise ValueError("chunk_threshold must be >= 1")
        if embed_batch_size < 1:
            raise ValueError("embed_batch_size must be >= 1")
        self._llm = llm_port
        self._summary_length = summary_length
        self._concurrency = concurrency
        self._chunk_threshold = chunk_threshold
        self._embeddings = embeddings_port
        self._embed_batch_size = embed_batch_size
        self._model_name = getattr(
            getattr(llm_port, "_llm", None), "model", "unknown"
        )

    @property
    def name(self) -> str:
        return "document_summary"

    async def _embed_document_chunks(
        self,
        chunks: list[Chunk],
        context: PipelineContext,
        doc_id: str,
    ) -> None:
        """Embed a document's chunks inline using the embeddings port.

        Skips chunks that already have embeddings (e.g. from change detection).
        Errors are captured in context.errors without raising.
        """
        assert self._embeddings is not None

        to_embed = [c for c in chunks if c.embedding is None]
        if not to_embed:
            return

        for i in range(0, len(to_embed), self._embed_batch_size):
            batch = to_embed[i : i + self._embed_batch_size]
            texts = [c.content for c in batch]
            try:
                embeddings = await self._embeddings.embed(texts)
                for chunk, embedding in zip(batch, embeddings):
                    chunk.embedding = embedding
            except Exception as exc:
                context.errors.append(
                    f"DocumentSummaryStep: inline embedding failed for "
                    f"{doc_id} batch {i // self._embed_batch_size}: {exc}"
                )

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

        # Mark stale summaries for cleanup: changed documents that dropped
        # below the chunk threshold no longer qualify for summarization,
        # so their existing summary entry must be removed.
        if context.change_detection_ran:
            for doc_id, doc_chunks in chunks_by_doc.items():
                if (
                    doc_id in context.changed_document_ids
                    and len(doc_chunks) < self._chunk_threshold
                ):
                    orphan_id = f"{doc_id}-summary-0"
                    context.orphan_ids.add(orphan_id)
                    logger.info(
                        "Stale summary marked for cleanup: %s "
                        "(%d chunks < threshold %d)",
                        orphan_id, len(doc_chunks), self._chunk_threshold,
                    )

        if not docs_to_summarize:
            return

        sem = asyncio.Semaphore(self._concurrency)
        embed_semaphore = asyncio.Semaphore(self._concurrency)
        embed_tasks: list[asyncio.Task] = []

        async def _summarize_one(
            doc_id: str, doc_chunks: list[Chunk],
        ) -> _SummaryResult:
            async with sem:
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
                    source_meta = doc_chunks[0].metadata
                    summary_meta = DocumentMetadata(
                        document_id=f"{doc_id}-summary",
                        source=source_meta.source,
                        type=source_meta.type,
                        title=source_meta.title,
                        embedding_type="summary",
                    )
                    summary_chunk = Chunk(
                        content=summary, metadata=summary_meta, chunk_index=0,
                    )
                    logger.info("Summarized document %s", doc_id)
                    return _SummaryResult(
                        doc_id=doc_id, summary=summary, chunk=summary_chunk,
                        doc_chunks=doc_chunks,
                    )
                except Exception as exc:
                    logger.warning(
                        "Summarization failed for %s: %s", doc_id, exc,
                    )
                    return _SummaryResult(
                        doc_id=doc_id,
                        error=(
                            f"DocumentSummaryStep: summarization failed "
                            f"for {doc_id}: {exc}"
                        ),
                    )

        # Fan out concurrent summarizations
        results: list[_SummaryResult] = await asyncio.gather(
            *[_summarize_one(d, c) for d, c in docs_to_summarize],
        )

        # Apply results to context in deterministic (input) order
        # and fire background embedding tasks for successful results.
        # Wrapped in try/finally to guarantee background tasks are always
        # awaited — without this, an exception between task creation and
        # the await loop orphans running tasks (silent resource leak).
        try:
            for result in results:
                if result.error is not None:
                    context.errors.append(result.error)
                elif result.summary is None or result.chunk is None:
                    context.errors.append(
                        f"DocumentSummaryStep: unexpected None summary/chunk "
                        f"for {result.doc_id}"
                    )
                else:
                    context.document_summaries[result.doc_id] = result.summary
                    context.chunks.append(result.chunk)

                    # Incremental embedding: fire off embedding as a background
                    # task while remaining results are applied.
                    if self._embeddings is not None and result.doc_chunks is not None:
                        embed_targets = result.doc_chunks + [result.chunk]
                        task = asyncio.create_task(
                            self._embed_document_background(
                                embed_targets, context, result.doc_id,
                                embed_semaphore,
                            )
                        )
                        embed_tasks.append(task)
        finally:
            # Always await background tasks to prevent orphaned coroutines
            # and ensure thread pool slots are freed.
            if embed_tasks:
                await asyncio.gather(*embed_tasks, return_exceptions=True)

    async def _embed_document_background(
        self,
        chunks: list[Chunk],
        context: PipelineContext,
        doc_id: str,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Embed a document's chunks in the background, bounded by semaphore."""
        async with semaphore:
            await self._embed_document_chunks(chunks, context, doc_id)
            embedded_count = sum(
                1 for c in chunks if c.embedding is not None
            )
            logger.info(
                "Inline-embedded %d/%d chunks for document %s",
                embedded_count, len(chunks), doc_id,
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
        max_section_chars: int = 30000,
        knowledge_store_port: "KnowledgeStorePort | None" = None,
        embeddings_port: "EmbeddingsPort | None" = None,
    ) -> None:
        self._llm = llm_port
        self._summary_length = summary_length
        self._max_section_chars = max(1000, max_section_chars)
        self._store = knowledge_store_port
        self._embeddings = embeddings_port
        self._model_name = getattr(
            getattr(llm_port, "_llm", None), "model", "unknown"
        )

    @property
    def name(self) -> str:
        return "body_of_knowledge_summary"

    async def _bok_exists(self, collection: str) -> bool:
        """Check whether a BoK summary already exists in the store."""
        if self._store is None:
            return False
        try:
            result = await self._store.get(
                collection=collection,
                where={"documentId": "body-of-knowledge-summary"},
                include=["metadatas"],
            )
            return len(result.ids) > 0
        except Exception:
            return False

    async def execute(self, context: PipelineContext) -> None:
        # Skip if change detection ran and found no changes or removals
        # — but only if a BoK summary already exists in the store.
        if (
            context.change_detection_ran
            and not context.changed_document_ids
            and not context.removed_document_ids
            and await self._bok_exists(context.collection_name)
        ):
            return

        # Collect unique document IDs and chunk content by doc.
        # In batched mode, raw_chunks_by_doc is pre-populated from batch
        # contexts and chunks may be empty; use documents list for ordering.
        if context.raw_chunks_by_doc:
            seen_doc_ids: list[str] = list(dict.fromkeys(
                doc.metadata.document_id
                for doc in context.documents
                if doc.metadata.document_id in context.raw_chunks_by_doc
            ))
            chunks_by_doc = context.raw_chunks_by_doc
        else:
            seen_doc_ids = []
            for chunk in context.chunks:
                doc_id = chunk.metadata.document_id
                if doc_id not in seen_doc_ids and chunk.metadata.embedding_type != "summary":
                    seen_doc_ids.append(doc_id)
            chunks_by_doc = {}
            for chunk in context.chunks:
                if chunk.metadata.embedding_type != "summary":
                    chunks_by_doc.setdefault(chunk.metadata.document_id, []).append(chunk.content)

        if not seen_doc_ids:
            # Corpus is empty — if documents were removed, mark the BoK
            # summary for cleanup so OrphanCleanupStep deletes it.
            if context.removed_document_ids:
                context.orphan_ids.add("body-of-knowledge-summary-0")
                logger.info(
                    "Corpus empty after removals; marking BoK summary for cleanup"
                )
            return

        # For each doc: prefer document_summaries, else concatenate raw chunk content
        sections: list[str] = []
        for doc_id in seen_doc_ids:
            if doc_id in context.document_summaries:
                sections.append(context.document_summaries[doc_id])
            elif doc_id in chunks_by_doc:
                sections.append("\n".join(chunks_by_doc[doc_id]))

        if not sections:
            return

        # Group sections by character count to limit refinement rounds.
        # Each round is a sequential LLM call; with slow models (e.g.
        # gemma-26b at ~2 min/call), 20 rounds = ~40 min.  Grouping
        # keeps each group under max_section_chars so the input fits
        # in the model's context window alongside the running summary
        # and prompt overhead.
        if len(sections) > 1:
            grouped: list[str] = []
            current_group: list[str] = []
            current_size = 0
            for section in sections:
                if current_group and current_size + len(section) > self._max_section_chars:
                    grouped.append("\n\n---\n\n".join(current_group))
                    current_group = []
                    current_size = 0
                current_group.append(section)
                current_size += len(section)
            if current_group:
                grouped.append("\n\n---\n\n".join(current_group))
            if len(grouped) < len(sections):
                logger.info(
                    "Grouped %d sections into %d refinement rounds "
                    "(max_section_chars=%d)",
                    len(sections), len(grouped), self._max_section_chars,
                )
                sections = grouped

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
            bok_chunk = Chunk(content=bok_summary, metadata=bok_meta, chunk_index=0)

            stored_inline = False
            # Persist inline when both ports are available — this eliminates
            # the window where BoK is generated but not stored, so a later
            # EmbedStep/StoreStep failure can't discard the LLM work.
            if self._embeddings is not None and self._store is not None:
                try:
                    embeddings = await self._embeddings.embed([bok_summary])
                    bok_chunk.embedding = embeddings[0]
                    await self._store.ingest(
                        collection=context.collection_name,
                        documents=[bok_summary],
                        metadatas=[{
                            "documentId": bok_meta.document_id,
                            "source": bok_meta.source,
                            "type": bok_meta.type,
                            "title": bok_meta.title,
                            "embeddingType": bok_meta.embedding_type,
                            "chunkIndex": 0,
                        }],
                        ids=[f"{bok_meta.document_id}-0"],
                        embeddings=[embeddings[0]],
                    )
                    context.chunks_stored += 1
                    logger.info("BoK summary embedded and stored inline")
                    stored_inline = True
                except Exception as exc:
                    logger.warning(
                        "BoK inline persist failed, deferring to finalize "
                        "EmbedStep/StoreStep: %s", exc,
                    )

            if not stored_inline:
                context.chunks.append(bok_chunk)
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
        storable = [
            c for c in context.chunks
            if c.embedding is not None
            and c.content_hash not in context.unchanged_chunk_hashes
        ]

        no_embedding = sum(1 for c in context.chunks if c.embedding is None)
        if no_embedding > 0:
            context.errors.append(
                f"StoreStep: skipped {no_embedding} chunks without embeddings"
            )

        unchanged_skipped = sum(
            1 for c in context.chunks
            if c.embedding is not None
            and c.content_hash in context.unchanged_chunk_hashes
        )
        if unchanged_skipped > 0:
            logger.info(
                "StoreStep: skipped %d unchanged chunks", unchanged_skipped,
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
                meta_entry = {
                    "documentId": c.metadata.document_id,
                    "source": c.metadata.source,
                    "type": c.metadata.type,
                    "title": c.metadata.title,
                    "embeddingType": c.metadata.embedding_type,
                    "chunkIndex": c.chunk_index,
                }
                if getattr(c.metadata, "uri", None):
                    meta_entry["uri"] = c.metadata.uri
                metadatas.append(meta_entry)
                ids.append(storage_id)
            batch_embeddings = [c.embedding for c in batch]

            # Deduplicate by storage ID — keep the last occurrence
            # (e.g. identical chunks across documents share a content hash).
            seen_ids: dict[str, int] = {}
            for idx, sid in enumerate(ids):
                seen_ids[sid] = idx
            if len(seen_ids) < len(ids):
                unique_indices = sorted(seen_ids.values())
                documents = [documents[j] for j in unique_indices]
                metadatas = [metadatas[j] for j in unique_indices]
                ids = [ids[j] for j in unique_indices]
                batch_embeddings = [batch_embeddings[j] for j in unique_indices]

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

    def __init__(self, knowledge_store_port: KnowledgeStorePort) -> None:
        self._store = knowledge_store_port

    @property
    def name(self) -> str:
        return "orphan_cleanup"

    @property
    def destructive(self) -> bool:
        return True

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

