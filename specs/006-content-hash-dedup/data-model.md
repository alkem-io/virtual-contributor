# Data Model: Content-Hash Deduplication and Orphan Cleanup

**Feature**: 006-content-hash-dedup | **Date**: 2026-04-06

## Entity Changes

### Chunk (modified)

**File**: `core/domain/ingest_pipeline.py`

```python
@dataclass
class Chunk:
    content: str
    metadata: DocumentMetadata
    chunk_index: int
    summary: str | None = None
    embedding: list[float] | None = None
    content_hash: str | None = None  # NEW: SHA-256 fingerprint
```

| Field | Type | Description |
|---|---|---|
| `content` | `str` | Chunk text content (existing) |
| `metadata` | `DocumentMetadata` | Parent document metadata (existing) |
| `chunk_index` | `int` | Position within document (existing) |
| `summary` | `str \| None` | Optional summary text (existing) |
| `embedding` | `list[float] \| None` | Vector embedding (existing) |
| `content_hash` | `str \| None` | **NEW** — SHA-256 hex digest of content + embedding-relevant metadata. Computed by `ContentHashStep`. Serves as the chunk's storage ID for content chunks. `None` for summary chunks (which use deterministic IDs). |

**Validation**: `content_hash` is a 64-character lowercase hex string when set. No Pydantic validation needed — it's a stdlib `hashlib.sha256().hexdigest()` output.

---

### PipelineContext (modified)

**File**: `core/domain/pipeline/engine.py`

```python
@dataclass
class PipelineContext:
    collection_name: str
    documents: list[Document]
    chunks: list[Chunk] = field(default_factory=list)
    document_summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, StepMetrics] = field(default_factory=dict)
    chunks_stored: int = 0
    # NEW fields for dedup tracking
    unchanged_chunk_hashes: set[str] = field(default_factory=set)
    orphan_ids: set[str] = field(default_factory=set)
    removed_document_ids: set[str] = field(default_factory=set)
    changed_document_ids: set[str] = field(default_factory=set)
    chunks_skipped: int = 0
    chunks_deleted: int = 0
    change_detection_ran: bool = False
```

