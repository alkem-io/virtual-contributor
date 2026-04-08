# Feature Specification: Pipeline Engine Safety — Formalize Destructive Step Handling

**Feature Branch**: `story/37-pipeline-engine-destructive-step-handling`  
**Created**: 2026-04-08  
**Status**: Draft  
**GitHub Issue**: [alkem-io/virtual-contributor#37](https://github.com/alkem-io/virtual-contributor/issues/37)  
**Parent Epic**: [alkem-io/alkemio#1820](https://github.com/alkem-io/alkemio/issues/1820)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Engine-Level Destructive Step Gating (Priority: P1)

As a pipeline author, I want the ingest engine to automatically skip destructive steps (e.g., orphan cleanup) when earlier write steps have recorded errors, so that partial write failures never cause data loss through premature cleanup.

**Why this priority**: This is a correctness and data safety issue. Destructive steps executing after partial write failures can delete chunks that were not successfully re-stored, causing irreversible data loss.

**Independent Test**: Configure a pipeline with a write step that fails partially and a destructive step after it. Verify the engine skips the destructive step and logs a warning.

**Acceptance Scenarios**:

1. **Given** a pipeline with steps [ChunkStep, EmbedStep, StoreStep, OrphanCleanupStep], **When** StoreStep records a partial batch failure error in `context.errors`, **Then** the engine skips OrphanCleanupStep without executing it, records a skip message in `context.errors`, and logs the skip at WARNING level.
2. **Given** a pipeline with steps [ChunkStep, EmbedStep, StoreStep, OrphanCleanupStep], **When** all steps before OrphanCleanupStep succeed with zero errors, **Then** OrphanCleanupStep executes normally.
3. **Given** a pipeline with multiple destructive steps, **When** any prior step has recorded errors, **Then** all destructive steps are skipped.
4. **Given** a pipeline with no destructive steps, **When** any step records errors, **Then** the pipeline continues executing all remaining non-destructive steps as before (no behavior change).

---

### User Story 2 - Step Protocol Extension with `destructive` Property (Priority: P1)

As a step implementor, I want to declare my step as destructive via a `destructive` property on the `PipelineStep` protocol, so that the engine can identify which steps need error-gating without fragile string-matching heuristics.

**Why this priority**: The protocol extension is the mechanism that enables US1. Without it, the engine cannot distinguish destructive from non-destructive steps.

**Independent Test**: Create a step class with `destructive = True` and verify it satisfies the `PipelineStep` protocol. Verify existing steps without a `destructive` property default to `False`.

**Acceptance Scenarios**:

1. **Given** a step class that defines `name`, `execute()`, and `destructive = True`, **Then** it satisfies `isinstance(step, PipelineStep)`.
2. **Given** an existing step class that does not define a `destructive` property, **Then** `getattr(step, 'destructive', False)` returns `False`, preserving backward compatibility.
3. **Given** `OrphanCleanupStep`, **When** inspecting its `destructive` property, **Then** it returns `True`.

---

### User Story 3 - Remove String-Matching Guard from OrphanCleanupStep (Priority: P1)

As a maintainer, I want the fragile string-matching guard (`if any(e.startswith("StoreStep:") ...)`) removed from `OrphanCleanupStep.execute()`, so that safety gating is handled by the engine and the step implementation is simpler and more robust.

**Why this priority**: The string-matching guard is the specific technical debt identified in the issue. Removing it is the direct deliverable.

**Independent Test**: After changes, verify that `OrphanCleanupStep.execute()` no longer inspects `context.errors` for store error strings. The step should execute unconditionally when called directly; gating is the engine's responsibility.

**Acceptance Scenarios**:

1. **Given** the updated `OrphanCleanupStep`, **When** `execute()` is called directly with errors in context, **Then** it proceeds with cleanup (no self-gating).
2. **Given** the full pipeline via `IngestEngine`, **When** StoreStep has errors, **Then** OrphanCleanupStep is still skipped -- but by the engine, not by the step itself.

---

## Clarifications

### Iteration 1

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| C1 | Should `destructive` be a required protocol member or handled via `getattr` with a default? | Use `getattr(step, 'destructive', False)` in the engine. Do NOT add `destructive` as a required member of the `PipelineStep` protocol. | Adding it as required would break all existing step classes and all test stubs. The protocol is `@runtime_checkable` and used across the codebase; backward compatibility is non-negotiable. |
| C2 | What message format for the skip entry in `context.errors`? | `"{step.name}: skipped — destructive step gated by prior errors"` | Consistent with existing error format `"{step.name}: {exc}"`. Uses the step name prefix so metrics and logging remain grep-friendly. |
| C3 | Should the skip be recorded in StepMetrics? | Yes, record a StepMetrics entry with `duration=0.0`, snapshot of current `items_in`/`items_out`, and `error_count=1`. | The skip message is appended to `context.errors`, which increments the error delta. Recording metrics ensures observability parity with executed steps. |
| C4 | Should only write-step errors gate destructive steps, or any error? | Any error in `context.errors` gates destructive steps. | The whole point is to generalize away from string matching. If any step has failed, the pipeline state is uncertain and destructive operations are unsafe. This is the simplest correct rule. |
| C5 | Which approach from the issue (1, 2, or 3) to use? | Approach 1 (step protocol extension with `destructive` property). | Simpler than phase-based execution (approach 2). Approach 3 (`error_gate`) is semantically identical but `destructive` better communicates intent — the property describes what the step does, not how the engine should treat it. |
| C6 | Should `destructive` be a class attribute or a `@property`? | Class attribute (e.g., `destructive = True`). | Simpler, no need for a getter. Consistent with how `name` could be done but the codebase chose `@property` for `name` because it is a common Protocol pattern. For `destructive`, a plain class attribute is more idiomatic since the value never varies per-instance. |

### Iteration 2

No new ambiguities found. Clarification loop complete.

## Scope

### In Scope

- Extend `PipelineStep` protocol with optional `destructive: bool` property
- Update `IngestEngine.run()` to check `context.errors` before executing destructive steps
- Mark `OrphanCleanupStep` as `destructive = True`
- Remove the string-matching guard from `OrphanCleanupStep.execute()`
- Add engine-level skip logging at WARNING level
- Add engine-level skip message to `context.errors`
- Unit tests for the new behavior
- Update existing tests that relied on the old string-matching guard

### Out of Scope

- Phase-based execution model (rejected in favor of simpler `destructive` property)
- Reordering or validating step ordering in the engine
- Changes to any steps other than `OrphanCleanupStep`
- Changes to plugin composition (how plugins build their step lists)
- Runtime configuration of destructive behavior (it is a static property)

## Constraints

- The `PipelineStep` protocol must remain `@runtime_checkable`
- Backward compatibility: existing step classes without `destructive` must continue to work (default to `False`)
- The `destructive` property is optional on the protocol -- the engine uses `getattr(step, 'destructive', False)`
- No new dependencies
