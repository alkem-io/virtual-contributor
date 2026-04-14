# Tasks: Summary Lifecycle Management

**Input**: Design documents from `specs/013-summary-lifecycle-management/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: User Story 1 -- Stale Per-Document Summary Cleanup (Priority: P1) MVP

**Goal**: When a changed document drops below the chunk threshold, mark its old summary for cleanup via `context.orphan_ids`.

**Independent Test**: Ingest a document with >= 4 chunks, re-ingest with < 4 chunks, verify the old summary entry is deleted.

### Implementation for User Story 1

- [X] T001 [US1] Add stale-summary detection loop in `DocumentSummaryStep.execute()` in core/domain/pipeline/steps.py: after building `docs_to_summarize`, iterate over `chunks_by_doc` to find changed documents below `chunk_threshold`; for each, add `f"{doc_id}-summary-0"` to `context.orphan_ids` and log at INFO level. Guard with `context.change_detection_ran`.

### Tests for User Story 1

- [X] T002 [P] [US1] Add `test_stale_summary_marked_as_orphan` in tests/core/domain/test_pipeline_steps.py: context with `change_detection_ran=True`, doc in `changed_document_ids`, 2 chunks (below threshold 4). Assert `"doc-1-summary-0"` in `context.orphan_ids`, no summary chunks generated, no LLM calls.
- [X] T003 [P] [US1] Add `test_no_orphan_when_still_above_threshold` in tests/core/domain/test_pipeline_steps.py: changed doc with >= 4 chunks. Assert orphan_ids does not contain summary ID, summary chunk generated.
- [X] T004 [P] [US1] Add `test_no_stale_cleanup_without_change_detection` in tests/core/domain/test_pipeline_steps.py: `change_detection_ran=False`, doc below threshold. Assert `orphan_ids` is empty.
- [X] T005 [P] [US1] Add `test_stale_cleanup_only_targets_changed_docs` in tests/core/domain/test_pipeline_steps.py: unchanged doc below threshold (not in `changed_document_ids`). Assert summary ID not in `orphan_ids`.

**Checkpoint**: Stale per-document summary cleanup is fully functional and tested.

---

## Phase 2: User Story 2 -- Empty Corpus BoK Summary Cleanup (Priority: P2)

**Goal**: When all documents are removed (empty corpus with removals), mark the BoK summary for cleanup via `context.orphan_ids`.

**Independent Test**: Ingest a space with documents, remove all, re-ingest, verify BoK summary entry is deleted.

### Implementation for User Story 2

- [X] T006 [US2] Modify `BodyOfKnowledgeSummaryStep.execute()` in core/domain/pipeline/steps.py: replace bare `if not seen_doc_ids: return` with orphan-marking logic that checks `context.removed_document_ids`; if removals exist and corpus is empty, add `"body-of-knowledge-summary-0"` to `context.orphan_ids` and log at INFO level before returning.

### Tests for User Story 2

- [X] T007 [P] [US2] Add `test_bok_summary_orphaned_on_empty_corpus` in tests/core/domain/test_pipeline_steps.py: empty chunks, `removed_document_ids={"doc-1", "doc-2"}`, `change_detection_ran=True`. Assert `"body-of-knowledge-summary-0"` in `context.orphan_ids`, no BoK chunk generated, no LLM calls.
- [X] T008 [P] [US2] Add `test_bok_summary_not_orphaned_when_docs_exist` in tests/core/domain/test_pipeline_steps.py: non-empty chunks with content. Assert BoK summary ID not in `orphan_ids`, BoK summary chunk generated.
- [X] T009 [P] [US2] Add `test_bok_not_orphaned_on_empty_corpus_without_removals` in tests/core/domain/test_pipeline_steps.py: empty chunks, no removals, `change_detection_ran=False`. Assert BoK summary ID not in `orphan_ids`.

**Checkpoint**: Empty corpus BoK cleanup is fully functional and tested.

---

## Phase 3: Validation

- [X] T010 Run full test suite (`poetry run pytest`) and verify all tests pass including new ones.

---

## Dependencies & Execution Order

### Phase Dependencies

- **User Story 1 (Phase 1)**: No dependencies -- start immediately
- **User Story 2 (Phase 2)**: No dependencies on Phase 1 (different step, different file section)
- **Validation (Phase 3)**: Depends on Phases 1 and 2

### User Story Dependencies

- **User Story 1 (P1)**: Independent -- can start after branch creation
- **User Story 2 (P2)**: Independent -- can start in parallel with US1

### Parallel Opportunities

**Phase 1**: T001 sequential (implementation). T002, T003, T004, T005 parallel (different test classes/methods, same file but no dependencies).
**Phase 2**: T006 sequential (implementation). T007, T008, T009 parallel (different test methods).
**Cross-phase**: Phase 1 and Phase 2 can run in parallel (different steps in steps.py, different test classes).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Stale per-document summary cleanup + tests
2. **STOP and VALIDATE**: Run tests for User Story 1 independently
3. Deploy -- stale document summaries are cleaned up on re-ingest

### Incremental Delivery

1. Phase 1 -> Test independently -> Stale summaries cleaned up (MVP!)
2. Add Phase 2 -> Test independently -> BoK summary cleaned up on empty corpus
3. Phase 3 -> Full validation pass
