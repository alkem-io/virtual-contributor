# Clarifications: Story #1827

**Iteration count:** 2 (1 with findings, 1 clean)

## Iteration 1

### Q1: Semantics of `summarize_concurrency == 0`
**Question:** Should `summarize_concurrency == 0` mean "disabled" or "sequential"?
**Chosen answer:** Sequential (normalized to 1).
**Rationale:** The issue explicitly proposes decoupling the enable/disable concern into a separate boolean flag (`SUMMARIZE_ENABLED`). Using `0` to mean "disabled" overloads the parameter's semantic. Normalizing 0 to 1 (sequential) keeps the concurrency parameter purely about parallelism.

### Q2: Should `ingest-space` also read `summarize_concurrency` from config?
**Question:** `ingest-space` currently always includes summary steps without reading `summarize_concurrency`. Should it?
**Chosen answer:** Yes.
**Rationale:** The story requires consistent behavior. Both plugins must respect the same config parameters. `ingest-space` should pass `config.summarize_concurrency` to `DocumentSummaryStep`.

### Q3: Default value for `summarize_enabled`
**Question:** Should the new `SUMMARIZE_ENABLED` flag default to `True` or `False`?
**Chosen answer:** `True`.
**Rationale:** Backward compatibility. Existing deployments have summarization running (in `ingest-space` always, in `ingest-website` when concurrency > 0). Defaulting to `True` preserves current behavior without requiring config changes.

### Q4: `BaseConfig()` instantiation inside `ingest-website.handle()`
**Question:** Should the `ingest-website` plugin's inline `BaseConfig()` construction be refactored to injected config?
**Chosen answer:** No, keep the current pattern to minimize scope. The fix will properly use both `summarize_enabled` and `summarize_concurrency` from the config instance.
**Rationale:** Refactoring config injection is a separate concern. The inline `BaseConfig()` works and is tested. Changing it introduces risk beyond the story's scope.

### Q5: Should `ingest-space` pass `concurrency` to `DocumentSummaryStep`?
**Question:** `ingest-space` does not currently pass a `concurrency` argument to `DocumentSummaryStep`. Should it?
**Chosen answer:** Yes.
**Rationale:** Without it, `DocumentSummaryStep` falls back to its default of `8`. Both plugins should read `summarize_concurrency` from config and pass it through, ensuring the operator has consistent control over parallelism.

## Iteration 2

No new ambiguities found. Clarification loop complete.
