# Feature Specification: Content-Hash Deduplication and Orphan Cleanup

**Feature Branch**: `006-content-hash-dedup`  
**Created**: 2026-04-06  
**Status**: Draft  
**Input**: User description: "implement https://github.com/orgs/alkem-io/projects/50/views/8?pane=issue&itemId=172816133&issue=alkem-io%7Cvirtual-contributor%7C30"  
**GitHub Issue**: [alkem-io/virtual-contributor#30](https://github.com/alkem-io/virtual-contributor/issues/30)  
**Parent Epic**: [alkem-io/alkemio#1818](https://github.com/alkem-io/alkemio/issues/1818)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skip Re-embedding of Unchanged Content (Priority: P1)

As a platform operator running repeated ingestion cycles (e.g., tuning chunk sizes, adding breadcrumbs, adjusting hierarchy metadata), I want the system to detect that content chunks have not changed and skip re-embedding them, so that re-ingestion completes significantly faster and consumes less compute resources.

**Why this priority**: Re-embedding unchanged content is the primary source of wasted GPU compute and experimentation slowdown. Eliminating redundant embedding calls delivers the largest immediate time and cost savings.

**Independent Test**: Ingest a corpus, then re-ingest the same corpus without changes. Verify that the system skips embedding for all unchanged chunks (>80% skip rate) and completes faster than a from-scratch ingestion.

**Acceptance Scenarios**:

1. **Given** a corpus has been previously ingested, **When** the same corpus is re-ingested without content changes, **Then** the system skips embedding for all unchanged chunks and logs the skip count.
2. **Given** a corpus has been previously ingested, **When** a subset of documents are modified and re-ingested, **Then** only modified chunks are re-embedded while unchanged chunks are skipped.
3. **Given** a corpus has been previously ingested, **When** re-ingestion occurs with identical content, **Then** the total re-ingestion time is measurably reduced compared to a fresh ingestion.

---

### User Story 2 - Orphan Chunk Cleanup on Re-ingestion (Priority: P1)

As a platform operator adjusting chunking parameters (e.g., changing chunk size from 9000 to 2000), I want the system to automatically remove orphaned chunks that no longer correspond to current chunking results, so that retrieval results are not polluted by stale or irrelevant content fragments.

**Why this priority**: Orphaned chunks directly degrade retrieval quality for end users of the virtual contributor. This is a correctness issue -- stale chunks produce wrong or confusing answers.

**Independent Test**: Ingest a document with one chunk size, then re-ingest with a different chunk size. Verify that chunks from the old chunking are removed and only current chunks remain.

**Acceptance Scenarios**:

1. **Given** a document was ingested producing N chunks, **When** the document is re-ingested with a smaller chunk size producing M chunks (M > N), **Then** only the M new chunks exist in the knowledge store and no chunks from the prior ingestion remain.
2. **Given** a document was ingested producing N chunks, **When** the document is re-ingested with a larger chunk size producing fewer chunks (M < N), **Then** only the M new chunks exist and the (N - M) surplus chunks from the prior ingestion are removed.
3. **Given** a document has been ingested, **When** the document is removed from the source corpus and ingestion runs, **Then** all chunks belonging to that document are removed from the knowledge store.

---

### User Story 3 - Content Fingerprinting for Change Detection (Priority: P2)

As a platform operator, I want each content chunk to carry a cryptographic fingerprint of its content, so that the system can reliably detect whether a chunk has changed between ingestion cycles without comparing full text.

**Why this priority**: Content fingerprinting is the foundational mechanism that enables both deduplication (US1) and future change auditing. It is a prerequisite that supports the higher-priority stories.

**Independent Test**: Ingest a corpus and verify that each stored chunk carries a content fingerprint in its metadata. Modify one document and re-ingest -- verify the fingerprint changes for affected chunks and remains stable for unaffected ones.

**Acceptance Scenarios**:

1. **Given** a document is ingested, **When** chunks are stored, **Then** each chunk's metadata includes a content fingerprint derived from its text content.
2. **Given** a chunk's content has not changed between ingestion cycles, **When** the fingerprint is recomputed, **Then** it matches the previously stored fingerprint.
3. **Given** a chunk's content has been modified, **When** the fingerprint is recomputed, **Then** it differs from the previously stored fingerprint.

---

### User Story 4 - Knowledge Store Lookup and Deletion Capabilities (Priority: P2)

As a platform operator, I want the knowledge store to support looking up existing chunks by their identifiers and deleting chunks that are no longer needed, so that the ingestion pipeline can perform change detection and orphan cleanup.

**Why this priority**: These are enabling capabilities required by US1 (change detection lookup) and US2 (orphan deletion). Without them, the higher-priority stories cannot function.

**Independent Test**: Store chunks in the knowledge store, then look up specific chunks by ID and verify correct metadata is returned. Delete specific chunks and verify they are no longer retrievable.

**Acceptance Scenarios**:

1. **Given** chunks have been stored in the knowledge store, **When** a lookup is performed by chunk identifiers, **Then** the system returns the metadata (including content fingerprint) for matching chunks.
2. **Given** chunks exist in the knowledge store, **When** a delete operation targets specific chunks, **Then** those chunks are removed and subsequent lookups return no results for them.
3. **Given** a delete operation targets chunks that do not exist, **When** the operation executes, **Then** it completes without errors.

---

### Edge Cases

- What happens when a document's content is emptied (zero chunks after re-chunking)? All prior chunks for that document should be removed.
- What happens when the knowledge store is unavailable during change detection lookup? The system should fall back to re-embedding all chunks rather than failing.
- What happens when a chunk's metadata changes but its text content does not? The fingerprint should reflect content relevant to embedding, so metadata-only changes that don't affect embedding should not trigger re-embedding.
- What happens during the first ingestion of a corpus (no prior chunks exist)? The system should proceed normally -- all chunks are treated as new and embedded.
- What happens on first re-ingestion of a corpus after this feature is deployed (legacy chunks without fingerprints)? All legacy chunks are treated as stale, re-embedded, and replaced. This is a one-time cost per document.
- What happens if two ingestion processes target the same document concurrently? Ingestion is serialized per document; the second process waits until the first completes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST compute a cryptographic content fingerprint (SHA-256) for each chunk during the chunking step.
- **FR-002**: System MUST store the content fingerprint as part of each chunk's metadata in the knowledge store.
- **FR-003**: System MUST compare content fingerprints before embedding and skip embedding for chunks whose fingerprint matches the previously stored value.
- **FR-004**: System MUST log the count of skipped (unchanged) chunks at an informational level during re-ingestion.
- **FR-005**: System MUST remove orphaned chunks (chunks belonging to a document that are no longer produced by the current chunking) after upserting new chunks for that document.
- **FR-006**: The knowledge store interface MUST support looking up existing chunks by their content-hash IDs (SHA-256), returning metadata including document association.
- **FR-007**: The knowledge store interface MUST support deleting chunks by their content-hash IDs or by document association.
- **FR-008**: System MUST fall back to full re-embedding if the knowledge store lookup fails during change detection, ensuring ingestion completes even if change detection is temporarily unavailable.
- **FR-009**: The content fingerprint MUST include the chunk text content AND all embedding-relevant metadata fields in fixed order: `content`, `title`, `source`, `type`, `document_id` (which encodes hierarchy and breadcrumbs). Changes to any of these fields trigger re-embedding. Fields are joined with a null byte separator for collision resistance (see research.md R2).
- **FR-010**: System MUST serialize ingestion at the document level — only one ingestion process may operate on a given document at a time — to prevent race conditions during concurrent lookup/delete/upsert operations.

### Key Entities

- **Chunk**: A segment of a document's content produced during the chunking step. Key attributes: text content, chunk index, parent document identifier, content fingerprint (which also serves as the chunk's unique identifier), embedding.
- **Content Fingerprint / Chunk ID**: A SHA-256 hash derived from a chunk's text content and all embedding-relevant metadata (title, breadcrumbs, source, hierarchy context). Serves dual purpose: (1) unique identifier for the chunk in the knowledge store (content-addressable storage), and (2) change-detection mechanism between ingestion cycles. Two chunks with identical text and metadata produce the same ID, enabling natural deduplication. A change to either text or metadata produces a different hash, triggering re-embedding.
- **Knowledge Store Entry**: A persisted chunk in the vector store, including its embedding vector and metadata (document ID, source, type, title, chunk index). The entry's ID is the content fingerprint itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Re-ingestion of an unchanged corpus achieves greater than 80% skip rate for embedding operations.
- **SC-002**: Re-ingestion of an unchanged corpus completes measurably faster than the initial ingestion (proportional to the skip rate).
- **SC-003**: After re-ingestion with changed chunking parameters, zero orphaned chunks remain in the knowledge store for affected documents.
- **SC-004**: All existing ingestion tests continue to pass without modification.
- **SC-005**: New tests cover the three core scenarios: skip-unchanged, detect-changed, and orphan-cleanup.

## Assumptions

- The existing ingestion pipeline and knowledge store infrastructure remain stable and available during this feature's development.
- SHA-256 hashing overhead is negligible relative to embedding costs (microseconds per chunk vs. milliseconds per embedding).
- Knowledge store ID lookups (by chunk identifier) are performant and do not involve vector similarity search.
- The content fingerprint scope includes both chunk text content and all embedding-relevant metadata (title, breadcrumbs, source, hierarchy context). Changes to any of these inputs trigger re-embedding.
- Orphan cleanup operates at the document level -- when a document is re-ingested, orphaned chunks for that document are removed, but chunks for other documents are unaffected.
- First-time ingestion (no prior chunks) works identically to current behavior -- all chunks are treated as new.
- No migration is required for legacy chunks (stored without content fingerprints). On first re-ingestion after this feature ships, all existing chunks for a document are treated as stale, re-embedded, and replaced with fingerprinted versions. Subsequent re-ingestions benefit from deduplication.

## Clarifications

### Session 2026-04-06

- Q: What is the chunk identity scheme? → A: Content hash (SHA-256 of chunk text) as the sole chunk ID (content-addressable storage).
- Q: How are legacy chunks (no fingerprint) handled on first re-ingestion? → A: No migration — all existing chunks treated as stale, re-embedded, and replaced with fingerprinted versions on first re-ingestion.
- Q: What happens with concurrent ingestion of the same document? → A: Serialize ingestion per document — only one process may operate on a given document at a time. The existing RabbitMQ architecture processes messages sequentially per queue (`prefetch=1`), and each plugin runs in its own container. Since ingestion is triggered per-space (one message = one space), and documents within a space are processed sequentially within a single pipeline run, FR-010 is satisfied by the existing architecture. No additional locking mechanism is required.
- Q: What is included in the content fingerprint hash input? → A: Fields in fixed order: `content`, `title`, `source`, `type`, `document_id` (encodes hierarchy/breadcrumbs). Joined with null byte separator. See research.md R2 for rationale.
- Q: What is the performance target for re-ingestion speedup (SC-002)? → A: Keep "measurably faster" — any statistically significant improvement suffices; no fixed percentage threshold.
