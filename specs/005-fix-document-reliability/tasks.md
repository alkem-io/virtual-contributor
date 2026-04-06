# Tasks: Document Processing Reliability & Alignment

**Input**: Design documents from `/specs/005-fix-document-reliability/`
**Prerequisites**: plan.md, spec.md

**Tests**: Test updates included in Phase 5 (chunk ID alignment), Phase 8 (retrieval alignment), and Phase 9 (LLM adapter test fixes).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Configuration)

**Purpose**: Add configuration fields needed by multiple stories

- [x] T001 [P] Add `rabbitmq_heartbeat: int = 300` and `rabbitmq_max_retries: int = 3` fields to `BaseConfig` in core/config.py
- [x] T002 [P] Pass `heartbeat` and `max_retries` config values from `BaseConfig` to `RabbitMQAdapter` constructor in main.py

**Checkpoint**: Configuration plumbing ready — adapter and pipeline changes can proceed

---

## Phase 2: User Story 1 - Stable Document Ingestion Under Load (Priority: P1)

**Goal**: Prevent RabbitMQ connection drops during long-running LLM calls by offloading blocking work to threads and adding message retry logic.

**Independent Test**: Ingest 15+ documents without heartbeat timeout errors in logs.

### Implementation for User Story 1

- [x] T003 [US1] Add `_sync_invoke()` method to `LangChainLLMAdapter` and change `invoke()` to use `asyncio.to_thread(self._sync_invoke, ...)` wrapped in `asyncio.wait_for()` in core/adapters/langchain_llm.py
- [x] T004 [US1] Add `heartbeat` and `max_retries` constructor parameters to `RabbitMQAdapter`, include heartbeat in AMQP URL, enable `tcp_keepalive=True` on `connect_robust()` in core/adapters/rabbitmq.py
- [x] T005 [US1] Implement message retry logic in `on_message()` callback — use `requeue=False`, track `x-retry-count` header, republish failed messages up to `max_retries`, discard with error log after exhaustion in core/adapters/rabbitmq.py
- [x] T006 [P] [US1] Add `max_retries=3` to LLM client kwargs in core/provider_factory.py

**Checkpoint**: US1 complete — RabbitMQ connections survive long LLM calls; failed messages retry up to 3 times

---

## Phase 3: User Story 2 - High-Quality Summarization (Priority: P1)

**Goal**: Align summarization prompts and budget with the original repo for higher-quality, entity-preserving summaries.

**Independent Test**: Ingest a document with 10+ entity-rich chunks and verify summary quality.

### Implementation for User Story 2

- [x] T007 [US2] Rewrite `DOCUMENT_REFINE_SYSTEM`, `DOCUMENT_REFINE_INITIAL`, `DOCUMENT_REFINE_SUBSEQUENT` prompts with structured FORMAT/REQUIREMENTS/FORBIDDEN sections in core/domain/pipeline/prompts.py
- [x] T008 [US2] Rewrite `BOK_OVERVIEW_SYSTEM`, `BOK_OVERVIEW_INITIAL`, `BOK_OVERVIEW_SUBSEQUENT` prompts with structured FORMAT/REQUIREMENTS/FORBIDDEN sections in core/domain/pipeline/prompts.py
- [x] T009 [US2] Change `summary_length` default from 2000 to 10000 in `DocumentSummaryStep.__init__()` in core/domain/pipeline/steps.py
- [x] T010 [US2] Change `summary_length` default from 2000 to 10000 in `BodyOfKnowledgeSummaryStep.__init__()` in core/domain/pipeline/steps.py
- [x] T011 [US2] Replace `asyncio.gather` + `Semaphore` concurrent summarization with sequential `for` loop in `DocumentSummaryStep.execute()`, add per-document logging in core/domain/pipeline/steps.py

**Checkpoint**: US2 complete — summaries use original repo prompts, 10000-char budget, and sequential processing

---

## Phase 4: User Story 3 - Correct Chunk ID Format (Priority: P2)

**Goal**: Align ChromaDB chunk IDs with the original repo's `{doc_id}-chunk{index}` format.

**Independent Test**: Ingest a document and verify ChromaDB entry IDs match expected format.

### Implementation for User Story 3

- [x] T012 [US3] Refactor `StoreStep.execute()` to compute `storage_id` as `{document_id}-chunk{chunk_index}` for raw chunks and plain `document_id` for summary/BoK chunks; use `storage_id` in both metadata `documentId` and entry ID in core/domain/pipeline/steps.py
- [x] T013 [US3] Update `TestStoreStep` assertions to expect new ID format (`"my-doc-chunk0-0"` and `"my-doc-chunk0"`) in tests/core/domain/test_pipeline_steps.py

**Checkpoint**: US3 complete — ChromaDB IDs match original repo format

---

## Phase 5: User Story 4 - Source Attribution, Filtering, and Deduplication (Priority: P2)

