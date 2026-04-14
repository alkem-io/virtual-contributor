# Feature Specification: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Feature Branch**: `story/37-pipeline-engine-safety-destructive-step-handling`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story #37

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Engine-Level Destructive Step Gating (Priority: P1)

As a platform operator, I want the ingest pipeline engine to automatically skip destructive steps (e.g., orphan cleanup) when earlier steps have recorded errors, so that partial write failures never trigger data deletion and I can trust that failed ingestions do not cause data loss.

**Why this priority**: The current guard is a fragile string-matching check inside `OrphanCleanupStep` that looks for a `"StoreStep:"` prefix in `context.errors`. If error message formats change or new destructive steps are added, this guard silently breaks. An engine-level mechanism is the only reliable way to prevent data loss during partial failures.

**Independent Test**: Run an ingest pipeline with a step that injects an error into `context.errors` followed by a step marked `destructive = True`. Verify the destructive step is skipped, a warning is logged, a skip message appears in errors, and metrics are recorded with `duration=0.0` and `error_count=1`.

**Acceptance Scenarios**:

1. **Given** a pipeline with a failing step followed by a destructive step, **When** `IngestEngine.run()` executes, **Then** the destructive step is NOT executed, a warning is logged, and a skip message is appended to `context.errors`.
2. **Given** a pipeline with no prior errors and a destructive step, **When** `IngestEngine.run()` executes, **Then** the destructive step runs normally.
3. **Given** a pipeline with errors and a non-destructive step, **When** `IngestEngine.run()` executes, **Then** the non-destructive step still runs regardless of errors.
4. **Given** a pipeline with errors and multiple destructive steps, **When** `IngestEngine.run()` executes, **Then** all destructive steps are skipped.
5. **Given** a pipeline where a non-destructive step raises an exception, **When** `IngestEngine.run()` catches the error and continues to a destructive step, **Then** the destructive step is skipped due to the caught error.
6. **Given** a destructive step is skipped, **When** metrics are recorded, **Then** `StepMetrics` has `duration=0.0` and `error_count=1`.
7. **Given** a destructive step is skipped due to 2 prior errors, **When** the skip message is appended, **Then** the message format is `"cleanup: skipped (destructive step gated by 2 prior error(s))"`.

---

### User Story 2 -- OrphanCleanupStep Declares Itself Destructive (Priority: P2)

As a developer maintaining the pipeline, I want `OrphanCleanupStep` to declare itself as destructive via a `destructive` property so that the engine-level gating mechanism protects it automatically, and the fragile string-matching guard can be removed.

**Why this priority**: This story applies the engine-level mechanism (US1) to the only currently known destructive step. Without this, the old string-matching guard remains as the sole protection.

**Independent Test**: Instantiate `OrphanCleanupStep` and verify `step.destructive is True`. Run an `IngestEngine` pipeline with a failing store step followed by `OrphanCleanupStep` and verify orphan data is not deleted.

**Acceptance Scenarios**:

1. **Given** an `OrphanCleanupStep` instance, **When** `step.destructive` is checked, **Then** it returns `True`.
2. **Given** a pipeline with a failing store step and an `OrphanCleanupStep`, **When** `IngestEngine.run()` executes, **Then** orphan cleanup is skipped and orphan data remains intact.
3. **Given** `OrphanCleanupStep.execute()`, **When** the source code is inspected, **Then** it no longer contains the `startswith("StoreStep:")` string-matching guard.

---

### Edge Cases

- When a step has `destructive = True` but is positioned in the middle of the pipeline, non-destructive steps after it still execute normally.
- When a non-destructive step does not define a `destructive` attribute, `getattr(step, 'destructive', False)` safely returns `False` -- no error, no behavioral change.
- When all steps succeed, destructive steps run normally as if the flag did not exist.
- When a destructive step is the first step in the pipeline and no errors exist, it executes normally.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `IngestEngine.run()` MUST check `getattr(step, 'destructive', False)` before executing each step.
- **FR-002**: `IngestEngine.run()` MUST skip any step where `destructive` is `True` and `context.errors` is non-empty, appending a skip message to `context.errors`.
- **FR-003**: `IngestEngine.run()` MUST log a warning when skipping a destructive step: `"Skipping destructive step '%s' due to %d prior error(s)"`.
- **FR-004**: `IngestEngine.run()` MUST record `StepMetrics` for skipped destructive steps with `duration=0.0` and `error_count=1`.
- **FR-005**: `OrphanCleanupStep` MUST declare a `destructive` property returning `True`.
- **FR-006**: `OrphanCleanupStep.execute()` MUST NOT contain the `startswith("StoreStep:")` string-matching guard.
- **FR-007**: The `PipelineStep` protocol MUST remain unchanged -- the `destructive` flag is opt-in via duck typing (`getattr` with default).
- **FR-008**: Existing non-destructive steps MUST continue to satisfy the `PipelineStep` protocol without any modifications.

### Key Entities

- **Destructive Step Convention**: An opt-in property (`destructive: bool`) on pipeline steps. Steps that delete or modify existing data in irreversible ways declare `destructive = True`. The engine uses `getattr(step, 'destructive', False)` to detect the flag without modifying the `PipelineStep` protocol.
- **Skip Message**: A formatted error string appended to `context.errors` when a destructive step is gated: `"{step.name}: skipped (destructive step gated by {N} prior error(s))"`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Destructive steps are automatically gated by any prior error, not just errors matching a specific string pattern.
- **SC-002**: The `PipelineStep` protocol is unchanged -- existing steps work without modification.
- **SC-003**: All new and existing tests pass (pytest green), including 7 new destructive gating tests.
- **SC-004**: The string-matching guard in `OrphanCleanupStep` is fully removed, eliminating the fragile coupling to error message formats.

## Assumptions

- The `PipelineStep` protocol is `@runtime_checkable` and adding a `destructive` property to individual step classes does not break protocol conformance for other steps.
- The sequential execution model of `IngestEngine.run()` (ADR-0004) is preserved -- destructive gating is a per-step check within the existing loop.
- No new runtime dependencies are needed.
- Only `OrphanCleanupStep` is currently destructive. Future destructive steps can opt in by adding the property.

## Clarifications

### C1: Protocol extension strategy for backward compatibility

**Question**: Should `destructive` be added to the `PipelineStep` protocol, use a mixin, or use `getattr`?

**Answer**: Use `getattr(step, 'destructive', False)` in `IngestEngine.run()`. The protocol remains unchanged. This is consistent with Python duck-typing conventions used elsewhere in this codebase.

### C2: Error message format for skipped destructive steps

**Question**: What format should the engine-level skip message use?

**Answer**: `"{step.name}: skipped (destructive step gated by {N} prior error(s))"`. Consistent with how the engine already formats caught exception messages as `f"{step.name}: {exc}"`.

### C3: Log level for skipping

**Question**: What log level for a gated destructive skip?

**Answer**: `logger.warning`. Not an exception (nothing crashed), but noteworthy enough for operators. The skip is an intentional safety mechanism, not routine.

### C4: Metrics for skipped steps

**Question**: Should `StepMetrics` be recorded for skipped destructive steps?

**Answer**: Yes. Record with `duration=0.0`, current `items_in`/`items_out`, and `error_count=1`. Ensures monitoring dashboards always have entries for all configured steps.

### C5: Destructive step in mid-pipeline

**Question**: If a destructive step is not the last step, do subsequent non-destructive steps still run?

**Answer**: Yes. The `destructive` flag only gates the specific step that declares it. Non-destructive steps always run.
