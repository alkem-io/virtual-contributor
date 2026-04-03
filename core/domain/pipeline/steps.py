"""Concrete pipeline step implementations."""

from __future__ import annotations

import asyncio
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
# DocumentSummaryStep
# ---------------------------------------------------------------------------

class DocumentSummaryStep:
    """Generate per-document summaries for docs with >3 chunks."""

    def __init__(
        self,
        llm_port: LLMPort,
        summary_length: int = 2000,
        concurrency: int = 8,
    ) -> None:
        self._llm = llm_port
        self._summary_length = summary_length
        self._concurrency = concurrency

    @property
    def name(self) -> str:
        return "document_summary"

    async def execute(self, context: PipelineContext) -> None:
        # Group chunks by document_id
        chunks_by_doc: dict[str, list[Chunk]] = {}
        for chunk in context.chunks:
            chunks_by_doc.setdefault(chunk.metadata.document_id, []).append(chunk)

        sem = asyncio.Semaphore(self._concurrency)

        async def _summarize_doc(doc_id: str, doc_chunks: list[Chunk]) -> None:
            async with sem:
                try:
                    summary = await _refine_summarize(
                        [c.content for c in doc_chunks],
                        self._llm.invoke,
                        self._summary_length,
                        DOCUMENT_REFINE_SYSTEM,
                        DOCUMENT_REFINE_INITIAL,
                        DOCUMENT_REFINE_SUBSEQUENT,
                    )
                    # Store in context for BoK step
                    context.document_summaries[doc_id] = summary

                    # Create a separate summary chunk
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
                except Exception as exc:
                    context.errors.append(
                        f"DocumentSummaryStep: summarization failed for {doc_id}: {exc}"
                    )

        tasks = [
            _summarize_doc(doc_id, doc_chunks)
            for doc_id, doc_chunks in chunks_by_doc.items()
            if len(doc_chunks) > 3
        ]
        await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# BodyOfKnowledgeSummaryStep
# ---------------------------------------------------------------------------

class BodyOfKnowledgeSummaryStep:
    """Generate a single overview entry for the entire knowledge base."""

    def __init__(
        self,
        llm_port: LLMPort,
        summary_length: int = 2000,
    ) -> None:
        self._llm = llm_port
        self._summary_length = summary_length

    @property
    def name(self) -> str:
        return "body_of_knowledge_summary"

    async def execute(self, context: PipelineContext) -> None:
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
            metadatas = [
                {
                    "documentId": c.metadata.document_id,
                    "source": c.metadata.source,
                    "type": c.metadata.type,
                    "title": c.metadata.title,
                    "embeddingType": c.metadata.embedding_type,
                    "chunkIndex": c.chunk_index,
                }
                for c in batch
            ]
            ids = [f"{c.metadata.document_id}-{c.chunk_index}" for c in batch]
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

