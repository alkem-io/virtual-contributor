# Tasks: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story:** #37
**Plan:** `plan.md`

---

## Task 1: Add destructive-step gating to IngestEngine.run()

**File:** `core/domain/pipeline/engine.py`
**Depends on:** None
**AC:**
- Before calling `step.execute(context)`, the engine checks `getattr(step, 'destructive', False)`.
- If `True` and `len(context.errors) > 0`, the step is skipped.
- A warning log is emitted: `"Skipping destructive step '%s' due to %d prior error(s)"`.
- An error is appended to `context.errors`: `"{step.name}: skipped (destructive step gated by {N} prior error(s))"`.
- `StepMetrics` is recorded for the skipped step with `duration=0.0`, current `items_in`/`items_out`, and `error_count=1`.
- Non-destructive steps are completely unaffected (existing behavior preserved).

**Tests:** T1a-T1e (Task 3)

## Task 2: Mark OrphanCleanupStep as destructive and remove string-matching guard

**File:** `core/domain/pipeline/steps.py`
**Depends on:** Task 1 (the engine must gate before we remove the step-level guard)
**AC:**
- `OrphanCleanupStep` gains a `@property` `destructive` returning `True`.
- The lines `if any(e.startswith("StoreStep:") for e in context.errors): ...` (and the associated error append + return) are removed from `OrphanCleanupStep.execute()`.
- `OrphanCleanupStep.execute()` now executes its cleanup logic unconditionally (the engine handles gating).

**Tests:** T2a (Task 3)

## Task 3: Add and update tests

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** Tasks 1 and 2
**AC:**

**New tests (TestDestructiveStepGating class):**
- **T1a:** Engine skips a destructive step when `context.errors` is non-empty. Verify step's `execute()` is not called, skip message is in errors, and metrics have `duration=0.0`, `error_count=1`.
- **T1b:** Engine runs a destructive step when `context.errors` is empty. Verify step's `execute()` is called.
- **T1c:** Non-destructive steps run even when errors exist. Verify `execute()` is called for non-destructive steps regardless of error state.
- **T1d:** Multiple destructive steps: all are skipped when errors exist.
- **T1e:** Destructive step after a failing non-destructive step: verify the destructive step is skipped due to the error introduced by the prior step's failure.

**New test in TestOrphanCleanupStep:**
- **T2a:** `OrphanCleanupStep(...).destructive is True`.

**Updated test:**
- **T3a:** `test_skips_cleanup_on_store_step_errors` is rewritten to use `IngestEngine` with a `FailingStoreStep` followed by `OrphanCleanupStep`. Verifies the orphan is NOT deleted and a skip message is in the result errors.

## Task 4: Verify all gates pass

**Depends on:** Tasks 1-3
**AC:**
- `poetry run pytest` passes (all tests green).
- `poetry run ruff check core/ plugins/ tests/` passes (no lint errors).
- `poetry run pyright core/ plugins/` passes (no type errors).
