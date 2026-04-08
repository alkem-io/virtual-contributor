# Spec: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Parent:** alkem-io/alkemio#1820
**Date:** 2026-04-08

## User Value

Operators configuring the ingest pipeline expect `summarize_concurrency` to behave identically across all ingest plugins. Currently, setting `summarize_concurrency=0` silently disables summarization in `ingest-website` while `ingest-space` always summarizes. This inconsistency causes confusing behavior and makes the config parameter semantics unclear.

## Scope

1. **Align pipeline assembly in `ingest-website`** to always include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep`, matching `ingest-space` behavior.
2. **Introduce a `SUMMARIZE_ENABLED` boolean config flag** (default `true`) that explicitly controls whether summarization steps are included in the pipeline for both plugins.
3. **Treat `summarize_concurrency=0` as sequential** (equivalent to concurrency=1) rather than "disabled", to avoid overloading the concurrency parameter.
4. **Add tests** to verify consistent behavior across both plugins.

## Out of Scope

- Changes to the summarization prompts or quality.
- Changes to `DocumentSummaryStep` or `BodyOfKnowledgeSummaryStep` internal logic beyond handling `concurrency <= 0`.
- Changes to non-ingest plugins (expert, generic, guidance, openai_assistant).
- Changes to the pipeline engine itself.

## Acceptance Criteria

1. `ingest-website` always includes `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in its pipeline, matching `ingest-space`.
2. A new `SUMMARIZE_ENABLED` config flag (default `true`) controls whether summary steps are included. When `false`, both plugins skip summary steps.
3. When `summarize_concurrency` is 0, `DocumentSummaryStep` receives `concurrency=1` (sequential), not disabled.
4. Both plugins respect `SUMMARIZE_ENABLED` identically.
5. Existing tests continue to pass.
6. New tests verify: (a) both plugins include summary steps by default, (b) `SUMMARIZE_ENABLED=false` skips summary steps in both plugins, (c) `summarize_concurrency=0` results in sequential summarization (concurrency=1).

## Constraints

- Must not break backward compatibility for deployments not setting `SUMMARIZE_ENABLED` (default=true preserves current ingest-space behavior).
- No changes to the plugin contract or port interfaces.
- Config changes must follow existing Pydantic Settings patterns in `core/config.py`.

## Clarifications (resolved)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | What does `summarize_concurrency=0` mean? | Sequential (maps to concurrency=1) | Zero-as-unlimited is counterintuitive; the story suggests sequential. |
| 2 | Where does `SUMMARIZE_ENABLED` live? | `BaseConfig` | Both plugins share the same base; matches how `summarize_concurrency` is defined. |
| 3 | Reject negative `summarize_concurrency`? | Yes, add validation | Negative concurrency is nonsensical; matches existing validation patterns. |
| 4 | Should `ingest-space` read `summarize_concurrency` from config? | Yes | Consistency: both plugins should use the same config-driven concurrency value. |
| 5 | Should `ingest-space` respect `SUMMARIZE_ENABLED`? | Yes | True parity requires both plugins to honor the flag. |
| 6 | Should inline `BaseConfig()` in `handle()` be changed? | Use plugin-specific config classes | Minimal improvement; `IngestWebsiteConfig`/`IngestSpaceConfig` inherit from `BaseConfig`. |
