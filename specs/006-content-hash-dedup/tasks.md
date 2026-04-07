# Tasks: Content-Hash Deduplication and Orphan Cleanup

**Input**: Design documents from `/specs/006-content-hash-dedup/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/knowledge-store-port.md, quickstart.md

**Tests**: Included — SC-005 requires tests covering skip-unchanged, detect-changed, and orphan-cleanup scenarios.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing. US3 (Content Fingerprinting) and US4 (Knowledge Store Lookup/Delete) are P2 enablers that block both P1 stories, so they are placed in the Foundational phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Core domain**: `core/` at repository root
- **Plugins**: `plugins/` at repository root
- **Tests**: `tests/` at repository root

---

## Phase 1: Setup

**Purpose**: Project initialization

No setup tasks required — project structure exists and no new directories are needed per plan.md.

---

## Phase 2: Foundational (US3 Content Fingerprinting + US4 Knowledge Store Lookup/Delete)

**Purpose**: Port extension, data model changes, and content hashing — MUST complete before any P1 user story

**Why here**: US3 and US4 are P2 stories but are architectural enablers. US1 depends on content hashes (US3) and store lookups (US4). US2 depends on store deletion (US4) and orphan identification via hashes (US3).

- [x] T001 [P] Add GetResult dataclass and extend KnowledgeStorePort protocol with get() and delete() methods in core/ports/knowledge_store.py
- [x] T002 [P] Add content_hash field to Chunk dataclass and add chunks_skipped/chunks_deleted fields to IngestResult in core/domain/ingest_pipeline.py
- [x] T003 [P] Add dedup tracking fields (unchanged_chunk_hashes, orphan_ids, removed_document_ids, changed_document_ids, chunks_skipped, chunks_deleted) to PipelineContext and propagate chunks_skipped/chunks_deleted to IngestResult in IngestEngine.run() in core/domain/pipeline/engine.py
- [x] T004 [P] Implement get() and delete() methods in ChromaDBAdapter using collection.get()/collection.delete() wrapped in asyncio.to_thread() with existing _retry() logic in core/adapters/chromadb.py
- [x] T005 [P] Implement ContentHashStep — compute SHA-256 of content+title+source+type+document_id joined by null byte separator for each content chunk in core/domain/pipeline/steps.py
- [x] T006 [P] Extend MockKnowledgeStorePort with get() and delete() methods in tests/conftest.py
- [x] T007 Write content hash unit tests — determinism, sensitivity to each metadata field, stability across runs in tests/core/domain/test_content_hash.py

**Checkpoint**: Port extended, data model updated, content hashing works. Foundation ready for P1 stories.

---

## Phase 3: User Story 1 — Skip Re-embedding of Unchanged Content (Priority: P1) MVP

**Goal**: Detect unchanged content chunks via content-hash lookup and skip re-embedding, achieving >80% skip rate on unchanged corpora (SC-001, SC-002).

**Independent Test**: Ingest a corpus, then re-ingest without changes. Verify all chunks are skipped and re-ingestion completes faster.

### Implementation for User Story 1

- [x] T008 [US1] Implement ChangeDetectionStep — query store for existing chunk hashes per document, pre-load embeddings onto unchanged chunks, populate orphan_ids/changed_document_ids/chunks_skipped, log skip count at INFO level (FR-004), fallback to full re-embedding on store failure (FR-008) in core/domain/pipeline/steps.py
- [x] T009 [US1] Modify StoreStep to use chunk.content_hash as storage ID for content chunks (embeddingType="chunk"), use deterministic IDs for summary chunks ({document_id}-summary-{chunk_index}), and store original documentId in metadata for all chunk types in core/domain/pipeline/steps.py

### Tests for User Story 1

- [x] T010 [US1] Write ChangeDetectionStep tests (unchanged skip with embedding pre-load, new chunk detection, orphan identification, removed document detection, fallback on store failure) and StoreStep tests (content-hash ID generation, deterministic summary IDs, metadata documentId correctness) in tests/core/domain/test_pipeline_steps.py

**Checkpoint**: US1 is independently testable — unchanged chunks are skipped and content-hash IDs are used for storage.

---

## Phase 4: User Story 2 — Orphan Chunk Cleanup on Re-ingestion (Priority: P1)

**Goal**: Automatically remove orphaned chunks that no longer correspond to current chunking results, and skip summarization for unchanged documents (SC-003).

**Independent Test**: Ingest a document with one chunk size, re-ingest with a different size. Verify old chunks are removed and only current chunks remain.

### Implementation for User Story 2

- [x] T011 [US2] Implement OrphanCleanupStep — delete orphan chunk IDs from context.orphan_ids via knowledge_store.delete(ids=...), delete all chunks for removed documents via knowledge_store.delete(where={"documentId": doc_id}), update context.chunks_deleted in core/domain/pipeline/steps.py
- [x] T012 [US2] Modify DocumentSummaryStep to check context.changed_document_ids before summarizing — skip summarization for documents with zero changed chunks in core/domain/pipeline/steps.py

### Tests for User Story 2

- [x] T013 [US2] Write OrphanCleanupStep tests (orphan deletion, removed document cleanup, empty document producing zero chunks, idempotent on empty sets) and DocumentSummaryStep tests (skip unchanged documents, summarize changed documents) in tests/core/domain/test_pipeline_steps.py

**Checkpoint**: US2 is independently testable — orphans are cleaned up and unchanged document summaries are preserved.

---

## Phase 5: Integration & Wiring

**Purpose**: Export new steps, wire pipeline composition in plugins, validate end-to-end

- [x] T014 Export ContentHashStep, ChangeDetectionStep, OrphanCleanupStep from core/domain/pipeline/__init__.py
- [x] T015 [P] Modify IngestSpacePlugin — remove delete_collection() call (line 74), wire ContentHashStep after ChunkStep, ChangeDetectionStep after ContentHashStep, OrphanCleanupStep after StoreStep, inject knowledge_store_port into new steps in plugins/ingest_space/plugin.py
- [x] T016 [P] Modify IngestWebsitePlugin — remove delete_collection() call (line 57), wire ContentHashStep after ChunkStep, ChangeDetectionStep after ContentHashStep, OrphanCleanupStep after StoreStep, inject knowledge_store_port into new steps in plugins/ingest_website/plugin.py
- [x] T017 Write integration tests — full pipeline: ingest corpus then re-ingest unchanged (verify >80% skip rate), ingest then re-ingest with changed content (verify orphan cleanup), ingest then remove document (verify chunk removal) in tests/core/domain/test_pipeline_steps.py

**Checkpoint**: Full pipeline works end-to-end with dedup and orphan cleanup. All existing tests pass (SC-004).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and final validation

- [x] T018 Write ADR for port extension (get/delete) and content-addressable storage scheme in docs/adr/0006-content-hash-dedup.md (required by constitution P8)
- [x] T019 Run quickstart.md validation — poetry run pytest, poetry run ruff check core/ plugins/ tests/, poetry run pyright core/ plugins/

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Skipped — project exists
- **Foundational (Phase 2)**: No dependencies — can start immediately. BLOCKS all user stories.
- **US1 (Phase 3)**: Depends on Phase 2 completion (T001 for port, T002 for content_hash, T003 for context fields, T005 for ContentHashStep)
- **US2 (Phase 4)**: Depends on Phase 3 completion (T008 for ChangeDetectionStep which populates orphan_ids and changed_document_ids)
- **Integration (Phase 5)**: Depends on Phase 4 completion (all steps must exist before plugin wiring)
- **Polish (Phase 6)**: Depends on Phase 5 completion

### Task-Level Dependencies

| Task | Depends On | Reason |
|---|---|---|
| T004 | T001 | Adapter implements port interface |
| T005 | T002 | ContentHashStep sets Chunk.content_hash field |
| T006 | T001 | Mock must match port protocol |
| T007 | T005 | Tests exercise ContentHashStep |
| T008 | T001, T003, T005 | Queries port, writes context fields, reads content hashes |
| T009 | T002 | Uses Chunk.content_hash for storage ID |
| T010 | T006, T008, T009 | Tests need mock port and step implementations |
| T011 | T008 | Reads context.orphan_ids populated by ChangeDetectionStep |
| T012 | T008 | Reads context.changed_document_ids populated by ChangeDetectionStep |
| T013 | T006, T011, T012 | Tests need mock port and step implementations |
| T014 | T005, T008, T011 | Exports require step classes to exist |
| T015, T016 | T014 | Plugins import from pipeline package |
| T017 | T015, T016 | Integration tests need full pipeline wiring |
| T018 | T017 | ADR documents final design decisions |
| T019 | T017 | Validation runs after all code is complete |

### Within Each User Story

- Implementation tasks before tests (tests validate implementation)
- Same-file tasks are sequential (steps.py modifications within a phase)
- Test tasks can run in parallel with tests from other phases if in different files

### Parallel Opportunities

**Phase 2 — Round 1** (all different files, no dependencies):
```
T001: core/ports/knowledge_store.py
T002: core/domain/ingest_pipeline.py
T003: core/domain/pipeline/engine.py
```

**Phase 2 — Round 2** (all different files, each depends only on Round 1):
```
T004: core/adapters/chromadb.py        (after T001)
T005: core/domain/pipeline/steps.py    (after T002)
T006: tests/conftest.py                (after T001)
```

**Phase 2 — Round 3**:
```
T007: tests/core/domain/test_content_hash.py (after T005)
```

**Phase 5 — Plugins** (different files):
```
T015: plugins/ingest_space/plugin.py   (after T014)
T016: plugins/ingest_website/plugin.py (after T014)
```

---

## Parallel Example: Phase 2 Foundational

```bash
# Round 1 — launch all three in parallel:
Task T001: "Add GetResult + get()/delete() to KnowledgeStorePort in core/ports/knowledge_store.py"
Task T002: "Add content_hash to Chunk, metrics to IngestResult in core/domain/ingest_pipeline.py"
Task T003: "Add dedup fields to PipelineContext, propagate metrics in core/domain/pipeline/engine.py"

