"""Ingest pipeline data classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
