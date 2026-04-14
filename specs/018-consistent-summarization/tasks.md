# Tasks: Consistent Summarization Behavior Between Ingest Plugins

**Input**: Design documents from `specs/018-consistent-summarization/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Config Fields)

**Purpose**: Config field and validation that MUST be in place before user story work begins.

- [X] T001 [US1] Add `summarize_enabled: bool = True` field to `BaseConfig` in core/config.py
- [X] T002 [US2] Add validation that `summarize_concurrency >= 0` with clear error message in core/config.py

**Checkpoint**: Config field and validation in place.

---

## Phase 2: User Story 1 -- Explicit Summarization Toggle (Priority: P1) MVP

**Goal**: Both ingest plugins honor `summarize_enabled` to include or skip summarization steps.

**Independent Test**: Set `SUMMARIZE_ENABLED=false`, run both plugins, verify no summary steps. Set `SUMMARIZE_ENABLED=true`, verify summary steps included.

### Implementation for User Story 1

- [X] T003 [P] [US1] Update IngestWebsitePlugin constructor in plugins/ingest_website/plugin.py to accept `summarize_enabled: bool = True` and `summarize_concurrency: int = 8`, store as instance attributes
- [X] T004 [P] [US1] Update IngestSpacePlugin constructor in plugins/ingest_space/plugin.py to accept `summarize_enabled: bool = True` and `summarize_concurrency: int = 8`, store as instance attributes
- [X] T005 [US1] Modify IngestWebsitePlugin.handle() in plugins/ingest_website/plugin.py to conditionally include DocumentSummaryStep and BodyOfKnowledgeSummaryStep based on `self._summarize_enabled`
- [X] T006 [US1] Modify IngestSpacePlugin.handle() in plugins/ingest_space/plugin.py to conditionally include DocumentSummaryStep and BodyOfKnowledgeSummaryStep based on `self._summarize_enabled`
- [X] T007 [US1] Wire `summarize_enabled` injection in main.py: inject `config.summarize_enabled` into plugin deps when `summarize_enabled` is in constructor signature

**Checkpoint**: Both plugins honor `summarize_enabled`. Summarization can be explicitly disabled.

---

## Phase 3: User Story 2 -- Concurrency Zero Means Sequential (Priority: P2)

**Goal**: `summarize_concurrency=0` maps to effective concurrency=1 in both plugins.

**Independent Test**: Set `SUMMARIZE_CONCURRENCY=0` with summarization enabled. Verify both plugins use concurrency=1 for DocumentSummaryStep.

### Implementation for User Story 2

- [X] T008 [P] [US2] In IngestWebsitePlugin constructor (plugins/ingest_website/plugin.py), store `self._summarize_concurrency = max(1, summarize_concurrency)` to map 0 to 1
- [X] T009 [P] [US2] In IngestSpacePlugin constructor (plugins/ingest_space/plugin.py), store `self._summarize_concurrency = max(1, summarize_concurrency)` to map 0 to 1
- [X] T010 [US2] Wire `summarize_concurrency` injection in main.py: inject `config.summarize_concurrency` into plugin deps when `summarize_concurrency` is in constructor signature
- [X] T011 [US2] Pass `self._summarize_concurrency` to DocumentSummaryStep concurrency parameter in both plugins

**Checkpoint**: Concurrency=0 runs sequentially in both plugins. Negative concurrency rejected at config.

---

## Phase 4: User Story 3 -- Remove Inline Config (Priority: P3)

**Goal**: IngestWebsitePlugin no longer instantiates BaseConfig() inside handle().

**Independent Test**: Verify no `from core.config import BaseConfig` in IngestWebsitePlugin.handle().

### Implementation for User Story 3

- [X] T012 [US3] Remove `from core.config import BaseConfig` and `config = BaseConfig()` from IngestWebsitePlugin.handle() in plugins/ingest_website/plugin.py
- [X] T013 [US3] Replace `config.summarize_concurrency` references with `self._summarize_concurrency` in IngestWebsitePlugin.handle()

**Checkpoint**: IngestWebsitePlugin uses only constructor-injected config, matching the hexagonal pattern.

---

## Phase 5: Tests

**Purpose**: Validate all scenarios for both plugins and config validation.

- [X] T014 [P] Add tests in tests/core/test_config_validation.py: `summarize_concurrency=-1` raises ValidationError, `summarize_concurrency=0` is valid, `summarize_enabled` defaults to True, `summarize_enabled=False` is accepted
- [X] T015 [P] Add `TestIngestWebsiteSummarizationBehavior` class in tests/plugins/test_ingest_website.py with three tests: enabled+concurrent, enabled+zero-concurrency, disabled
- [X] T016 [P] Add `TestIngestSpaceSummarizationBehavior` class in tests/plugins/test_ingest_space.py with three tests: enabled+concurrent, enabled+zero-concurrency, disabled
- [X] T017 Update existing `test_pipeline_composition` in tests/plugins/test_ingest_website.py to remove dependency on `summarize_concurrency=0` as a disable mechanism

**Checkpoint**: All scenarios tested. All existing tests pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies -- start immediately
- **User Story 1 (Phase 2)**: Depends on Phase 1 T001 (summarize_enabled config field)
- **User Story 2 (Phase 3)**: Depends on Phase 1 T002 (concurrency validation)
- **User Story 3 (Phase 4)**: Depends on Phase 2 and Phase 3 (constructor params in place before removing inline config)
- **Tests (Phase 5)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends only on Foundational phase
- **User Story 2 (P2)**: Depends only on Foundational phase. Can run in parallel with US1
- **User Story 3 (P3)**: Depends on US1 + US2 (constructor params must exist before removing inline config)

### Parallel Opportunities

**Phase 1**: T001, T002 sequential (same file).
**Phase 2**: T003, T004 parallel (different plugin files). T005, T006 parallel (different plugin files). T007 after T003-T006.
**Phase 3**: T008, T009 parallel (different plugin files). T010 after T008/T009. T011 parallel with T010.
**Phase 4**: T012, T013 sequential (same file).
**Phase 5**: T014, T015, T016 parallel (different files). T017 after T012/T013.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Config field + validation
2. Complete Phase 2: Explicit summarization toggle
3. **STOP and VALIDATE**: Both plugins honor summarize_enabled
4. Deploy -- summarization behavior is now consistent

### Incremental Delivery

1. Phase 1 -> Foundation in place
2. Add US1 -> Test independently -> Deploy (explicit toggle, MVP!)
3. Add US2 -> Test independently -> Deploy (concurrency=0 means sequential)
4. Add US3 -> Test independently -> Deploy (inline config removed)
5. Phase 5 -> Full test coverage
