# Technical Research: Map-Reduce Summarization

**Branch**: `027-map-reduce-summarization` | **Date**: 2026-04-22

---

## Decision 1: Map-reduce over refine

**Context**: The existing refine strategy processes chunks sequentially -- chunk 1 produces an initial summary, chunk 2 refines it, chunk 3 refines again, and so on. For N chunks, this requires N sequential LLM calls with no opportunity for parallelism. With slow models (e.g., gemma-26b at ~2 min/call), 20 chunks means ~40 minutes of wall-clock time.

**Decision**: Replace refine with parallel map-reduce. Each chunk is summarized independently (map), then partial summaries are merged hierarchically (reduce).

**Rationale**:
- Map phase is embarrassingly parallel -- all chunks can be processed concurrently.
- Wall-clock time drops from O(N) to O(N/concurrency + log_F(N)) where F is the reduce fan-in.
- Map summaries are independent, so a failed chunk does not corrupt the running summary.
- Quality on large corpora improves because each chunk gets a fresh context window (no accumulated drift from sequential refinement).

**Trade-off**: The refine strategy naturally deduplicates across chunks as it accumulates. Map-reduce relies on the reduce prompt to deduplicate, which may be slightly less aggressive but is more robust to individual failures.

---

## Decision 2: Tree-reduce (not flat reduce)

**Context**: After the map phase produces N partial summaries, they must be merged into one. A flat reduce would concatenate all N and pass them to a single LLM call. For large N, this can exceed the model's context window.

**Decision**: Use tree-reduce -- merge in batches of `reduce_fanin` (default 6-10 depending on step), then merge the merged results, repeating until one summary remains.

**Rationale**:
- Handles arbitrary corpus sizes without hitting context limits.
- Each reduce call processes a bounded input (at most `reduce_fanin` partial summaries).
- Logarithmic depth: ceil(log_F(N)) levels for N partials.
- Batches at each level can optionally be parallelized in the future (currently sequential within a level but levels are O(log N) so the impact is small).

---

## Decision 3: Semaphore-bounded concurrency (not unlimited gather)

**Context**: `asyncio.gather(*tasks)` launches all tasks simultaneously. For 100 chunks, this means 100 concurrent LLM calls, which can overwhelm rate limits, exhaust connection pools, or cause OOM on the LLM provider side.

**Decision**: Use `asyncio.Semaphore(concurrency)` to bound the number of in-flight map calls. Default concurrency is 5.

**Rationale**:
- Provides backpressure without requiring external rate limiting.
- The semaphore is configurable per step instantiation.
- `asyncio.gather` still launches all coroutines, but the semaphore serializes them into bounded windows.
- Default of 5 balances throughput with typical LLM API rate limits.

---

## Decision 4: Split-model architecture

**Context**: The map phase and reduce phase have different computational profiles. Map calls process individual chunks and produce compact summaries -- this is mechanical extraction work well-suited to a fast/cheap model. The reduce phase synthesizes multiple summaries into a cohesive whole -- this benefits from a more capable model with better reasoning.

**Decision**: Accept separate `map_invoke` and `reduce_invoke` callables in `_map_reduce_summarize`. Wire them through optional constructor parameters:
- `DocumentSummaryStep.reduce_llm_port` -- uses the BoK model (typically larger) for reduce
- `BodyOfKnowledgeSummaryStep.map_llm_port` -- uses the summary model (typically cheaper) for map

**Rationale**:
- Cost optimization: cheap model handles N map calls, expensive model handles ~N/F reduce calls.
- Quality optimization: the reduce model has better synthesis capability where it matters most.
- Backward compatible: when the optional port is not provided, both phases use the same model.
- The split follows the existing config pattern (`summarize_llm_*` vs `bok_llm_*` env vars).

---

## Decision 5: Retain `_refine_summarize` in codebase

**Context**: The map-reduce strategy replaces refine for both `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep`. The `_refine_summarize` function is no longer called.

**Decision**: Keep `_refine_summarize` in `steps.py` and all refine prompt templates in `prompts.py`.

**Rationale**:
- Enables easy rollback if map-reduce shows quality regressions in specific domains.
- The function is small (~50 lines) and carries no maintenance burden.
- Refine prompts are referenced by the existing import block (no dead import warnings).
- A future feature could offer strategy selection (map-reduce vs refine) per collection.

---

## Decision 6: Per-chunk budget scaling formula

**Context**: Each map call needs a character budget to control output length. If all map summaries are at full `max_length`, the reduce phase would receive N * max_length characters, which can exceed context limits and produce redundant output.

**Decision**: Per-chunk budget is `max(500, max_length // max(2, len(chunks)))`.

**Rationale**:
- Scales inversely with chunk count so total map output stays roughly proportional to `max_length`.
- `max(2, ...)` prevents division by 1 for single-chunk input (handled separately anyway).
- Floor of 500 ensures even large corpora produce meaningful per-chunk summaries with enough room for specific entities, dates, and facts.
- The reduce phase uses the full `max_length` as its budget since it produces the final output.

---

## Decision 7: Error handling strategy

**Context**: LLM calls can fail due to rate limits, timeouts, malformed responses, or model errors. In a parallel pipeline, individual failures should not abort the entire operation.

**Decision**:
- **Map phase**: Failed chunks are logged at WARNING and skipped. The `minis` list contains only successful results. If all fail, return `""`.
- **Reduce phase**: Failed batches fall back to concatenation of their input summaries with `---` separators. The tree continues with the concatenated result.

**Rationale**:
- A partial summary covering N-K of N chunks is strictly better than no summary.
- Concatenation preserves all information from the successful map calls, even if the structure is suboptimal.
- The tree-reduce can recover at subsequent levels -- a later reduce call may successfully synthesize the concatenated batch with other batches.
- Logging at WARNING ensures operators are alerted without filling error budgets.
