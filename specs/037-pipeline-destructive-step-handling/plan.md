# Implementation Plan: Pipeline Engine Safety — Formalize Destructive Step Handling

**Spec**: [spec.md](spec.md)  
**Created**: 2026-04-08

## Summary

Add a first-class `destructive` property to the pipeline step contract and teach `IngestEngine.run()` to skip destructive steps when `context.errors` is non-empty. Remove the fragile string-matching guard from `OrphanCleanupStep`. This is a small, focused change touching two production files and their tests.

## Architecture

### Design Decision

Use **Approach 1** from the issue: extend the step contract with an optional `destructive` attribute. The engine checks `getattr(step, 'destructive', False)` before each step execution. If the step is destructive and `context.errors` is non-empty, the engine skips it, logs a WARNING, appends a skip message to errors, and records a zero-duration StepMetrics entry.

This is preferred over phase-based execution because:
- It requires no structural change to the engine's sequential execution model
- It is backward-compatible (existing steps without `destructive` default to `False`)
- It keeps gating logic centralized in the engine rather than distributed across steps

### Execution Flow Change

```
Before:
  for step in steps:
      execute(step)

After:
  for step in steps:
      if step.destructive and context.errors:
          skip(step)      # log WARNING, append skip message, record metrics
      else:
          execute(step)
```

## Affected Modules

| File | Change Type | Description |
|------|-------------|-------------|
| `core/domain/pipeline/engine.py` | MODIFIED | Add destructive-step gating logic to `IngestEngine.run()`. No change to `PipelineStep` protocol definition (backward compat via `getattr`). |
| `core/domain/pipeline/steps.py` | MODIFIED | Add `destructive = True` to `OrphanCleanupStep`. Remove string-matching guard from `OrphanCleanupStep.execute()`. |
| `tests/core/domain/test_pipeline_steps.py` | MODIFIED | Add tests for engine-level destructive gating. Update `OrphanCleanupStep` tests to remove/adjust string-matching guard assertions. |

## Data Model Deltas

None. No new fields on `PipelineContext`, `IngestResult`, or any Pydantic model. The `destructive` attribute is a plain class attribute on step classes, not stored or serialized.

## Interface Contracts

### PipelineStep Protocol (unchanged formally, extended informally)

The `PipelineStep` protocol definition in `engine.py` remains unchanged. The `destructive` attribute is accessed via `getattr(step, 'destructive', False)`. Steps that want to opt into destructive gating add `destructive = True` as a class attribute.

```python
# engine.py — protocol stays as-is
@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str: ...
    async def execute(self, context: PipelineContext) -> None: ...

# steps.py — opt-in
class OrphanCleanupStep:
    destructive = True
    ...
```

### IngestEngine.run() Contract Change

- **Before**: All steps execute unconditionally (errors are recorded but never cause skips).
- **After**: Steps where `getattr(step, 'destructive', False)` is `True` are skipped when `len(context.errors) > 0` at the time they are about to execute.
- **Skip behavior**: Appends `"{step.name}: skipped — destructive step gated by prior errors"` to `context.errors`. Records `StepMetrics(duration=0.0, ...)` with `error_count=1`. Logs at WARNING level.

## Test Strategy

### Unit Tests (new)

1. **Engine skips destructive step when errors exist**: Register a step that produces an error, then a destructive step. Assert destructive step's `execute()` is never called, skip message appears in errors, and metrics are recorded.
2. **Engine runs destructive step when no errors**: Same setup but no prior errors. Assert destructive step executes normally.
3. **Engine skips multiple destructive steps**: Multiple destructive steps after an error. All skipped.
4. **Non-destructive steps still run after errors**: Error step, then non-destructive step. Non-destructive step executes.
5. **Backward compatibility**: Step without `destructive` attribute runs normally regardless of errors.

### Unit Tests (modified)

1. **OrphanCleanupStep no longer self-gates**: Call `OrphanCleanupStep.execute()` directly with errors in context. Assert it proceeds (no skip). The old test asserting string-matching skip behavior is replaced.

### Integration Tests

1. **Full pipeline with StoreStep failure**: ChunkStep + EmbedStep + StoreStep(failing) + OrphanCleanupStep. Assert OrphanCleanupStep is skipped by the engine.

## Rollout Notes

- No configuration changes. No environment variable changes.
- No migration needed. Pure code change.
- Fully backward compatible: existing step classes without `destructive` are unaffected.
- Risk: Low. The change narrows behavior (fewer things can happen on error), not widens it.
