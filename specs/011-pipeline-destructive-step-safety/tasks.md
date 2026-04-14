# Tasks: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Input**: Design documents from `specs/011-pipeline-destructive-step-safety/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: User Story 1 -- Engine-Level Destructive Step Gating (Priority: P1) MVP

**Goal**: Add engine-level gating that automatically skips destructive steps when prior errors exist.

**Independent Test**: Run `IngestEngine` with an error-producing step followed by a destructive step. Verify the destructive step is not executed, a skip message is in errors, and metrics have `duration=0.0`.

### Implementation for User Story 1

- [X] T001 [US1] Add destructive-step gating logic in `IngestEngine.run()` in core/domain/pipeline/engine.py: before calling `step.execute(context)`, check `getattr(step, 'destructive', False)`; if True and `context.errors` is non-empty, skip with warning log, append skip message, record `StepMetrics` with `duration=0.0` and `error_count=1`
- [X] T002 [P] [US1] Add test `test_engine_skips_destructive_step_with_prior_errors` in tests/core/domain/test_pipeline_steps.py: verify destructive step is not executed when errors exist, skip message appears in errors
- [X] T003 [P] [US1] Add test `test_engine_runs_destructive_step_with_no_errors` in tests/core/domain/test_pipeline_steps.py: verify destructive step runs when no errors
- [X] T004 [P] [US1] Add test `test_non_destructive_steps_run_despite_errors` in tests/core/domain/test_pipeline_steps.py: verify non-destructive steps execute regardless of errors
- [X] T005 [P] [US1] Add test `test_multiple_destructive_steps_all_skipped` in tests/core/domain/test_pipeline_steps.py: verify all destructive steps skipped when errors exist
- [X] T006 [P] [US1] Add test `test_destructive_step_skipped_after_failing_non_destructive` in tests/core/domain/test_pipeline_steps.py: verify destructive skipped after exception-raising step
- [X] T007 [P] [US1] Add test `test_metrics_recorded_for_skipped_destructive_step` in tests/core/domain/test_pipeline_steps.py: verify `StepMetrics` has `duration=0.0` and `error_count=1`
- [X] T008 [P] [US1] Add test `test_skip_message_format` in tests/core/domain/test_pipeline_steps.py: verify exact skip message format includes step name and error count

**Checkpoint**: Engine-level destructive gating is fully functional and tested independently.

---

## Phase 2: User Story 2 -- OrphanCleanupStep Destructive Declaration (Priority: P2)

**Goal**: Mark `OrphanCleanupStep` as destructive and remove the fragile string-matching guard.

**Independent Test**: Instantiate `OrphanCleanupStep` and assert `step.destructive is True`. Run engine with failing store step followed by orphan cleanup and verify orphan data is preserved.

### Implementation for User Story 2

- [X] T009 [US2] Add `@property destructive` returning `True` to `OrphanCleanupStep` in core/domain/pipeline/steps.py
- [X] T010 [US2] Remove the `if any(e.startswith("StoreStep:") ...)` string-matching guard and associated error append + return from `OrphanCleanupStep.execute()` in core/domain/pipeline/steps.py
- [X] T011 [P] [US2] Add test `test_destructive_property` in tests/core/domain/test_pipeline_steps.py: assert `OrphanCleanupStep(...).destructive is True`
- [X] T012 [US2] Update test `test_skips_cleanup_on_store_step_errors` in tests/core/domain/test_pipeline_steps.py: rewrite to use `IngestEngine` with `FailingStoreStep` followed by `OrphanCleanupStep`, verify orphan is NOT deleted and skip message contains "destructive step gated"

**Checkpoint**: OrphanCleanupStep is protected by engine-level gating. String-matching guard fully removed.

---

## Phase 3: Polish & Cross-Cutting Concerns

- [X] T013 Verify all gates pass: `poetry run pytest` (all green), `poetry run ruff check core/ plugins/ tests/` (no lint errors), `poetry run pyright core/ plugins/` (no type errors)

---

## Dependencies & Execution Order

### Phase Dependencies

- **User Story 1 (Phase 1)**: No dependencies -- start immediately
- **User Story 2 (Phase 2)**: Depends on Phase 1 T001 (engine must gate before step-level guard is removed)
- **Polish (Phase 3)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent -- engine-level gating with no prerequisite changes
- **User Story 2 (P2)**: Depends on US1 T001 (engine gating must exist before removing the old guard)

### Parallel Opportunities

**Phase 1**: T001 is sequential (engine code). T002-T008 are parallel (all test file, separate test classes).
**Phase 2**: T009 and T010 are sequential (same file, same class). T011 and T012 parallel with each other but depend on T009/T010.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Engine-level gating in `engine.py`
2. Complete Phase 1 tests: 7 new tests validating gating behavior
3. **STOP and VALIDATE**: Engine-level gating works with any step that declares `destructive = True`
4. Deploy -- pipeline is intrinsically safer

### Incremental Delivery

1. Phase 1 -> Engine-level gating (MVP!)
2. Add US2 -> OrphanCleanupStep migrated to engine gating -> Deploy
3. Phase 3 -> Final validation
