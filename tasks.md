# Tasks: Pipeline Engine Safety — Formalize Destructive Step Handling

**Story:** alkem-io/virtual-contributor#37
**Date:** 2026-04-08

---

## Task List (dependency-ordered)

### T1: Add destructive-step skip logic to IngestEngine.run()

**File:** `core/domain/pipeline/engine.py`

**Changes:**
- In the `for step in self._steps:` loop, before executing the step, check `getattr(step, "destructive", False)`.
- If `True` and `context.errors` is non-empty:
  - Append `"{step.name}: skipped (destructive step cannot run when pipeline has errors)"` to `context.errors`.
  - Log a warning.
  - Record `StepMetrics` with `duration=0.0`, `items_in` and `items_out` matching current chunk count, `error_count=1`.
  - `continue` to skip execution.

**Acceptance criteria:**
- Destructive steps are skipped when `context.errors` is non-empty.
- Non-destructive steps and steps without `destructive` property are unaffected.
- Metrics are recorded for skipped steps.

**Tests:** T4 (test_engine_skips_destructive_step_on_errors, test_engine_runs_destructive_step_without_errors, test_engine_runs_non_destructive_step_despite_errors, test_engine_treats_missing_destructive_as_false, test_skipped_destructive_step_records_metrics)

---

### T2: Add `destructive` property to OrphanCleanupStep and remove string-matching guard

**File:** `core/domain/pipeline/steps.py`

**Depends on:** T1

**Changes:**
- Add `@property` `destructive` returning `True` to `OrphanCleanupStep`.
- Remove the `if any(e.startswith("StoreStep:") for e in context.errors):` guard block from `OrphanCleanupStep.execute()`.

**Acceptance criteria:**
- `OrphanCleanupStep().destructive` returns `True`.
- `OrphanCleanupStep.execute()` no longer contains any string-matching error inspection.
- Existing orphan cleanup behavior (deletion of orphan IDs and removed documents) is preserved.

**Tests:** T4 (test_orphan_cleanup_destructive_property), existing orphan_cleanup tests (test_orphan_deletion, test_removed_document_cleanup, test_idempotent_on_empty_sets)

---

### T3: Update existing test for string-matching guard

**File:** `tests/core/domain/test_pipeline_steps.py`

**Depends on:** T1, T2

**Changes:**
- Update `test_skips_cleanup_on_store_step_errors` to test via `IngestEngine` instead of direct `OrphanCleanupStep.execute()` call with pre-populated errors.
- The test should: create an engine with a failing non-destructive step followed by a destructive step, run the engine, and verify the destructive step was skipped.

**Acceptance criteria:**
- The updated test proves that engine-level skip works for destructive steps when prior steps produced errors.
- No string-matching on "StoreStep:" in any test.

**Tests:** Self (the updated test itself)

---

### T4: Add new engine-level tests for destructive step handling

**File:** `tests/core/domain/test_pipeline_steps.py`

**Depends on:** T1, T2

**Changes:**
Add the following tests to a new `TestDestructiveStepHandling` class:
1. `test_engine_skips_destructive_step_on_errors` — Engine with a pre-errored context skips destructive steps.
2. `test_engine_runs_destructive_step_without_errors` — Engine runs destructive steps when no errors exist.
3. `test_engine_runs_non_destructive_step_despite_errors` — Non-destructive steps execute even with errors.
4. `test_engine_treats_missing_destructive_as_false` — Steps without `destructive` are non-destructive.
5. `test_skipped_destructive_step_records_metrics` — Metrics entry for skipped step has zero duration and error_count=1.
6. `test_orphan_cleanup_destructive_property` — `OrphanCleanupStep.destructive` is `True`.

**Acceptance criteria:**
- All six tests pass.
- Tests use mock/recording steps, not real pipeline steps (except the property test).

**Tests:** Self

---

### T5: Run exit gates (test, lint, typecheck)

**Depends on:** T1, T2, T3, T4

**Changes:** None (validation only).

**Acceptance criteria:**
- `poetry run pytest` passes all tests.
- `poetry run ruff check core/ plugins/ tests/` reports no issues.
- `poetry run pyright core/ plugins/` reports no errors.
