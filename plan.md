# Plan: Pipeline Engine Safety — Formalize Destructive Step Handling

**Story:** alkem-io/virtual-contributor#37
**Date:** 2026-04-08

---

## Architecture

The change is contained within the pipeline engine domain layer. No ports, adapters, plugins, events, or config changes are needed.

### Design

The engine gains awareness of destructive steps via duck-typing. Before executing each step, `IngestEngine.run()` checks `getattr(step, "destructive", False)`. If `True` and `context.errors` is non-empty, the step is skipped with a structured message appended to errors and metrics recorded with zero duration.

This replaces the current self-guarding pattern where `OrphanCleanupStep` inspects `context.errors` for `"StoreStep:"` prefixes.

```
Before:  Step self-guards → fragile string matching → only OrphanCleanupStep protected
After:   Engine guards → duck-typed `destructive` flag → all destructive steps protected
```

## Affected Modules

| File | Change |
|------|--------|
| `core/domain/pipeline/engine.py` | Add destructive-step skip logic to `IngestEngine.run()`. No Protocol change needed (duck-typed). |
| `core/domain/pipeline/steps.py` | `OrphanCleanupStep`: add `destructive` property returning `True`; remove string-matching guard from `execute()`. |
| `tests/core/domain/test_pipeline_steps.py` | Update `test_skips_cleanup_on_store_step_errors` to test via engine (not direct step call). Add new engine-level tests for destructive step handling. |

## Data Model Deltas

None. `PipelineContext`, `StepMetrics`, `IngestResult` are unchanged.

## Interface Contracts

### PipelineStep Protocol (unchanged formally, extended by convention)

```python
@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str: ...
    async def execute(self, context: PipelineContext) -> None: ...
    # Optional duck-typed extension:
    # @property
    # def destructive(self) -> bool: ...  (default False if absent)
```

Steps that wish to be skipped on errors define `destructive = True` (or a `@property` returning `True`). Steps that do not define it are assumed non-destructive.

### IngestEngine.run() behavior change

```
for step in self._steps:
    if getattr(step, "destructive", False) and context.errors:
        # Skip, log, record metrics with skip message
        continue
    # ... existing execution logic
```

## Test Strategy

| Test | What it proves |
|------|---------------|
| `test_engine_skips_destructive_step_on_errors` | Engine skips steps with `destructive=True` when `context.errors` is non-empty |
| `test_engine_runs_destructive_step_without_errors` | Engine runs destructive steps normally when no errors exist |
| `test_engine_runs_non_destructive_step_despite_errors` | Non-destructive steps still execute even with errors |
| `test_engine_treats_missing_destructive_as_false` | Steps without `destructive` property are treated as non-destructive |
| `test_skipped_destructive_step_records_metrics` | Metrics entry exists for skipped steps with zero duration |
| `test_skips_cleanup_on_store_step_errors` (updated) | OrphanCleanupStep is skipped via engine when prior errors exist (replaces string-matching test) |
| `test_orphan_cleanup_destructive_property` | `OrphanCleanupStep.destructive` returns `True` |

## Rollout Notes

- Zero-downtime change. No config, env var, or deployment changes needed.
- Backward compatible: existing steps without `destructive` property continue working identically.
- Plugin wiring in `ingest_website` and `ingest_space` requires no changes.
