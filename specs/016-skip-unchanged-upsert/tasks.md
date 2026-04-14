# Tasks: Skip Upsert for Unchanged Chunks in StoreStep

**Input**: Design documents from `specs/016-skip-unchanged-upsert/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Single user story -- tasks grouped by implementation then tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: User Story 1 - Skip Unchanged Chunks (Priority: P1) MVP

**Goal**: StoreStep filters out unchanged chunks before upserting to ChromaDB, reducing redundant I/O on incremental ingests.

**Independent Test**: Ingest a knowledge base, re-ingest without changes, verify zero chunks stored. Change a subset, re-ingest, verify only changed chunks stored.

### Implementation for User Story 1

- [X] T001 [US1] Add unchanged-chunk filter to `StoreStep.execute()` in `core/domain/pipeline/steps.py`: extend the storable list comprehension to exclude chunks whose `content_hash` is in `context.unchanged_chunk_hashes`
- [X] T002 [US1] Separate the no-embedding skip count from unchanged skip count in `core/domain/pipeline/steps.py`: compute `no_embedding` count independently so the error message only reflects chunks genuinely lacking embeddings
- [X] T003 [US1] Add INFO log for unchanged chunks skipped in `core/domain/pipeline/steps.py`: log the count of unchanged chunks filtered out when greater than zero

**Checkpoint**: StoreStep correctly filters unchanged chunks and reports accurate metrics.

---

## Phase 2: Tests for User Story 1

**Purpose**: Verify skip-unchanged behavior with 4 distinct test scenarios.

- [X] T004 [P] [US1] Test that unchanged chunks are skipped: create `test_skips_unchanged_chunks` in `tests/core/domain/test_pipeline_steps.py` -- PipelineContext with `unchanged_chunk_hashes` containing a hash, chunk with matching `content_hash` and valid embedding, assert 0 chunks stored
- [X] T005 [P] [US1] Test that changed chunks are stored alongside unchanged: create `test_stores_changed_chunks_alongside_unchanged` in `tests/core/domain/test_pipeline_steps.py` -- mix of changed and unchanged chunks, assert only changed ones stored, `chunks_stored` equals changed count
- [X] T006 [P] [US1] Test that summary/BoK chunks are not filtered: create `test_unchanged_filter_does_not_affect_summary_chunks` in `tests/core/domain/test_pipeline_steps.py` -- summary chunk with `content_hash=None` alongside unchanged content chunk, assert summary chunk is stored
- [X] T007 [P] [US1] Test backward compatibility when unchanged_hashes is empty: create `test_no_filter_when_unchanged_hashes_empty` in `tests/core/domain/test_pipeline_steps.py` -- empty `unchanged_chunk_hashes`, assert all embedded chunks stored

**Checkpoint**: All 4 tests pass, confirming skip-unchanged behavior and backward compatibility.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Implementation)**: No dependencies -- start immediately
- **Phase 2 (Tests)**: Depends on Phase 1 completion (tests verify the implementation)

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories (single-story feature)

### Parallel Opportunities

**Phase 1**: T001, T002, T003 are sequential (same file, same function).
**Phase 2**: T004, T005, T006, T007 are all parallel (independent test methods in the same file, no data dependencies).

```text
T001-T003 (implementation) --> T004, T005, T006, T007 (tests, parallel)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: StoreStep filter implementation (T001-T003)
2. Complete Phase 2: Test coverage (T004-T007)
3. **STOP and VALIDATE**: Run `poetry run pytest tests/core/domain/test_pipeline_steps.py` to confirm all tests pass
4. Deploy -- unchanged chunks are no longer redundantly upserted
