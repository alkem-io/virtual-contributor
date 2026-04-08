# Plan: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story**: #37  
**Status**: Draft  
**Date**: 2026-04-08  

---

## Architecture

The change is localized to the pipeline engine layer. No new modules, ports, adapters, or dependencies are introduced.

### Design

The `IngestEngine.run()` loop gains a pre-execution check: before calling `step.execute(context)`, it inspects `getattr(step, "destructive", False)`. If `True` and `context.errors` is non-empty, the step is skipped, a message is appended to `context.errors`, and `StepMetrics` are recorded with `error_count=1`.

`OrphanCleanupStep` gains a class-level `destructive = True` attribute and its `execute()` method loses the `any(e.startswith("StoreStep:") ...)` guard.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/engine.py` | Add destructive-step gating logic to `IngestEngine.run()`. Add docstring to `PipelineStep` protocol. |
| `core/domain/pipeline/steps.py` | Add `destructive = True` to `OrphanCleanupStep`. Remove string-matching guard from `execute()`. |
| `tests/core/domain/test_pipeline_steps.py` | Update `test_skips_cleanup_on_store_step_errors` to test via engine. Add new `TestDestructiveStepGating` class with engine-level tests. |

### Data Model Deltas

None. No changes to `PipelineContext`, `StepMetrics`, `IngestResult`, or any domain models.

### Interface Contracts

**PipelineStep protocol** -- no formal change to the protocol definition. The `destructive` attribute is opt-in via duck typing (checked with `getattr`).

**IngestEngine.run()** -- behavior change: destructive steps are now conditionally skipped. This is backward-compatible because:
- Steps without `destructive` attribute default to `False` (non-destructive).
- The skip behavior only activates when `context.errors` is non-empty.
- The IngestResult contract is unchanged.

### Test Strategy

1. **Unit tests (engine level)**: New `TestDestructiveStepGating` class with test doubles:
   - Destructive step skipped when errors exist
   - Destructive step runs when no errors exist
   - Non-destructive steps still run when errors exist
   - Multiple destructive steps -- all skipped when errors exist
   - Metrics recorded for skipped destructive steps
   - Steps without `destructive` attribute treated as non-destructive

2. **Unit tests (step level)**: Update `TestOrphanCleanupStep`:
   - `test_skips_cleanup_on_store_step_errors`: Rewrite to test via engine integration (errors from any step gate OrphanCleanupStep)
   - Verify `destructive` attribute is `True` on the class
   - Verify `execute()` no longer contains string-matching guard (tested indirectly: even non-StoreStep errors cause skip when routed through engine)

3. **Integration tests**: Existing `TestPipelineIntegration` tests continue to pass unchanged (they use full pipelines with OrphanCleanupStep).

### Rollout Notes

- Zero-downtime: No config changes, no migration, no wire-format changes.
- Backward-compatible: Existing pipelines work identically. Only behavior change is that OrphanCleanupStep skip is now engine-driven rather than self-driven.
- The string-matching guard removal means that if someone calls `OrphanCleanupStep.execute()` directly (outside the engine) with prior errors, cleanup will no longer be self-guarded. This is acceptable because the engine is the only execution path.
