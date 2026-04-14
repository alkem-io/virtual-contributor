# Plan: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story:** #37
**Spec:** `spec.md`

---

## Architecture

The change is localized to two files in `core/domain/pipeline/` and their corresponding test file. No new modules, no new dependencies, no configuration changes.

**Before:**
```
IngestEngine.run() -> for step in steps: step.execute(context)
OrphanCleanupStep.execute() -> manual string check: any(e.startswith("StoreStep:") ...)
```

**After:**
```
IngestEngine.run() -> for step in steps:
    if getattr(step, 'destructive', False) and context.errors:
        skip + log + record metrics
    else:
        step.execute(context)
OrphanCleanupStep -> destructive = True (property); execute() has NO guard
```

## Affected Modules

| File | Change Type | Description |
|------|-------------|-------------|
| `core/domain/pipeline/engine.py` | Modify | Add destructive-step gating logic in `IngestEngine.run()` |
| `core/domain/pipeline/steps.py` | Modify | Add `destructive` property to `OrphanCleanupStep`; remove string-matching guard |
| `tests/core/domain/test_pipeline_steps.py` | Modify | Update `test_skips_cleanup_on_store_step_errors` to test engine-level gating; add new engine-level tests |

## Data Model Deltas

None. `PipelineContext`, `StepMetrics`, `IngestResult` are unchanged. The `PipelineStep` protocol is not modified (we use `getattr` duck-typing).

## Interface Contracts

### PipelineStep Protocol (unchanged)
```python
@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str: ...
    async def execute(self, context: PipelineContext) -> None: ...
```

### Destructive Step Convention (new, opt-in)
Steps that want engine-level error gating declare:
```python
@property
def destructive(self) -> bool:
    return True
```

The engine checks `getattr(step, 'destructive', False)`. Steps without this property default to `False` (non-destructive).

### IngestEngine.run() Contract Change
When `getattr(step, 'destructive', False)` is `True` and `len(context.errors) > 0`:
- Step is NOT executed
- A warning is logged: `"Skipping destructive step '%s' due to %d prior error(s)"`
- An error is appended: `"{step.name}: skipped (destructive step gated by {N} prior error(s))"`
- Metrics are recorded with `duration=0.0` and `error_count=1`

## Test Strategy

1. **Unit: Engine destructive gating** -- New test class `TestDestructiveStepGating` in test_pipeline_steps.py:
   - Test engine skips destructive step when context has errors
   - Test engine runs destructive step when context has no errors
   - Test non-destructive steps still run even when errors exist
   - Test metrics recorded for skipped destructive steps
   - Test skip message format in context.errors

2. **Unit: OrphanCleanupStep.destructive property** -- New test in `TestOrphanCleanupStep`:
   - `assert OrphanCleanupStep(...).destructive is True`

3. **Update: test_skips_cleanup_on_store_step_errors** -- Change from testing step-level string guard to testing engine-level gating (run through IngestEngine with a failing StoreStep followed by OrphanCleanupStep).

4. **Regression: all existing tests** -- Must pass without changes to non-destructive steps.

## Rollout Notes

- Zero-config change. No environment variables, no feature flags.
- Backward compatible. Existing pipeline step implementations continue to work without modification.
- The behavior change is strictly safer: destructive steps are now gated by any prior error, not just errors matching a specific string pattern.
