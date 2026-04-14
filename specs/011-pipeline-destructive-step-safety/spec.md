# Spec: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Story:** #37
**Status:** Draft
**Author:** SDD Agent

---

## User Value

Prevent data loss during ingestion by ensuring that destructive pipeline steps (e.g., orphan cleanup) are automatically skipped when earlier write steps have experienced errors. Currently, the only protection is a fragile string-matching guard in `OrphanCleanupStep` that checks for a `"StoreStep:"` prefix in `context.errors`. This does not generalize: if new destructive steps are added, or if error message formats change, the guard silently breaks. A first-class engine-level mechanism makes the pipeline intrinsically safe, regardless of how many destructive steps exist or how error messages are formatted.

## Scope

1. Establish an opt-in `destructive` property convention for pipeline steps. The `PipelineStep` protocol itself is NOT modified; instead, `IngestEngine.run()` uses `getattr(step, 'destructive', False)` to detect the flag.
2. Update `IngestEngine.run()` to check `context.errors` before executing any step that declares itself destructive, and skip it with a logged warning + recorded error if prior errors exist.
3. Mark `OrphanCleanupStep` as `destructive = True`.
4. Remove the string-matching guard (`any(e.startswith("StoreStep:") ...)`) from `OrphanCleanupStep.execute()`.
5. Add/update tests to cover the new engine-level gating behavior, the `destructive` property on `OrphanCleanupStep`, and to remove assertions on the old string-matching behavior.

## Out of Scope

- Phase-based execution model (grouping steps into named phases like `analyze`, `write`, `cleanup`). The simple `destructive` flag is sufficient for the current pipeline shape.
- Any changes to non-destructive steps (`ChunkStep`, `ContentHashStep`, `ChangeDetectionStep`, `DocumentSummaryStep`, `BodyOfKnowledgeSummaryStep`, `EmbedStep`, `StoreStep`).
- Changes to ingest plugin wiring (`ingest_website/plugin.py`, `ingest_space/plugin.py`). These pass step lists to `IngestEngine` and are unaffected by the protocol extension.

## Acceptance Criteria

1. Steps may optionally declare a `destructive` property returning `True`. The `PipelineStep` protocol is unchanged; the engine uses `getattr(step, 'destructive', False)` to detect the flag.
2. `IngestEngine.run()` skips any step where `step.destructive is True` if `context.errors` is non-empty at that point, logs a warning, and appends a skip message to `context.errors`.
3. `OrphanCleanupStep.destructive` returns `True`.
4. `OrphanCleanupStep.execute()` no longer contains the `startswith("StoreStep:")` string-matching guard.
5. Existing non-destructive steps continue to satisfy the `PipelineStep` protocol without changes (the `destructive` property defaults to `False` via the protocol or a mixin).
6. All existing tests pass, with the orphan cleanup skip test updated to exercise the new engine-level mechanism instead of the old step-level string check.
7. New tests cover: (a) engine skips destructive steps when errors exist; (b) engine runs destructive steps when no errors exist; (c) the `destructive` property on `OrphanCleanupStep`.

## Constraints

- Must remain backward-compatible with the existing `PipelineStep` protocol. Existing steps that do not define `destructive` must still satisfy the protocol (use `getattr` with default or a protocol with default).
- No new runtime dependencies.
- Must keep the pipeline engine's sequential execution model (see ADR-0004).
