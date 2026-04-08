# Specification: Pipeline Engine Safety — Formalize Destructive Step Handling

**Story:** alkem-io/virtual-contributor#37
**Epic:** alkem-io/alkemio#1820
**Date:** 2026-04-08

---

## User Value

Pipeline operators and developers gain confidence that destructive operations (orphan deletion, document removal) will never execute after partial write failures. The safety mechanism is engine-level and automatic, eliminating the need for each destructive step to self-guard via fragile string matching.

## Scope

1. Support an optional `destructive: bool` duck-typed property on pipeline steps (not formally added to the `PipelineStep` Protocol to maintain backward compatibility). The engine uses `getattr(step, "destructive", False)` to detect it.
2. Modify `IngestEngine.run()` to check `context.errors` before executing any step where `destructive` is `True`. If errors exist, skip the step and record a structured skip message in `context.errors`.
3. Update `OrphanCleanupStep` in `core/domain/pipeline/steps.py`:
   - Add `destructive = True` property.
   - Remove the existing string-matching guard (`if any(e.startswith("StoreStep:") ...)`).
4. Add/update unit tests to verify the engine-level skip behavior and the removal of the string-matching guard.

## Out of Scope

- Phase-based execution (grouping steps into named phases like `analyze`, `write`, `cleanup`). This is a heavier refactor reserved for a future story.
- Retry or rollback logic for failed steps.
- Changes to non-destructive steps (ChunkStep, ContentHashStep, ChangeDetectionStep, EmbedStep, StoreStep, DocumentSummaryStep, BodyOfKnowledgeSummaryStep) beyond verifying they remain `destructive=False` by default.
- Changes to plugin wiring code in `ingest_website` or `ingest_space` (they already pass `OrphanCleanupStep` to the engine; no change needed).

## Acceptance Criteria

1. **AC-1**: Pipeline steps may optionally define a `destructive` property returning `True`. Steps that do not define `destructive` are treated as non-destructive via `getattr(step, "destructive", False)` in the engine.
2. **AC-2**: `IngestEngine.run()` skips any step where `step.destructive is True` when `context.errors` is non-empty, and appends a structured skip message to `context.errors`.
3. **AC-3**: `OrphanCleanupStep.destructive` returns `True`.
4. **AC-4**: The string-matching guard (`if any(e.startswith("StoreStep:") ...)`) is removed from `OrphanCleanupStep.execute()`.
5. **AC-5**: All existing tests pass without modification (except the test that asserts the old string-matching behavior, which is updated to test the new engine-level mechanism).
6. **AC-6**: New tests verify:
   - Engine skips destructive steps when errors exist.
   - Engine runs destructive steps when no errors exist.
   - Non-destructive steps run regardless of errors.
   - Steps without a `destructive` property are treated as non-destructive.
7. **AC-7**: Lint (`ruff`), type check (`pyright`), and full test suite pass green.

## Clarifications

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Which of the three proposed approaches? | Option 1: Step protocol extension with `destructive: bool` | Simplest, least invasive, maps directly to the duck-typed protocol design. Phase-based is heavier; error-gated is semantically identical but less expressive. |
| 2 | Should `destructive` be required on the Protocol or duck-typed? | Duck-typed via `getattr(step, "destructive", False)` in the engine | Adding a required property to the `@runtime_checkable` Protocol would break all existing steps and third-party implementations. |
| 3 | Skip message format? | `"{step.name}: skipped (destructive step cannot run when pipeline has errors)"` | Structured, grep-friendly, no coupling to specific upstream step names. |
| 4 | Skip on write-phase errors only, or any errors? | Any errors in `context.errors` | Simpler, safer. Destructive ops should not run in any degraded pipeline state. |
| 5 | Property mutability? | Read-only `@property` | A step's destructive nature is intrinsic and fixed at construction time. |

**Clarify iteration count: 1** (zero new ambiguities on re-examination)

## Constraints

- Python 3.12, Poetry-managed project.
- `PipelineStep` is a `@runtime_checkable` Protocol. The `destructive` property must remain optional/duck-typed to avoid breaking existing steps that do not define it.
- No new dependencies.
- Async-first: `IngestEngine.run()` is an async method.
