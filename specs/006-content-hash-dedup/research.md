# Research: Content-Hash Deduplication and Orphan Cleanup

**Feature**: 006-content-hash-dedup | **Date**: 2026-04-06

## R1: ChromaDB `get()` and `delete()` API Capabilities

**Decision**: Extend `KnowledgeStorePort` with `get()` (by IDs and/or metadata filter) and `delete()` (by IDs and/or metadata filter), implemented via ChromaDB's native `collection.get()` and `collection.delete()` APIs.

**Rationale**: The current port only has `query()` (vector similarity), `ingest()` (upsert), and `delete_collection()` (full wipe). Content-hash dedup requires:
- **Lookup by IDs**: `collection.get(ids=[...], include=["metadatas"])` — to check if content hashes already exist in the store.
- **Lookup by metadata filter**: `collection.get(where={"documentId": doc_id}, include=[])` — to find all existing chunk IDs for a document (needed for orphan detection).
- **Delete by IDs**: `collection.delete(ids=[...])` — to remove specific orphaned chunks.
- **Delete by metadata filter**: `collection.delete(where={"documentId": doc_id})` — to remove all chunks for a deleted document.

All four operations are natively supported by the ChromaDB Python client (`chromadb-client ^1.5.0`). The sync calls will be wrapped in `asyncio.to_thread()` with the existing retry logic, consistent with the current adapter pattern.

**Alternatives considered**:
- *Vector query with metadata filter*: Would return approximate results, not exact ID lookups. Rejected — dedup requires exact matching.
- *Separate dedup store (e.g., Redis/SQLite)*: Would add operational complexity and a new dependency. Rejected — ChromaDB already stores the metadata we need.

---

## R2: Content Hash Input Normalization

**Decision**: SHA-256 hash of a canonical string formed by joining the chunk's text content and all embedding-relevant metadata fields with a null byte (`\0`) separator, in a fixed field order.

**Rationale**: The hash must be deterministic across runs. Using a fixed field order with an unambiguous separator ensures identical content always produces the same hash. The null byte separator avoids collisions from field value concatenation (e.g., `title="ab"` + `source="cd"` vs `title="abc"` + `source="d"`).

**Hash input fields** (in order):
1. `content` — the chunk text
2. `metadata.title` — document title
3. `metadata.source` — source identifier (URL, space ID, etc.)
4. `metadata.type` — document type enum value
5. `metadata.document_id` — parent document identifier (encodes hierarchy/breadcrumbs)

**Excluded from hash**:
- `embedding_type` — always "chunk" for content chunks; including it would make summary hashes collide differently but adds no dedup value.
- `chunk_index` — position within document is a consequence of content, not an input to embedding. Two chunks with identical text+metadata but different indices should deduplicate.

