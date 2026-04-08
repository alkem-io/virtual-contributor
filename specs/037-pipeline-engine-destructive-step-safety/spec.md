# Spec: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story**: #37  
**Status**: Draft  
**Author**: SDD Agent  
**Date**: 2026-04-08  

---

## User Value

Pipeline authors and operators gain confidence that destructive steps (e.g., OrphanCleanupStep) will never execute when earlier write steps had partial failures. Today, this safety depends on a fragile string-matching guard inside OrphanCleanupStep that checks for a `StoreStep:` prefix in `context.errors`. This story replaces that ad-hoc guard with a first-class, engine-level mechanism that generalizes to any current or future destructive step.

## Scope

1. Extend the `PipelineStep` protocol with an optional `destructive: bool` property (defaulting to `False`) so steps can self-declare as destructive.
2. Update `IngestEngine.run()` to check `context.errors` before executing any step whose `destructive` property is `True`, and skip it with a logged warning and recorded error when errors exist.
3. Update `OrphanCleanupStep` to declare `destructive = True` and remove the current string-matching guard from its `execute()` method.
4. Add/update tests covering the new engine-level gating behavior.

## Out of Scope

- Phase-based execution grouping (analyze/write/cleanup phases) -- more complex than needed for the current requirement.
- Automatic rollback of partially written data on step failure.
- Changes to any step other than `OrphanCleanupStep` (no other step is currently destructive).
- Changes to the plugin assembly code in `ingest_website` or `ingest_space` plugins (no changes needed since the behavior is engine-level).

## Acceptance Criteria

1. **AC1**: `PipelineStep` protocol has an optional `destructive` property. Steps not declaring it are treated as non-destructive (`False`).
2. **AC2**: `IngestEngine.run()` skips any step with `destructive=True` when `context.errors` is non-empty, appends a skip message to `context.errors`, and logs at WARNING level.
3. **AC3**: `OrphanCleanupStep` declares `destructive = True` as a class-level attribute and no longer contains string-matching logic against `context.errors`.
4. **AC4**: Existing tests for OrphanCleanupStep that validated the string-matching guard (`test_skips_cleanup_on_store_step_errors`) are updated to validate engine-level gating instead.
5. **AC5**: New engine-level tests verify: (a) destructive steps are skipped when errors exist, (b) destructive steps run normally when no errors exist, (c) non-destructive steps still run even when errors exist, (d) metrics are recorded for skipped destructive steps.
6. **AC6**: All existing tests continue to pass without modification (except those testing the removed string-matching guard).
7. **AC7**: `IngestResult.success` remains `False` when errors exist, regardless of whether destructive steps were skipped.

## Constraints

- The `PipelineStep` protocol must remain `@runtime_checkable` and duck-typed. The `destructive` property must be optional -- steps without it must not break.
- No changes to `PipelineContext` fields.
- The skip message appended to `context.errors` must clearly identify the skipped step and the reason.
- The solution must work with the existing `RecordingStep` and other test doubles that do not declare `destructive`.

## Glossary

- **Destructive step**: A pipeline step that deletes or removes data from the knowledge store. Running such a step after partial write failures could cause data loss.
- **Error gate**: The engine-level check that prevents destructive steps from executing when prior steps have recorded errors.
- **Write phase**: The portion of the pipeline that persists data (EmbedStep, StoreStep). Errors here trigger the error gate for subsequent destructive steps.
