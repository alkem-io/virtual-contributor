# ADR 0010: Pipeline Destructive Step Safety

## Status
Accepted

## Context
Pipeline steps like `OrphanCleanupStep` perform destructive operations (deleting chunks from the vector store). When earlier steps fail — leaving the pipeline in a partially-processed state — executing destructive steps risks data loss. The original safeguard relied on fragile string matching against error messages (`startswith("StoreStep:")`), which was brittle and did not generalize.

## Decision
Introduce an **engine-level destructive step gate** using duck-typed property detection:

1. **`destructive` property**: Steps that perform irreversible operations declare `destructive = True` as a class attribute. The engine checks `getattr(step, 'destructive', False)` before execution.
2. **Automatic skip on prior errors**: When `context.has_errors` is `True`, any step with `destructive=True` is automatically skipped by the engine. Non-destructive steps continue executing.
3. **Protocol preservation**: The `PipelineStep` protocol is unchanged — `destructive` is an opt-in attribute detected at runtime via duck typing, maintaining backward compatibility with all existing steps.
4. **Skip metrics**: Skipped destructive steps record `StepMetrics` with `duration=0.0` and `error_count=1` for monitoring visibility.

## Consequences
- **Positive**: Destructive operations are never executed when the pipeline is in an error state — prevents data loss from partial processing.
- **Positive**: No breaking changes to existing steps — only steps that opt in to `destructive=True` are affected.
- **Positive**: Replaces fragile string-based error matching with explicit, property-based gating.
- **Negative**: Duck-typed detection is invisible at the type level — a step author must know to set `destructive=True` (no compiler enforcement).