**Format**:
```python
canonical = "\0".join([content, title, source, type, document_id])
content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Alternatives considered**:
- *JSON serialization of a dict*: Python dicts have stable ordering since 3.7, but JSON serialization adds unnecessary overhead and quotes. Rejected.
- *Include chunk_index in hash*: Would prevent deduplication of overlapping chunks across documents. Rejected — the spec explicitly says content-addressable storage where "two chunks with identical text and metadata produce the same ID."
- *MD5 instead of SHA-256*: Faster but weaker collision resistance. SHA-256 is specified in the requirements (FR-001). The performance difference is negligible at this scale.

---

## R3: Pipeline Step Sequencing

**Decision**: Insert three new steps into the pipeline in specific positions relative to existing steps.

**New pipeline order**:
1. `ChunkStep` — split documents into chunks (existing, unchanged)
2. `ContentHashStep` — compute SHA-256 fingerprint for each chunk (**new**)
3. `ChangeDetectionStep` — query store for existing hashes, mark unchanged chunks, identify orphans (**new**)
4. `DocumentSummaryStep` — generate per-document summaries, skip unchanged documents (existing, **modified behavior**)
5. `BodyOfKnowledgeSummaryStep` — generate BoK overview (existing, unchanged)
6. `EmbedStep` — skip chunks already marked with embeddings from store (existing, **leverages existing skip logic**)
7. `StoreStep` — upsert using content-hash IDs (existing, **modified ID scheme**)
8. `OrphanCleanupStep` — delete orphaned chunk IDs identified in step 3 (**new**)

**Rationale**:
- `ContentHashStep` must run immediately after `ChunkStep` because it needs the chunk text and metadata to compute the hash.
- `ChangeDetectionStep` must run before `EmbedStep` so that unchanged chunks can be pre-populated with their existing embeddings (from the store), allowing `EmbedStep`'s existing `if c.embedding is None` filter to naturally skip them.
- `OrphanCleanupStep` must run after `StoreStep` to ensure new chunks are safely stored before orphans are deleted (crash safety).
- `DocumentSummaryStep` can skip documents with zero changed chunks since the existing summaries in the store are still valid.

**Alternatives considered**:
- *Single "DedupStep" combining hash + detection + cleanup*: Violates SRP. Cleanup must happen after storage, not before. Rejected.
- *Hash computation inside ChunkStep*: Possible but mixes concerns. ChunkStep is about text splitting; hashing is a separate domain operation. Rejected for clarity.

---

## R4: Summary Chunk Dedup Strategy

**Decision**: Use a hybrid ID scheme — content-hash IDs for regular chunks, deterministic IDs for summary chunks.

**Regular chunks** (`embeddingType="chunk"`):
- ID = SHA-256 content hash (content-addressable)
- Full dedup: skip embedding if hash matches existing entry

**Summary chunks** (`embeddingType="summary"`):
- ID = `{document_id}-summary-{chunk_index}` (deterministic, stable across re-ingestion)
- Always upserted when the parent document has changed chunks
- Skipped entirely (not regenerated) when the parent document has zero changed chunks

**BoK summary chunk** (`embeddingType="bodyOfKnowledgeSummary"`):
- ID = `body-of-knowledge-summary-0` (deterministic, singleton)
- Regenerated if any document in the corpus has changes

**Rationale**: LLM-generated summaries are non-deterministic — the same input can produce different text across runs. Content-hashing the summary output would never match, defeating dedup. Instead:
- For unchanged documents, we skip summary generation entirely (the existing summary in the store is still valid).
- For changed documents, we regenerate the summary and upsert it with the same deterministic ID, replacing the old version.

**Alternatives considered**:
- *Hash summary inputs (concatenated chunk texts)*: Would detect input changes but still requires LLM call to produce the summary. The optimization of skipping the LLM call for unchanged documents achieves the same result more simply. Rejected.
- *Content-hash all chunks including summaries*: Would cause summary chunks to become orphans on every re-ingestion (new hash each time). Rejected.
- *Never deduplicate summaries*: Would still require the expensive LLM call for unchanged documents. Rejected — skipping unchanged documents saves significant compute.

---

## R5: Document Removal Detection

**Decision**: Detect removed documents by comparing the set of document IDs in the current ingestion batch against the set of document IDs already in the collection, then delete all chunks for documents no longer present.

**Mechanism**:
1. `ChangeDetectionStep` queries the store for all unique `documentId` values in the collection metadata.
2. It computes: `removed_doc_ids = existing_doc_ids - current_doc_ids`
3. `OrphanCleanupStep` deletes all chunks where `documentId` is in `removed_doc_ids`.

**Rationale**: The spec requires (Acceptance Scenario 2.3) that when a document is removed from the source corpus, all its chunks are removed from the store. Since both plugins fetch the complete document set before running the pipeline, the pipeline has full visibility into what documents should exist.

**Edge case**: First ingestion (empty collection) — `existing_doc_ids` is empty, so `removed_doc_ids` is empty. No cleanup needed. Works correctly.

**Alternatives considered**:
- *Timestamp-based staleness*: Would require adding ingestion timestamps and a TTL policy. More complex, less deterministic. Rejected.
- *Plugin-level cleanup (outside pipeline)*: Would duplicate logic across both plugins. Rejected — centralizing in a pipeline step is DRY and testable.

---

## R6: KnowledgeStorePort Extension Approach

**Decision**: Add `get()` and `delete()` as new methods on the existing `KnowledgeStorePort` protocol. Introduce a `GetResult` dataclass for `get()` return values.

**Rationale**: These are fundamental CRUD operations that the port was missing. The port currently only supports Create (ingest), Read-by-similarity (query), and Delete-all (delete_collection). Adding Read-by-ID (get) and Delete-by-ID (delete) completes the CRUD surface without violating Interface Segregation — any knowledge store implementation would naturally support these operations.

**Impact**:
- `KnowledgeStorePort` protocol gains two new methods → any class claiming to implement the protocol must add them.
- `ChromaDBAdapter` is the only concrete adapter → single implementation site.
- No plugin code changes — plugins interact with the store only through pipeline steps.
- This is a port interface change per the constitution → requires an ADR (P8).

**Alternatives considered**:
- *Separate `KnowledgeStoreLookupPort`*: Would over-segregate the interface for two tightly related operations. A store that can write and query can certainly also get-by-ID and delete-by-ID. Rejected.
- *Add methods only to the adapter, not the port*: Would violate Hexagonal Boundaries — pipeline steps must not know about adapters. Rejected.