**Goal**: Restore `[source:N]` prefix formatting (Issue #7), add score-threshold filtering (Issue #8), and deduplicate sources in both plugins.

**Independent Test**: Query both plugins. Verify `[source:N]` in LLM prompts, low-score chunks excluded, no duplicate source URLs in response.

### Implementation for User Story 4

- [x] T014 [US4] Add `retrieval_n_results: int = 5` and `retrieval_score_threshold: float = 0.3` config fields to `BaseConfig` in core/config.py
- [x] T015 [US4] Add `score_threshold` keyword-only constructor param (default 0.3) to `GuidancePlugin` in plugins/guidance/plugin.py
- [x] T016 [US4] Add score-threshold filtering (exclude pairs where `score < threshold`) before deduplication in plugins/guidance/plugin.py
- [x] T017 [US4] Add `[source:N]` prefix formatting at context assembly (`f"[source:{i}] {doc}"`) in plugins/guidance/plugin.py
- [x] T018 [P] [US4] Add `n_results` and `score_threshold` keyword-only constructor params (defaults 5, 0.3) to `ExpertPlugin` in plugins/expert/plugin.py
- [x] T019 [US4] Implement `_filter_and_format()` module-level helper: filter by score threshold, prefix with `[source:N]`, return filtered `QueryResult` in plugins/expert/plugin.py
- [x] T020 [US4] Apply `_filter_and_format()` in both `retrieve_node` (graph path) and `_handle_simple()` in plugins/expert/plugin.py
- [x] T021 [US4] Add source deduplication by source URL in `_build_sources()` using `seen` dict (matching original `{doc["source"]: doc}.values()`) in plugins/expert/plugin.py
- [x] T022 [US4] Add config injection in main.py: introspect plugin `__init__` signature, inject `n_results` and `score_threshold` from config for plugins that accept them

**Checkpoint**: US4 complete — both plugins have `[source:N]` prefixes, score filtering, and source deduplication

---

## Phase 6: User Story 5 - Reduced Expert Retrieval Count (Priority: P2)

**Goal**: Reduce expert `n_results` from 10 to 5 (configurable) to stay within context window limits (Issue #9).

**Independent Test**: Query expert plugin, verify it requests 5 results from ChromaDB.

### Implementation for User Story 5

- [x] T023 [US5] Change `n_results=10` to `self._n_results` in both `retrieve_node` and `_handle_simple()` in plugins/expert/plugin.py (covered by T018+T020)

**Checkpoint**: US5 complete — expert retrieves 5 results (configurable)

---

## Phase 7: User Story 6 - Configurable Summarization Pipeline (Priority: P3)

**Goal**: Allow operators to disable summarization by setting `summarize_concurrency=0`.

**Independent Test**: Set `summarize_concurrency=0` and verify only chunk/embed/store steps execute.

### Implementation for User Story 6

- [x] T024 [US6] Conditionally include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in the ingest pipeline based on `config.summarize_concurrency > 0` in plugins/ingest_website/plugin.py

**Checkpoint**: US6 complete — summarization steps skippable via configuration

---

## Phase 8: Test Updates for Retrieval Alignment

**Purpose**: Add and update tests for Issues #7, #8, #9

- [x] T025 [P] Add `test_source_prefix_formatting` and `test_low_score_chunks_filtered_out` tests for guidance plugin in tests/plugins/test_guidance.py
- [x] T026 [P] Add `test_source_prefix_formatting`, `test_low_score_chunks_filtered_out` tests and update `test_knowledge_retrieval` to assert `n_results=5` in tests/plugins/test_expert.py
- [x] T027 [P] Update LLM adapter tests from `AsyncMock().ainvoke` to `MagicMock().invoke` to match `asyncio.to_thread` execution model in tests/core/test_langchain_llm.py

**Checkpoint**: All 216 tests pass

---

## Phase 9: Spec Documentation

**Purpose**: Create and update specification artifacts for this feature

- [x] T028 [P] Update `summary_length` defaults from 2000 to 10000 in specs/004-pipeline-engine-redesign/spec.md (FR-007)
- [x] T029 [P] Update `summary_length` defaults from 2000 to 10000 in specs/004-pipeline-engine-redesign/contracts/pipeline-api.md
- [x] T030 [P] Update `summary_length` defaults and chunk ID format documentation in specs/004-pipeline-engine-redesign/data-model.md
- [x] T031 Update spec.md, plan.md, tasks.md to reflect Issues #7, #8, #9 implementation

**Checkpoint**: All specification artifacts consistent with implemented changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — configuration changes first
- **Phase 2 (US1)**: Depends on Phase 1 (config fields needed by adapter)
- **Phase 3 (US2)**: Independent of Phase 2 (different files)
- **Phase 4 (US3)**: Independent of Phases 2-3 (different code area in steps.py)
- **Phase 5 (US4)**: Depends on Phase 1 (config fields for retrieval_n_results, retrieval_score_threshold)
- **Phase 6 (US5)**: Covered by Phase 5 tasks (shared n_results param)
- **Phase 7 (US6)**: Independent of all other phases (ingest_website plugin only)
- **Phase 8 (Tests)**: Depends on Phases 5-6 (tests verify new behavior)
- **Phase 9 (Specs)**: Depends on all implementation phases

### Parallel Opportunities

- T001 and T002 can run in parallel (different files)
- T006 can run in parallel with T003-T005 (different file)
- T007 and T008 can run together (same file, additive)
- Phases 3, 4, 5, 6, and 7 can all run in parallel (different files)
- T025, T026, T027 can all run in parallel (different test files)
- T028, T029, T030 can all run in parallel (different spec files)

---

## Implementation Strategy

All tasks are marked complete — implemented across two work sessions:

**Session 1** (4 commits):
1. `b713b57` — Prompt rewrite, summary length increase, chunk ID alignment (US2, US3)
2. `5d62429` — Further prompt/summary/ID refinements (US2, US3)
3. `88914df` — Thread-based LLM execution, RabbitMQ heartbeat/retry, guidance dedup (US1, US4 partial)
4. `64fc551` — Final async robustness fixes (US1)

**Session 2** (Issues #7, #8, #9 — pending commit):
5. `[source:N]` prefix formatting in both plugins (US4, Issue #7)
6. Score-threshold filtering with configurable `RETRIEVAL_SCORE_THRESHOLD` (US4, Issue #8)
7. Expert n_results reduced to 5 with configurable `RETRIEVAL_N_RESULTS` (US5, Issue #9)
8. Expert source deduplication by source URL (US4)
9. LLM adapter test fixes for `asyncio.to_thread` mocking
10. Spec artifacts updated for all changes
