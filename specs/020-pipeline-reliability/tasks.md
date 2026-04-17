# Tasks: Pipeline Reliability and BoK Resilience

**Input**: Design documents from `specs/020-pipeline-reliability/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by fix area.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Thread Pool Deadlock Prevention (US1)

**Purpose**: Eliminate the primary deadlock vector: zombie thread accumulation from timeout retries.

- [X] T001 [US1] Add explicit `asyncio.TimeoutError` catch in `LangChainLLMAdapter.invoke()` in core/adapters/langchain_llm.py that raises `TimeoutError` immediately without retry. Place it before the generic `except Exception` clause so timeouts are never retried.
- [X] T002 [US1] Add `import concurrent.futures` and set `loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=32))` in `main()` in main.py, before `loop.run_until_complete(_run(config))`.

**Checkpoint**: LLM timeout produces exactly 1 zombie thread (not 3). Thread pool has 32 workers for concurrent pipeline workloads.

---

## Phase 2: Background Task Safety (US1)

**Purpose**: Prevent orphaned background tasks in DocumentSummaryStep.

- [X] T003 [US1] Replace `assert` statements in `DocumentSummaryStep.execute()` in core/domain/pipeline/steps.py with graceful error handling: append to `context.errors` when `result.summary is None or result.chunk is None` instead of raising `AssertionError`.
- [X] T004 [US1] Wrap the result-processing loop and task creation in `DocumentSummaryStep.execute()` in a `try` block, and add a `finally` block that calls `asyncio.gather(*embed_tasks, return_exceptions=True)` to ensure all background tasks are always awaited.

**Checkpoint**: Background embedding tasks are always awaited. No assert-based crashes in the result loop.

---

## Phase 3: Partial Summary Resilience (US2)

**Purpose**: Make refine-pattern summarization resilient to mid-stream LLM failures.

- [X] T005 [US2] Add `try/except Exception` around the LLM call in `_refine_summarize()` in core/domain/pipeline/steps.py. When the exception is caught and a partial summary exists from prior rounds, return the partial summary with a `logger.warning`. When no partial summary exists (round 1 failure), re-raise.
- [X] T006 [US2] Add `logger.debug` per refinement round in `_refine_summarize()`: "Refine round {i+1}/{total} complete ({len} chars)".

**Checkpoint**: Mid-stream failure returns partial summary. First-round failure raises. Debug logging traces progress.

---

## Phase 4: BoK Section Grouping and Inline Persistence (US2, US3)

**Purpose**: Reduce BoK refinement rounds via section grouping, persist BoK inline, and skip unchanged BoK regeneration.

- [X] T007 [US2] Add `max_section_chars: int = 30000` constructor parameter to `BodyOfKnowledgeSummaryStep` in core/domain/pipeline/steps.py. Enforce minimum of 1000 via `max(1000, max_section_chars)`.
- [X] T008 [US2] Implement section grouping logic in `BodyOfKnowledgeSummaryStep.execute()`: iterate sections, accumulate into groups until `max_section_chars` is exceeded, join with `"\n\n---\n\n"`. Only apply when `len(sections) > 1`. Log the grouping: "Grouped {N} sections into {M} refinement rounds (max_section_chars={limit})".
- [X] T009 [P] [US2] Add `knowledge_store_port: KnowledgeStorePort | None = None` and `embeddings_port: EmbeddingsPort | None = None` constructor parameters to `BodyOfKnowledgeSummaryStep`.
- [X] T010 [US2] Implement inline BoK persistence in `BodyOfKnowledgeSummaryStep.execute()`: after generating the BoK summary, when both ports are available, embed the summary, store it with the correct metadata and storage ID `"body-of-knowledge-summary-0"`, increment `context.chunks_stored`, and log success. Wrap in `try/except` that logs a warning and defers to the finalize path on failure.
- [X] T011 [US3] Add `_bok_exists()` method to `BodyOfKnowledgeSummaryStep`: query the store for `{"embeddingType": "body-of-knowledge"}` entries, return `True` if any exist, `False` if no store or on error.
- [X] T012 [US3] Add skip condition at the top of `BodyOfKnowledgeSummaryStep.execute()`: when `change_detection_ran` is True, `changed_document_ids` is empty, `removed_document_ids` is empty, and `_bok_exists()` returns True, return immediately.

**Checkpoint**: Section grouping reduces refinement rounds. BoK persisted inline. Unchanged corpus with existing BoK is skipped.

---

## Phase 5: StoreStep Dedup and ChangeDetection Fix

**Purpose**: Fix edge cases in chunk storage and change detection.

- [X] T013 [P] Add batch-level deduplication in `StoreStep.execute()` in core/domain/pipeline/steps.py: build `seen_ids: dict[str, int]` mapping storage ID to last index. When duplicates exist (`len(seen_ids) < len(ids)`), rebuild batch arrays from unique indices sorted in order.
- [X] T014 [P] Fix embeddings check in `ChangeDetectionStep._detect()` in core/domain/pipeline/steps.py: change `if existing.embeddings` to `if existing.embeddings is not None and len(existing.embeddings) > 0`.

**Checkpoint**: No duplicate storage ID errors. Empty embeddings list handled correctly.

---

## Phase 6: Plugin Wiring (US2)

**Purpose**: Both ingest plugins pass the required ports to BodyOfKnowledgeSummaryStep for inline persistence and skip behavior.

- [X] T015 [P] [US2] Update `IngestWebsitePlugin.handle()` in plugins/ingest_website/plugin.py to pass `knowledge_store_port=self._knowledge_store` and `embeddings_port=self._embeddings` to `BodyOfKnowledgeSummaryStep`.
- [X] T016 [P] [US2] Update `IngestSpacePlugin.handle()` in plugins/ingest_space/plugin.py to pass `knowledge_store_port=self._knowledge_store` and `embeddings_port=self._embeddings` to `BodyOfKnowledgeSummaryStep`.

**Checkpoint**: Both plugins enable BoK inline persist and skip-on-unchanged.

---

## Phase 7: Tests (US1, US2, US3, Edge)

**Purpose**: Validate reliability and resilience behaviors with unit tests.

- [X] T017 [US3] Update the BoK skip test (`test_skips_when_nothing_changed`) in tests/core/domain/test_pipeline_steps.py to pre-populate `MockKnowledgeStorePort` with an existing BoK entry (via `store.ingest()`) and pass `knowledge_store_port=store` to `BodyOfKnowledgeSummaryStep`. Assert that no LLM calls are made and no BoK chunk is appended.
- [X] T018 [P1] [US1] Verify LLM adapter raises immediately on timeout without retry — `tests/core/adapters/test_langchain_llm.py` (existing test covers this).
- [X] T019 [P1] [US1] Verify DocumentSummaryStep background tasks are always awaited via try/finally — `tests/core/domain/test_pipeline_steps.py` (existing test).
- [X] T020 [P2] [US2] Verify `_refine_summarize` returns partial summary when mid-stream round fails — `tests/core/domain/test_pipeline_steps.py` (existing test).
- [X] T021 [P2] [US2] Verify BoK section grouping reduces refinement rounds for large section counts — `tests/core/domain/test_pipeline_steps.py` (existing test).
- [X] T022 [P2] [US2] Verify BoK inline embed+store persists immediately when ports provided — `tests/core/domain/test_pipeline_steps.py` (existing test).
- [X] T023 [--] [Edge] Verify StoreStep deduplicates by storage ID within a batch — `tests/core/domain/test_pipeline_steps.py` (existing test).

**Checkpoint**: Test validates that BoK skip requires both "no changes" AND "BoK exists in store". Tests cover timeout behavior, task safety, partial summary resilience, section grouping, inline persistence, and batch deduplication.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Thread Pool)**: No dependencies -- start immediately
- **Phase 2 (Task Safety)**: No dependencies -- can run in parallel with Phase 1
- **Phase 3 (Partial Summary)**: No dependencies -- can run in parallel with Phases 1-2
- **Phase 4 (BoK Enhancements)**: T008 depends on T007. T010 depends on T009. T012 depends on T011.
- **Phase 5 (StoreStep/ChangeDetection)**: No dependencies -- can run in parallel with any phase
- **Phase 6 (Plugin Wiring)**: Depends on T009 (BoKStep constructor params exist)
- **Phase 7 (Tests)**: Depends on T011-T012 (BoKStep skip behavior in place)

### Parallel Opportunities

**Phase 1**: T001, T002 parallel (different files).
**Phase 2**: T003, T004 sequential (same method, T003 removes asserts before T004 wraps in try/finally).
**Phase 3**: T005, T006 sequential (same function).
**Phase 4**: T007-T008 sequential (same class). T009 parallel with T007/T008. T010 after T009. T011-T012 sequential.
**Phase 5**: T013, T014 parallel (different classes).
**Phase 6**: T015, T016 parallel (different files).
**Phase 7**: T017 after Phase 4.

---

## Implementation Strategy

### Fix Severity Order

1. **Phase 1** (Thread pool deadlock) -- Highest impact: eliminates service-wide deadlock
2. **Phase 2** (Task safety) -- High impact: prevents resource leaks across pipelines
3. **Phase 3** (Partial summary) -- Medium impact: preserves expensive LLM work
4. **Phase 4** (BoK enhancements) -- Medium impact: reduces BoK cost and adds resilience
5. **Phase 5** (Edge case fixes) -- Low impact: correctness fixes for rare conditions
6. **Phase 6** (Plugin wiring) -- Required for Phase 4 to take effect in production
7. **Phase 7** (Tests) -- Validates Phase 4 behavior
