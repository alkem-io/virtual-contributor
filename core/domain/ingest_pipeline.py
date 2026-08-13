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
    """Descriptor carried by a document (and its chunks) through ingestion.

    The hierarchy fields record *where in a space tree* the content came from,
    so retrieval can be scoped to a space or subspace.

    ``depth`` is the tier in the space tree, not the distance from the root
    through every node kind: 0 = ingest root (space or knowledge base),
    1 = first-level subspace, 2 = second-level subspace, 3 = contribution
    (post, whiteboard, link). A callout carries the depth of the node that
    *owns* it rather than a tier of its own; it is identified by
    ``callout_id`` and by its document type.

    ``subspace_id``/``subspace_name`` name the **nearest containing**
    subspace. For a second-level subspace's own content that is itself; for
    content beneath it, it is the subspace that contains that content — never
    the first-level ancestor.

    All six fields default to "unknown" so existing construction sites (e.g.
    website ingestion, which has no tree position at all) keep working
    untouched.
    """

    document_id: str
    source: str
    type: str = "knowledge"
    title: str = ""
    embedding_type: str = "knowledge"
    uri: str | None = None
    space_id: str | None = None
    space_name: str | None = None
    subspace_id: str | None = None
    subspace_name: str | None = None
    callout_id: str | None = None
    depth: int = 0


@dataclass
class Chunk:
    content: str
    metadata: DocumentMetadata
    chunk_index: int
    summary: str | None = None
    embedding: list[float] | None = None
    content_hash: str | None = None


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
    chunks_skipped: int = 0
    chunks_deleted: int = 0