| Field | Type | Description |
|---|---|---|
| `unchanged_chunk_hashes` | `set[str]` | **NEW** — Content hashes of chunks that already exist unchanged in the store. `ChangeDetectionStep` populates this; `EmbedStep` uses it (indirectly — unchanged chunks get their embedding pre-loaded so they're skipped). |
| `orphan_ids` | `set[str]` | **NEW** — Storage IDs of chunks that exist in the store but are no longer produced by current chunking. `ChangeDetectionStep` populates this; `OrphanCleanupStep` deletes them. |
| `removed_document_ids` | `set[str]` | **NEW** — Document IDs that were in the store but are not in the current ingestion batch. `ChangeDetectionStep` populates this; `OrphanCleanupStep` cleans up their chunks. |
| `changed_document_ids` | `set[str]` | **NEW** — Document IDs with at least one changed or new chunk. `ChangeDetectionStep` populates this; `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` use it to skip unchanged documents. |
| `chunks_skipped` | `int` | **NEW** — Count of chunks skipped due to dedup (for metrics/logging per FR-004). |
| `chunks_deleted` | `int` | **NEW** — Count of orphan chunks deleted (for metrics/logging). |
| `change_detection_ran` | `bool` | **NEW** — Set to `True` by `ChangeDetectionStep` on successful completion. Disambiguates "no changes detected" (empty `changed_document_ids` + `True`) from "change detection not in pipeline" (empty `changed_document_ids` + `False`). `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` check this flag to decide whether to skip unchanged documents. |

---

### GetResult (new)

**File**: `core/ports/knowledge_store.py`

```python
@dataclass
class GetResult:
    """Result returned from a knowledge store get-by-ID or get-by-filter operation."""
    ids: list[str]
    metadatas: list[dict] | None = None
    documents: list[str] | None = None
    embeddings: list[list[float]] | None = None
```

| Field | Type | Description |
|---|---|---|
| `ids` | `list[str]` | Chunk storage IDs matching the query. Always populated. |
| `metadatas` | `list[dict] \| None` | Chunk metadata dicts, positionally aligned with `ids`. `None` if not requested via `include`. |
| `documents` | `list[str] \| None` | Chunk text content, positionally aligned with `ids`. `None` if not requested. |
| `embeddings` | `list[list[float]] \| None` | Embedding vectors, positionally aligned with `ids`. `None` if not requested. |

**Note**: Unlike `QueryResult` (which has nested lists for multi-query results), `GetResult` uses flat lists since `get()` is a single lookup operation.

---

### IngestResult (modified)

**File**: `core/domain/ingest_pipeline.py`

```python
@dataclass
class IngestResult:
    collection_name: str
    documents_processed: int
    chunks_stored: int
    errors: list[str] = field(default_factory=list)
    success: bool = True
    chunks_skipped: int = 0   # NEW
    chunks_deleted: int = 0   # NEW
```

| Field | Type | Description |
|---|---|---|
| `chunks_skipped` | `int` | **NEW** — Number of chunks skipped due to content-hash match (dedup). Propagated from `PipelineContext.chunks_skipped`. |
| `chunks_deleted` | `int` | **NEW** — Number of orphan chunks deleted. Propagated from `PipelineContext.chunks_deleted`. |

---

## New Pipeline Steps

### ContentHashStep

**File**: `core/domain/pipeline/steps.py`

**Responsibility**: Compute SHA-256 content fingerprint for each chunk produced by `ChunkStep`.

**Behavior**:
- Iterates over `context.chunks` where `embedding_type == "chunk"`.
- Computes `content_hash = sha256("\0".join([content, title, source, type, document_id]))`.
- Sets `chunk.content_hash = content_hash`.
- Leaves summary chunks (if any already exist) with `content_hash = None`.

**Dependencies**: None (stdlib `hashlib` only).

---

### ChangeDetectionStep

**File**: `core/domain/pipeline/steps.py`

**Responsibility**: Query the knowledge store for existing chunks, determine which are unchanged, and identify orphans.

**Behavior**:
1. Collect all unique `document_id` values from `context.chunks` (content chunks only).
2. For each document, call `knowledge_store.get(collection, where={"documentId": doc_id}, include=["metadatas", "embeddings"])` to retrieve existing chunk IDs and their embeddings.
3. Also collect the set of all existing `documentId` values from the store to detect removed documents. This is done via `knowledge_store.get(collection, where={}, include=["metadatas"])` to retrieve all stored chunk metadata, then extracting unique `documentId` values from the results.
4. For each content chunk in `context.chunks`:
   - If `chunk.content_hash` exists in the store's ID set for that document → chunk is unchanged.
     - Copy the existing embedding onto `chunk.embedding` (so `EmbedStep` skips it).
     - Add to `context.unchanged_chunk_hashes`.
     - Increment `context.chunks_skipped`.
   - Else → chunk is new or changed. Add `document_id` to `context.changed_document_ids`.
5. Orphan detection: For each document, `orphan_ids = existing_ids_for_doc - new_hash_ids_for_doc`. Add to `context.orphan_ids`.
6. Removed document detection: `removed_doc_ids = all_existing_doc_ids - current_doc_ids`. Add to `context.removed_document_ids`.
7. Log skip count at INFO level per FR-004.
8. **Fallback** (FR-008): If the knowledge store lookup fails, log a warning and treat all chunks as new (proceed with full re-embedding). Clear `unchanged_chunk_hashes` and `orphan_ids`.

**Dependencies**: `KnowledgeStorePort` (injected via constructor).

---

### OrphanCleanupStep

**File**: `core/domain/pipeline/steps.py`

**Responsibility**: Delete orphaned chunks and chunks from removed documents.

**Behavior**:
1. If any `StoreStep` errors exist in `context.errors`, skip cleanup entirely (avoid deleting orphans when replacements may not have been stored).
2. If `context.orphan_ids` is non-empty, call `knowledge_store.delete(collection, ids=list(orphan_ids))`.
3. For each `doc_id` in `context.removed_document_ids`, call `knowledge_store.delete(collection, where={"documentId": doc_id})` for content chunks and `knowledge_store.delete(collection, where={"documentId": f"{doc_id}-summary"})` for summary chunks.
4. Update `context.chunks_deleted` with the total count.
5. Log deletion counts at INFO level.

**Dependencies**: `KnowledgeStorePort` (injected via constructor).

---

## Modified Pipeline Steps

### StoreStep (modified)

**Changes**:
- ID generation uses `chunk.content_hash` for content chunks (instead of `{doc_id}-chunk{i}`).
- Summary chunks retain deterministic IDs: `{document_id}-{chunk_index}`.
- Metadata `documentId` field stores the original `document_id` (not the storage ID) for all chunk types, enabling document-level queries.

### EmbedStep (unchanged logic, new behavior)

**No code changes needed.** The existing filter `to_embed = [c for c in context.chunks if c.embedding is None]` naturally skips chunks whose embeddings were pre-loaded by `ChangeDetectionStep`.

### DocumentSummaryStep (modified)

**Changes**:
- Before summarizing a document, check if `document_id` is in `context.changed_document_ids`.
- If the document has no changed chunks, skip summarization (existing summary in store is still valid).

---

## Storage ID Scheme

| Chunk Type | Storage ID | Example |
|---|---|---|
| Content chunk | SHA-256 content hash | `a1b2c3d4e5f6...` (64 hex chars) |
| Document summary | `{document_id}-summary-{chunk_index}` | `space-123-summary-0` |
| BoK summary | `body-of-knowledge-summary-{chunk_index}` | `body-of-knowledge-summary-0` |

## Stored Metadata Schema

All chunk types store the same metadata structure in ChromaDB:

```python
{
    "documentId": str,        # Content: document_id; summary: f"{document_id}-summary"; BoK: "body-of-knowledge-summary"
    "source": str,            # Source identifier
    "type": str,              # Document type
    "title": str,             # Display title
    "embeddingType": str,     # "chunk" | "summary"
    "chunkIndex": int,        # Position within document
}
```

**Key change**: `documentId` stores the original `document_id` for content chunks (enabling `where={"documentId": doc_id}` queries), `f"{document_id}-summary"` for document summaries, and `"body-of-knowledge-summary"` for the BoK entry. `contentHash` is NOT stored in metadata — the content hash is used as the storage ID directly.
