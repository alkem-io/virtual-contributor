"""Shared ingest pipeline: chunk → summarize → embed → store."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    KNOWLEDGE = "knowledge"
    SPACE = "space"
    SUBSPACE = "subspace"
    CALLOUT = "callout"
    PDF_FILE = "pdf_file"
    SPREADSHEET = "spreadsheet"
    DOCUMENT = "document"
    LINK = "link"
    MEMO = "memo"
    WHITEBOARD = "whiteboard"
    COLLECTION = "collection"
    POST = "post"
    NONE = "none"


@dataclass
class DocumentMetadata:
    document_id: str
    source: str
    type: str = "knowledge"
    title: str = ""
    embedding_type: str = "knowledge"


@dataclass
class Chunk:
    content: str
    metadata: DocumentMetadata
    chunk_index: int
    summary: str | None = None
    embedding: list[float] | None = None


@dataclass
class Document:
    content: str
    metadata: DocumentMetadata
    chunks: list[Chunk] | None = None


@dataclass
class IngestResult:
    collection_name: str
    documents_processed: int
    chunks_stored: int
    errors: list[str] = field(default_factory=list)
    success: bool = True


async def run_ingest_pipeline(
    documents: list[Document],
    collection_name: str,
    embeddings_port,
    knowledge_store_port,
    llm_port=None,
    chunk_size: int = 2000,
    chunk_overlap: int = 400,
    batch_size: int = 20,
    summary_length: int = 10000,
    summarize: bool = False,
) -> IngestResult:
    """Execute the shared ingest pipeline.

    1. Chunk documents using RecursiveCharacterTextSplitter
    2. Optionally summarize via LLM
    3. Embed chunks via EmbeddingsPort
    4. Store in batches via KnowledgeStorePort
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    all_chunks: list[Chunk] = []
    errors: list[str] = []

    # Step 1: Chunk
    for doc in documents:
        try:
            text_chunks = splitter.split_text(doc.content)
            for i, text in enumerate(text_chunks):
                chunk = Chunk(
                    content=text,
                    metadata=doc.metadata,
                    chunk_index=i,
                )
                all_chunks.append(chunk)
        except Exception as exc:
            errors.append(f"Chunking failed for {doc.metadata.document_id}: {exc}")

    if not all_chunks:
        return IngestResult(
            collection_name=collection_name,
            documents_processed=len(documents),
            chunks_stored=0,
            errors=errors,
            success=len(errors) == 0,
        )

    # Step 2: Summarize (optional)
    if summarize and llm_port:
        from core.domain.summarize_graph import summarize_document
        for doc in documents:
            doc_chunks = [c for c in all_chunks if c.metadata.document_id == doc.metadata.document_id]
            if len(doc_chunks) > 1 and len(doc.content) > summary_length:
                try:
                    summary = await summarize_document(
                        [c.content for c in doc_chunks],
                        llm_port.invoke,
                        summary_length,
                    )
                    for chunk in doc_chunks:
                        chunk.summary = summary
                except Exception as exc:
                    errors.append(f"Summarization failed for {doc.metadata.document_id}: {exc}")

    # Step 3: Embed in batches
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        texts = [c.summary or c.content for c in batch]
        try:
            embeddings = await embeddings_port.embed(texts)
            for chunk, embedding in zip(batch, embeddings):
                chunk.embedding = embedding
        except Exception as exc:
            errors.append(f"Embedding failed for batch {i // batch_size}: {exc}")

    # Step 4: Store in batches
    chunks_stored = 0
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        try:
            docs = [c.summary or c.content for c in batch]
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
            ids = [
                f"{c.metadata.document_id}-{c.chunk_index}"
                for c in batch
            ]
            await knowledge_store_port.ingest(
                collection=collection_name,
                documents=docs,
                metadatas=metadatas,
                ids=ids,
            )
            chunks_stored += len(batch)
        except Exception as exc:
            errors.append(f"Storage failed for batch {i // batch_size}: {exc}")

    return IngestResult(
        collection_name=collection_name,
        documents_processed=len(documents),
        chunks_stored=chunks_stored,
        errors=errors,
        success=chunks_stored > 0 and len(errors) == 0,
    )
