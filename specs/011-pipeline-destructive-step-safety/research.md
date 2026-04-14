# Research: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Feature Branch**: `story/37-pipeline-engine-safety-destructive-step-handling`
**Date**: 2026-04-14

## Research Tasks

### R1: Protocol extension strategy for backward compatibility

**Context**: The `PipelineStep` protocol is `@runtime_checkable`. Adding a new required property `destructive` would break all existing steps that do not implement it. Need to choose a backward-compatible approach.

**Findings**:

Three options were evaluated:

1. **Add required `destructive` property to `PipelineStep` protocol**: Would force all existing step classes and test steps to add the property. Breaks backward compatibility.
2. **Define a separate `DestructiveStep` protocol**: Adds unnecessary complexity. Engine would need `isinstance` checks against a second protocol.
3. **Use `getattr(step, 'destructive', False)` in the engine**: Zero-disruption. Steps that want destructive gating add a `destructive` property. All others default to `False` automatically. Consistent with Python duck-typing conventions already used in this codebase (e.g., plugin contracts).

**Decision**: Use `getattr(step, 'destructive', False)` in `IngestEngine.run()`. The `PipelineStep` protocol remains unchanged.
**Rationale**: Least invasive. Zero changes to existing steps. Idiomatic Python duck typing.
**Alternatives considered**: (a) Required protocol property -- rejected (breaks backward compatibility). (b) Separate `DestructiveStep` protocol -- rejected (unnecessary complexity).

---

### R2: Replacing the string-matching guard in OrphanCleanupStep

**Context**: `OrphanCleanupStep.execute()` currently checks `any(e.startswith("StoreStep:") for e in context.errors)` to decide whether to skip cleanup. This guard is fragile: it depends on exact error message formatting and only matches errors from `StoreStep`.

**Findings**:

The existing guard has several problems:
1. Coupled to `StoreStep`'s error message prefix -- if message format changes, guard breaks silently.
2. Only protects against `StoreStep` errors -- errors from other steps (e.g., `EmbedStep`) would not trigger the guard.
3. Each new destructive step would need its own string-matching logic.

With engine-level gating (R1), `OrphanCleanupStep.execute()` can be simplified to only contain its cleanup logic. The engine handles all error-based skipping.

**Decision**: Remove the string-matching guard entirely. Add `destructive = True` property. Let the engine gate.
**Rationale**: Engine-level gating is more general (any error triggers skip), more robust (no string matching), and centralized (one check point).
**Alternatives considered**: (a) Keep guard as defense-in-depth -- rejected (redundant with engine gating, increases maintenance burden). (b) Change guard to check `len(context.errors) > 0` instead of string matching -- rejected (still step-level, engine-level is cleaner).

---

### R3: Metrics for skipped destructive steps

**Context**: When a destructive step is skipped, should `StepMetrics` be recorded?

**Findings**:

The `IngestEngine.run()` always records metrics in `context.metrics[step.name]` after executing a step. If skipped steps have no metrics entry, monitoring dashboards may show missing steps, causing confusion.

Recording `StepMetrics` with `duration=0.0` and `error_count=1` makes it unambiguous that the step was skipped (not just fast). The `items_in` and `items_out` values reflect the current state at the time of skipping.

**Decision**: Record `StepMetrics` for skipped steps with `duration=0.0`, current `items_in`/`items_out`, and `error_count=1`.
**Rationale**: Consistent metrics dict. Monitoring always shows all configured steps. `error_count=1` + `duration=0.0` is a clear signal of intentional skip.
**Alternatives considered**: (a) No metrics for skipped steps -- rejected (gaps in monitoring). (b) Metrics with `error_count=0` -- rejected (ambiguous, could look like a fast success).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Protocol extension | `getattr(step, 'destructive', False)` | Zero-disruption, idiomatic Python |
| String-matching guard | Remove entirely | Engine-level gating is more general and robust |
| Metrics for skipped steps | Record with `duration=0.0`, `error_count=1` | Consistent monitoring, clear skip signal |
| Log level for skipping | `logger.warning` | Safety mechanism activation, not routine |
| Mid-pipeline destructive steps | Non-destructive steps still run | Simplest predictable behavior |
