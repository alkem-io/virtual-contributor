# Spec: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08
**Status:** Draft

## User Value

Operators and developers can rely on consistent, predictable summarization behavior across both ingest plugins. The `summarize_concurrency` config parameter means the same thing in both `ingest-website` and `ingest-space`, and a new explicit `SUMMARIZE_ENABLED` flag provides a clear, unambiguous way to disable summarization entirely.

## Scope

1. **Align `ingest-website` with `ingest-space`:** Always include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in the `ingest-website` pipeline, regardless of the `summarize_concurrency` value.
2. **Introduce `SUMMARIZE_ENABLED` config flag:** Add a boolean `summarize_enabled` field (default `True`) to `BaseConfig` that controls whether summarization steps are included in both plugins' pipelines.
3. **Treat `summarize_concurrency=0` as sequential (concurrency=1):** Stop overloading `summarize_concurrency=0` as "disabled". A value of 0 means "sequential processing" (i.e., concurrency 1).
4. **Update both plugins:** Both `ingest-website` and `ingest-space` respect `SUMMARIZE_ENABLED` identically.
5. **Update `.env.example`:** Document the new `SUMMARIZE_ENABLED` flag.
6. **Update tests:** Add/modify tests to cover the new behavior.

## Out of Scope

- Changing the summarization algorithm or prompt templates.
- Changing chunk sizes, overlap, or other pipeline parameters.
- Changing the `DocumentSummaryStep` or `BodyOfKnowledgeSummaryStep` internal logic.
- Adding new pipeline steps.
- Changing the concurrency implementation inside `DocumentSummaryStep` (the `concurrency` parameter is passed through but not actively used for async fan-out in the current codebase).

## Acceptance Criteria

1. When `SUMMARIZE_ENABLED=true` (default), both `ingest-website` and `ingest-space` include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in their pipelines.
2. When `SUMMARIZE_ENABLED=false`, both plugins skip `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep`.
3. `summarize_concurrency=0` no longer disables summarization; it is treated as sequential (concurrency=1).
4. All existing tests pass.
5. New tests verify the conditional pipeline composition for both plugins.
6. `.env.example` documents `SUMMARIZE_ENABLED`.

## Constraints

- Must not break backward compatibility for users who are not setting `SUMMARIZE_ENABLED` (default=True preserves current `ingest-space` behavior).
- Users who were relying on `summarize_concurrency=0` to disable summarization in `ingest-website` must now use `SUMMARIZE_ENABLED=false`. This is a deliberate breaking change for correctness.
- Follow existing codebase conventions: Pydantic Settings, env var binding, duck-typed plugins, mock ports in tests.

## Clarifications (resolved during /speckit.clarify)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Should `summarize_concurrency=0` mean "sequential" or "use default"? | Treat 0 as sequential (concurrency=1) | The parameter name implies parallelism count. Zero logically maps to "not parallel" = sequential. |
| 2 | Should `SUMMARIZE_ENABLED` default to `true` or `false`? | Default to `true` | Both plugins currently run summarization by default. Least-surprising default preserves existing behavior. |
| 3 | Where should the `SUMMARIZE_ENABLED` check live? | In each plugin, at pipeline composition time | Plugins own their step lists. Steps should not know about global enable/disable. |
| 4 | Should both plugins read `summarize_concurrency` from config? | Yes, both from `BaseConfig` | `ingest-space` currently hardcodes the default. Consistency is the goal. |
| 5 | Should `SUMMARIZE_ENABLED` validation reject invalid values? | Use Pydantic's built-in bool coercion | Standard pattern, handles true/false/1/0/yes/no. |
| 6 | Does `summarize_concurrency` need negative-value validation? | Yes, validate >= 0 | Negative concurrency is nonsensical. |
| 7 | How should `ingest-website` obtain config? | Constructor injection, not inline `BaseConfig()` | Aligns with hexagonal architecture; config read once at startup. |
| 8 | Remove inline `BaseConfig()` from `ingest-website` handle? | Yes, inject `summarize_concurrency` and `summarize_enabled` via constructor | Clean separation of concerns. |

## Supersedes

- `specs/005-fix-document-reliability/spec.md` FR-013: "The ingest website plugin MUST conditionally include summarization steps based on `summarize_concurrency` configuration -- summarization steps are omitted when the value is 0." This behavior is deliberately replaced by the `SUMMARIZE_ENABLED` flag.
