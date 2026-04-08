# Clarifications

**Story**: #37  
**Iteration**: 1  

---

## Resolved Ambiguities

### C1: How should the optional `destructive` property work with the Protocol?

**Question**: Python `Protocol` classes require all declared members to be present for `isinstance()` checks. If we add `destructive` to `PipelineStep`, existing steps (and test doubles) without it will fail `isinstance(step, PipelineStep)`.

**Chosen Answer**: Do NOT add `destructive` to the `PipelineStep` protocol definition. Instead, use `getattr(step, "destructive", False)` in `IngestEngine.run()` to check for the property at runtime. This keeps the protocol backward-compatible. Steps that want to be destructive add `destructive = True` as a class attribute.

**Rationale**: The codebase already uses `@runtime_checkable` Protocol with duck typing. Adding an optional attribute to the protocol would break the contract. Using `getattr` with a default is the standard Python duck-typing pattern and is consistent with how the codebase handles optional attributes elsewhere (e.g., `getattr(getattr(llm_port, "_llm", None), "model", "unknown")` in DocumentSummaryStep).

### C2: Should the skip message be appended as an error or handled differently?

**Question**: When a destructive step is skipped, should the skip notification be appended to `context.errors` (making `IngestResult.success=False`) or tracked separately?

**Chosen Answer**: Append to `context.errors`. The skip itself is a consequence of earlier errors, and the pipeline already has errors. The message serves as an audit trail explaining why cleanup did not happen. Since `success` is already `False` due to the triggering errors, this does not change the result status.

**Rationale**: Keeping it in `context.errors` is consistent with how OrphanCleanupStep currently records its skip message. It also ensures operators see the skip in the standard error report without needing a separate field.

### C3: What format should the skip message use?

**Question**: What prefix/format should the engine-level skip message follow?

**Chosen Answer**: Use the format `"{step.name}: skipped (destructive step gated by {N} prior error(s))"` where N is `len(context.errors)`. This follows the existing convention of `"{StepName}: description"` prefixes used throughout steps.py.

**Rationale**: Consistent with existing error message format (`StoreStep: storage failed...`, `EmbedStep: embedding failed...`). Including the error count gives operators actionable context.

### C4: Should `StepMetrics` be recorded for skipped destructive steps?

**Question**: When a destructive step is skipped, should the engine still record `StepMetrics` for it?

**Chosen Answer**: Yes. Record `StepMetrics` with `duration=0.0`, `items_in` and `items_out` equal to the current chunk count, and `error_count=1` (the skip message). This ensures metrics remain complete for monitoring/debugging.

**Rationale**: The engine currently records metrics for every step, including those that raise exceptions. Skipped steps should be equally visible in the metrics dict.

### C5: Should the `destructive` property also be exposed as a Protocol documentation or only engine behavior?

**Question**: Should we document the `destructive` concept in the PipelineStep Protocol docstring even though it is not a protocol member?

**Chosen Answer**: Yes. Add a docstring note to the `PipelineStep` Protocol class explaining that steps can optionally declare `destructive = True` as a class attribute, and that the engine will gate them on prior errors.

**Rationale**: Protocol documentation is the natural place for pipeline authors to learn about available step behaviors. Without this documentation, the feature is invisible to future contributors.

---

## Iteration Summary

- 5 ambiguities identified and resolved.
- No remaining unknowns.
