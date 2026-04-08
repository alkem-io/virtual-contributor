# Spec: Consistent Summarization Behavior Between Ingest Plugins

**Story:** alkem-io/alkemio#1827
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Operators and developers expect both ingest plugins (`ingest-website` and `ingest-space`) to behave identically regarding summarization. Today, `ingest-website` silently skips summarization when `summarize_concurrency == 0`, while `ingest-space` always runs summarization regardless of the concurrency setting. This inconsistency causes unpredictable behavior: the same document ingested through different paths may or may not get summaries, leading to degraded retrieval quality for website-sourced knowledge.

## Scope

1. **Align summarization pipeline construction** in `ingest-website` with `ingest-space`: always include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in the pipeline.
2. **Add a new `SUMMARIZE_ENABLED` boolean config flag** to explicitly control whether summarization is enabled or disabled, rather than overloading `summarize_concurrency`.
3. **Apply `summarize_concurrency` consistently** as a parallelism control parameter in both plugins (how many documents are summarized in parallel).
4. **Ensure `summarize_concurrency == 0` means sequential** (concurrency=1), not disabled.
5. **Update both plugins** to read `summarize_enabled` from config and conditionally include summary steps.
6. **Update tests** to cover the new flag and the consistent behavior.

## Out of Scope

- Changes to the summarization prompt templates or quality.
- Changes to the `DocumentSummaryStep` or `BodyOfKnowledgeSummaryStep` internal logic beyond constructor arguments.
- Changes to the pipeline engine itself.
- Per-plugin summarization enable/disable (one global flag suffices).

## Acceptance Criteria

1. **AC-1:** Both `ingest-website` and `ingest-space` include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in their pipelines when `summarize_enabled` is `True` (default).
2. **AC-2:** Both plugins omit summary steps when `summarize_enabled` is `False`.
3. **AC-3:** `summarize_concurrency` controls only parallelism degree. A value of `0` is normalized to `1` (sequential).
4. **AC-4:** Both `ingest-space` and `ingest-website` pass the config's `summarize_concurrency` to `DocumentSummaryStep`.
5. **AC-5:** A new `SUMMARIZE_ENABLED` env var (default `true`) is added to `BaseConfig`.
6. **AC-6:** `.env.example` documents the new variable.
7. **AC-7:** Existing tests continue to pass; new tests validate both plugins with `summarize_enabled=True` and `summarize_enabled=False`.

## Constraints

- Must not break existing deployments where `SUMMARIZE_CONCURRENCY` is set to a positive integer.
- The default behavior (no env vars set) must remain identical to today's `ingest-space` behavior (summarization enabled).
- No new dependencies may be added.