# Round 2 — launch all three in parallel (after Round 1):
Task T004: "Implement get()/delete() in ChromaDBAdapter in core/adapters/chromadb.py"
Task T005: "Implement ContentHashStep in core/domain/pipeline/steps.py"
Task T006: "Extend MockKnowledgeStorePort in tests/conftest.py"

# Round 3:
Task T007: "Write content hash unit tests in tests/core/domain/test_content_hash.py"
```

---

## Implementation Strategy

### MVP First (Phase 2 + Phase 3: US1)

1. Complete Phase 2: Foundational — port, data model, ContentHashStep
2. Complete Phase 3: US1 — ChangeDetectionStep, StoreStep modification
3. **STOP and VALIDATE**: Run T010 tests — unchanged chunks are skipped, content-hash IDs work
4. This delivers SC-001 (>80% skip rate) and SC-002 (faster re-ingestion) without full plugin wiring

### Full Delivery (add Phase 4 + Phase 5)

5. Complete Phase 4: US2 — OrphanCleanupStep, DocumentSummaryStep modification
6. Complete Phase 5: Integration — plugin wiring, end-to-end tests
7. **VALIDATE**: Run full test suite — all SC criteria met, all existing tests pass (SC-004)
8. Complete Phase 6: Polish — ADR, final validation

### Key Risk: US2 depends on US1

Unlike typical story independence, US2 (orphan cleanup) structurally depends on US1 (change detection), because `ChangeDetectionStep` populates the `orphan_ids` that `OrphanCleanupStep` consumes. This is an inherent data flow dependency, not a design flaw — orphan identification IS change detection.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [US1]/[US2] labels map to spec.md user stories
- US3 and US4 are absorbed into Foundational phase (P2 enablers for P1 stories)
- EmbedStep requires NO code changes — its existing `if c.embedding is None` filter naturally skips chunks pre-loaded by ChangeDetectionStep
- `delete_collection()` is retained on the port for admin use but removed from plugin ingestion paths
- All new pipeline steps are async, consistent with existing step design
- Content hash uses SHA-256 (FR-001) with null-byte field separator per research.md R2
