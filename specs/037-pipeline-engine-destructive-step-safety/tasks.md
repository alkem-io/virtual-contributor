# Tasks: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story**: #37  
**Status**: Draft  
**Date**: 2026-04-08  

---

## Task List

### T1: Add destructive-step gating to IngestEngine.run()

**File**: `core/domain/pipeline/engine.py`  
**Depends on**: None  
**Acceptance criteria**:
- Before calling `step.execute(context)`, engine checks `getattr(step, "destructive", False)`.
- If `True` and `len(context.errors) > 0`, the step is skipped.
- A skip message is appended to `context.errors` in format: `"{step.name}: skipped (destructive step gated by {N} prior error(s))"`.
- A WARNING-level log is emitted.
- `StepMetrics` are recorded with `duration=0.0`, `items_in`/`items_out` = current chunk count, `error_count=1`.
- Steps without `destructive` attribute or with `destructive=False` execute normally regardless of errors.
**Tests**: T4

### T2: Add docstring to PipelineStep protocol

**File**: `core/domain/pipeline/engine.py`  
**Depends on**: T1  
**Acceptance criteria**:
- `PipelineStep` protocol class has a docstring explaining the optional `destructive` attribute.
- Docstring explains engine gating behavior.
**Tests**: None (documentation only)

### T3: Update OrphanCleanupStep to use engine-level gating

**File**: `core/domain/pipeline/steps.py`  
**Depends on**: T1  
**Acceptance criteria**:
- `OrphanCleanupStep` has `destructive = True` as a class-level attribute (not a property).
- The `any(e.startswith("StoreStep:") ...)` guard is removed from `execute()`.
- The "skipped cleanup because earlier storage writes failed" error append is removed from `execute()`.
- `execute()` runs its cleanup logic unconditionally (engine handles gating).
**Tests**: T5

### T4: Add engine-level destructive step gating tests

**File**: `tests/core/domain/test_pipeline_steps.py`  
**Depends on**: T1  
**Acceptance criteria**:
- New `TestDestructiveStepGating` class with the following tests:
  - `test_destructive_step_skipped_when_errors_exist`: Destructive step does not execute when context has errors.
  - `test_destructive_step_runs_when_no_errors`: Destructive step executes normally when no errors.
  - `test_non_destructive_steps_run_despite_errors`: Steps without `destructive` attribute still execute when errors exist.
  - `test_skip_message_format`: Skip message matches expected format and is appended to errors.
  - `test_metrics_recorded_for_skipped_step`: Skipped destructive step has metrics with error_count=1 and duration~0.
  - `test_multiple_destructive_steps_all_skipped`: Multiple destructive steps in a pipeline are all skipped when errors exist.
  - `test_destructive_false_treated_as_non_destructive`: Steps with explicit `destructive = False` still run.
**Tests**: Self (these are the tests)

### T5: Update OrphanCleanupStep tests for engine-level gating

**File**: `tests/core/domain/test_pipeline_steps.py`  
**Depends on**: T3  
**Acceptance criteria**:
- `test_skips_cleanup_on_store_step_errors` is rewritten to test via `IngestEngine`: a pipeline with a failing step before `OrphanCleanupStep` results in OrphanCleanupStep being skipped.
- New test `test_orphan_cleanup_has_destructive_attribute`: Verifies `OrphanCleanupStep.destructive is True`.
- New test `test_orphan_cleanup_runs_when_no_errors_via_engine`: OrphanCleanupStep runs normally in a clean pipeline.
- Existing direct-call tests (`test_orphan_deletion`, `test_removed_document_cleanup`, `test_idempotent_on_empty_sets`) are unchanged.
**Tests**: Self (these are the tests)

---

## Dependency Order

```
T1 (engine gating) --> T2 (docstring)
T1 (engine gating) --> T3 (OrphanCleanupStep update) --> T5 (OrphanCleanupStep tests)
T1 (engine gating) --> T4 (engine gating tests)
```

T4 and T3 can execute in parallel after T1.
T2 can execute any time after T1.
T5 executes after T3.

## Execution Order

1. T1 -- Engine gating logic
2. T2 -- Protocol docstring (parallel with T3, T4)
3. T3 -- OrphanCleanupStep update (parallel with T2, T4)
4. T4 -- Engine gating tests (parallel with T2, T3)
5. T5 -- OrphanCleanupStep test updates (after T3)
