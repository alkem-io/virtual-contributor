# Clarifications

**Iteration count:** 1

---

## Clarification 1: Protocol extension strategy for backward compatibility

**Question:** The `PipelineStep` protocol is `@runtime_checkable`. Adding a new required property `destructive` would break all existing steps that do not implement it. Should we (a) make it a required protocol member with a default in a base mixin, (b) make the engine use `getattr(step, 'destructive', False)`, or (c) define a separate `DestructiveStep` protocol?

**Chosen answer:** (b) Use `getattr(step, 'destructive', False)` in `IngestEngine.run()`. The `PipelineStep` protocol remains unchanged -- no new required member. Steps that want to declare themselves destructive simply add a `destructive` property returning `True`. This is the least invasive option and is consistent with Python duck-typing conventions already used in this codebase (e.g., plugin contracts).

**Rationale:** Adding a required property to the protocol would force all existing step classes (and any external/test steps) to add the property, violating backward compatibility. A separate protocol adds unnecessary complexity. Using `getattr` with a safe default is idiomatic Python and zero-disruption.

## Clarification 2: Error message format for skipped destructive steps

**Question:** When the engine skips a destructive step, what format should the error message use? The existing convention in `OrphanCleanupStep` uses `"OrphanCleanupStep: skipped cleanup because earlier storage writes failed"`. Should the engine-level message follow the same `{StepName}: ...` pattern?

**Chosen answer:** Yes. The engine-level message will use the format `"{step.name}: skipped (destructive step gated by prior errors)"`. This is consistent with how `IngestEngine.run()` already formats caught exception messages as `f"{step.name}: {exc}"`.

**Rationale:** Consistent error message format across the engine. Using `step.name` (the property) rather than the class name keeps messages aligned with what appears in metrics.

## Clarification 3: Should the engine log at WARNING or INFO level when skipping?

**Question:** The existing string-matching guard in `OrphanCleanupStep` does not log at all (only appends to `context.errors`). The engine's exception handler uses `logger.exception`. What log level for a gated destructive skip?

**Chosen answer:** `logger.warning`. It is not an exception (nothing crashed), but it is noteworthy enough that operators should see it. The skip is an intentional safety mechanism, not routine.

**Rationale:** `INFO` would be too quiet for a safety mechanism activation. `ERROR` would be misleading since the skip is desired behavior. `WARNING` is the correct semantic level.

## Clarification 4: Should metrics still be recorded for skipped destructive steps?

**Question:** When a destructive step is skipped by the engine gate, should `StepMetrics` still be recorded for it?

**Chosen answer:** Yes. Record a `StepMetrics` entry with `duration=0.0`, `items_in` and `items_out` at their current values, and `error_count=1` (the skip message counts as an error). This ensures the metrics dict always has entries for all steps in the pipeline, making monitoring consistent.

**Rationale:** Having metrics for all configured steps (even skipped ones) avoids confusion in monitoring dashboards. The `error_count=1` and `duration=0.0` make it unambiguous that the step was skipped, not just fast.

## Clarification 5: What if a step has both `destructive=True` and is not the last step?

**Question:** The issue only discusses `OrphanCleanupStep`, but the mechanism should be general. If a destructive step is positioned in the middle of the pipeline, should subsequent non-destructive steps still run?

**Chosen answer:** Yes. The `destructive` flag only gates the specific step that declares it. Non-destructive steps always run regardless of where destructive steps appear. The engine iterates all steps in order and only checks the destructive flag per-step.

**Rationale:** This is the simplest and most predictable behavior. If operators want to prevent all downstream execution, they should use the error-propagation mechanism (exceptions caught by the engine) rather than relying on the destructive flag.
