# Task List: Pipeline Engine Safety — Formalize Destructive Step Handling

**Spec**: [spec.md](spec.md)  
**Plan**: [plan.md](plan.md)  
**Created**: 2026-04-08

## Tasks

### Phase 1: Engine-Level Destructive Step Gating

- [x] T001 [US1, US2] Add destructive-step gating logic to `IngestEngine.run()` in `core/domain/pipeline/engine.py`: before executing each step, check `getattr(step, 'destructive', False)` and if `True` and `context.errors` is non-empty, skip execution, append `"{step.name}: skipped — destructive step gated by prior errors"` to `context.errors`, log at WARNING level, and record `StepMetrics(duration=0.0, items_in=len(context.chunks), items_out=len(context.chunks), error_count=1)`.
  - **Acceptance**: Engine skips destructive steps when errors exist; non-destructive steps still execute regardless of errors.
  - **Tests**: T004, T005, T006, T007, T008

- [x] T002 [US2, US3] Add `destructive = True` class attribute to `OrphanCleanupStep` in `core/domain/pipeline/steps.py`.
  - **Acceptance**: `getattr(OrphanCleanupStep(...), 'destructive', False)` returns `True`.
  - **Tests**: T009

- [x] T003 [US3] Remove the string-matching guard (`if any(e.startswith("StoreStep:") for e in context.errors)`) and its associated error append from `OrphanCleanupStep.execute()` in `core/domain/pipeline/steps.py`.
  - **Acceptance**: `OrphanCleanupStep.execute()` no longer inspects `context.errors`. When called directly with errors in context, it proceeds with cleanup.
  - **Tests**: T010

### Phase 2: Tests

- [x] T004 [US1] Write test `test_engine_skips_destructive_step_when_errors_exist` in `tests/core/domain/test_pipeline_steps.py`: create a pipeline with an error-producing step followed by a destructive step; assert the destructive step's execute is never called, skip message is in errors, and StepMetrics is recorded with duration=0.
  - **Acceptance**: Test passes. Destructive step not executed.

- [x] T005 [US1] Write test `test_engine_runs_destructive_step_when_no_errors` in `tests/core/domain/test_pipeline_steps.py`: create a pipeline with a clean step followed by a destructive step; assert the destructive step executes normally.
  - **Acceptance**: Test passes. Destructive step executed.

- [x] T006 [US1] Write test `test_engine_skips_multiple_destructive_steps` in `tests/core/domain/test_pipeline_steps.py`: create a pipeline with an error step followed by two destructive steps; assert both are skipped.
  - **Acceptance**: Test passes. Both destructive steps skipped.

- [x] T007 [US1] Write test `test_non_destructive_steps_run_after_errors` in `tests/core/domain/test_pipeline_steps.py`: create a pipeline with an error step followed by a non-destructive step; assert the non-destructive step executes.
  - **Acceptance**: Test passes. Non-destructive step runs despite prior errors.

- [x] T008 [US2] Write test `test_backward_compat_step_without_destructive_runs` in `tests/core/domain/test_pipeline_steps.py`: create a step class without a `destructive` attribute; assert it runs normally in the engine regardless of prior errors.
  - **Acceptance**: Test passes. Step without `destructive` is treated as non-destructive.

- [x] T009 [US2] Write test `test_orphan_cleanup_step_has_destructive_true` in `tests/core/domain/test_pipeline_steps.py`: assert `OrphanCleanupStep` has `destructive == True`.
  - **Acceptance**: Test passes.

- [x] T010 [US3] Update existing `OrphanCleanupStep` tests in `tests/core/domain/test_pipeline_steps.py`: remove/replace assertions that test the old string-matching guard behavior. Add test `test_orphan_cleanup_no_self_gating` that calls `execute()` directly with errors in context and asserts cleanup proceeds.
  - **Acceptance**: Old guard-related tests updated. New test passes.

- [x] T011 [US1] Write integration test `test_full_pipeline_destructive_gating` in `tests/core/domain/test_pipeline_steps.py`: compose a full pipeline with ChunkStep, EmbedStep, a failing StoreStep, and OrphanCleanupStep. Assert OrphanCleanupStep is skipped by the engine.
  - **Acceptance**: Test passes. Engine-level gating works end-to-end.

## Dependency Order

```
T001 (engine gating) — no dependencies
T002 (destructive attribute) — no dependencies
T003 (remove guard) — no dependencies
T004..T011 (tests) — depend on T001, T002, T003
```

T001, T002, T003 are independent and can be implemented in any order or in parallel. All test tasks depend on the production code changes being complete.

## Checklist

- [ ] All tests pass (`poetry run pytest`)
- [ ] Lint clean (`poetry run ruff check core/ plugins/ tests/`)
- [ ] Type check clean (`poetry run pyright core/ plugins/`)
- [ ] No new dependencies added
