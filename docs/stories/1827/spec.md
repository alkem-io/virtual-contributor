# Spec: Consistent summarization behavior between ingest-website and ingest-space

**Story:** #1827
**Parent:** alkem-io/alkemio#1820

## User Value

Operators configuring the ingest pipeline expect `summarize_concurrency` to behave identically across all ingest plugins. Currently the two ingest plugins interpret the parameter differently, leading to silent data-quality regression when `summarize_concurrency=0` is set: ingest-website silently skips all summarization while ingest-space still summarizes. This inconsistency makes the system unpredictable and undermines trust in the configuration surface.

## Scope

1. **Align ingest-website with ingest-space**: Always include `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` in the pipeline, regardless of `summarize_concurrency` value.
2. **Introduce `summarize_enabled` config flag**: Add a new boolean configuration field `SUMMARIZE_ENABLED` (default `true`) to `BaseConfig` that explicitly controls whether summarization steps are included. Both plugins honor this flag consistently.
3. **Treat `summarize_concurrency=0` as sequential**: When `summarize_concurrency` is 0, pass `concurrency=1` to `DocumentSummaryStep` so it runs sequentially rather than being disabled.
4. **Update tests**: Add and update unit tests covering all combinations of `summarize_enabled` and `summarize_concurrency` for both plugins.

## Out of Scope

- Changing the summarization algorithm or prompt templates.
- Modifying the `IngestEngine` or `PipelineStep` protocol.
- Adding new pipeline steps.
- Changing ingest-space's chunk size, overlap, or other pipeline parameters.
- Runtime toggling of summarization (the flag is read once at pipeline construction time).

## Acceptance Criteria

1. When `SUMMARIZE_ENABLED=true` (default) and `summarize_concurrency=8`, both plugins include summary steps with concurrency=8. (Preserves current ingest-space behavior.)
2. When `SUMMARIZE_ENABLED=true` and `summarize_concurrency=0`, both plugins include summary steps with concurrency=1 (sequential). (Fixes current ingest-website bug.)
3. When `SUMMARIZE_ENABLED=false`, neither plugin includes summary steps. (New opt-out feature.)
4. No behavioral change for ingest-space when `SUMMARIZE_ENABLED` is not set (default true).
5. All existing tests continue to pass.
6. New tests validate the three scenarios above for both plugins.

## Constraints

- Must remain backward-compatible: existing deployments without `SUMMARIZE_ENABLED` set must behave as if it were `true`.
- `summarize_concurrency` retains its meaning as "parallel summarization concurrency" and is no longer overloaded as an enable/disable toggle.
- Config changes follow the existing Pydantic Settings pattern in `core/config.py`.
