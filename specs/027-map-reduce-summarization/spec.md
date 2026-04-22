# Feature Specification: Map-Reduce Summarization

**Feature Branch**: `027-map-reduce-summarization`
**Created**: 2026-04-22
**Status**: Implemented
**Input**: Retrospec from code changes

---

## Overview

Replace the sequential refine summarization strategy with a parallel map-reduce approach for both document-level and body-of-knowledge (BoK) summaries. The new strategy summarizes all chunks concurrently in a map phase, then tree-reduces the partial summaries in batches until a single summary remains. Split-model support allows using a cheaper/faster model for the map phase and a more capable model for the reduce phase.

---

## User Scenarios & Testing

### US1 (P1): Parallel map-reduce summarization replaces sequential refine for faster throughput

**As** an operator running document ingestion pipelines,
**I want** chunk summarization to happen in parallel rather than sequentially,
**so that** total summarization wall-clock time scales with concurrency rather than linearly with chunk count.

**Acceptance criteria:**
- All chunks of a document are summarized concurrently, bounded by a configurable semaphore (`concurrency` parameter).
- Partial summaries are merged via tree-reduce in batches of `reduce_fanin` until one summary remains.
- Both `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` use `_map_reduce_summarize` instead of `_refine_summarize`.
- The final summary quality is at least equivalent to the refine strategy for the same corpus.

### US2 (P2): Split-model support for map and reduce phases

**As** an operator optimizing LLM cost and quality,
**I want** to configure a cheap/fast model for the map phase and a more capable model for the reduce phase,
**so that** per-chunk work uses cost-efficient inference while synthesis uses higher-quality inference.

**Acceptance criteria:**
- `DocumentSummaryStep` accepts an optional `reduce_llm_port` parameter; when provided, the reduce phase uses it instead of `llm_port`.
- `BodyOfKnowledgeSummaryStep` accepts an optional `map_llm_port` parameter; when provided, the map phase uses it instead of `llm_port`.
- When the optional port is not provided, both phases fall back to the single `llm_port` (backward compatible).
- Plugin wiring in `ingest_space` and `ingest_website` passes the correct model instances.

### US3 (P3): Fault tolerance for partial failures

**As** a system operator,
**I want** summarization to degrade gracefully when individual LLM calls fail,
**so that** a single failed chunk does not abort the entire summarization pipeline.

**Acceptance criteria:**
- If a map call fails for a chunk, the chunk is skipped and the remaining partial summaries proceed to reduce.
- If a reduce call fails for a batch, the batch falls back to concatenation of its inputs.
- A log entry "Map-reduce: N/M partial summaries produced" reports how many map calls succeeded.
- If all map calls fail, the function returns an empty string without raising.
- A single-chunk input that fails returns an empty string.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Empty chunk list | Return `""` immediately, no LLM calls |
| Single chunk | Invoke map once; on failure return `""` |
| All map calls fail | `minis` list is empty, return `""` |
| Reduce failure at first tree level | Concatenate the batch inputs with `---` separator |
| Reduce failure at deeper tree levels | Same concatenation fallback per batch; tree continues |
| `concurrency=1` | Semaphore serializes map calls; functionally correct but no parallelism |
| `reduce_fanin` larger than chunk count | Single reduce batch; if it fails, concatenation fallback |
| `reduce_llm_port` / `map_llm_port` not provided | Falls back to the primary `llm_port`; no behavioral change |
| Extremely large corpus (hundreds of chunks) | Tree-reduce keeps batch count logarithmic; per-chunk budget floors at 500 chars |

---

## Requirements

### FR-001: Parallel map with semaphore-bounded concurrency

The `_map_reduce_summarize` function shall execute map calls for all chunks concurrently using `asyncio.gather`, bounded by an `asyncio.Semaphore(concurrency)`. The default concurrency shall be 5.

### FR-002: Tree-reduce with configurable fan-in

After the map phase, partial summaries shall be merged in batches of `reduce_fanin` (default 6 for the shared function; 10 as used by both step classes). Merging continues in levels until a single summary remains. Single-element batches pass through without an LLM call.

### FR-003: Per-chunk budget scaling

Each map call receives a character budget calculated as `max(500, max_length // max(2, len(chunks)))`. This keeps individual partial summaries compact so the reduce phase receives manageable input, with a floor of 500 characters to preserve meaningful facts.

### FR-004: Split-model support

`_map_reduce_summarize` accepts separate `map_invoke` and `reduce_invoke` callables. `DocumentSummaryStep` maps its `llm_port` to `map_invoke` and its `reduce_llm_port` (defaulting to `llm_port`) to `reduce_invoke`. `BodyOfKnowledgeSummaryStep` maps its `map_llm_port` (defaulting to `llm_port`) to `map_invoke` and its `llm_port` to `reduce_invoke`.

### FR-005: Map-phase error tolerance

Failed map calls shall be logged at WARNING level and skipped. The reduce phase proceeds with whatever partial summaries succeeded. If zero partial summaries are produced, the function returns `""`.

### FR-006: Reduce-phase error tolerance

Failed reduce calls shall be logged at WARNING level. The batch's input summaries are concatenated with `\n\n---\n\n` separators as a fallback. The tree-reduce continues with subsequent levels.

### FR-007: Dedicated prompt templates

Six new prompt constants shall be defined in `core/domain/pipeline/prompts.py`: `DOCUMENT_MAP_TEMPLATE`, `DOCUMENT_REDUCE_SYSTEM`, `DOCUMENT_REDUCE_TEMPLATE`, `BOK_MAP_TEMPLATE`, `BOK_REDUCE_SYSTEM`, `BOK_REDUCE_TEMPLATE`. Document map uses `DOCUMENT_REFINE_SYSTEM` as the system prompt (reuse of existing constant).

### FR-008: Backward compatibility

Existing deployments that do not provide `reduce_llm_port` or `map_llm_port` shall continue to work identically, with both phases using the single `llm_port`. The `_refine_summarize` function shall remain in the codebase, unused but available.

### FR-009: Plugin wiring

Both `IngestSpacePlugin` and `IngestWebsitePlugin` shall wire `reduce_llm_port` into `DocumentSummaryStep` (using `bok_llm` or `summary_llm`) and `map_llm_port` into `BodyOfKnowledgeSummaryStep` (using `summary_llm`).

---

## Success Criteria

| Criterion | Metric |
|-----------|--------|
| Throughput improvement | Summarization wall-clock time for N chunks improves proportionally to concurrency setting (e.g., concurrency=5 processes 5 chunks in approximately the time of 1) |
| No data loss from partial failures | When K of N map calls fail, the final summary contains facts from all N-K successful chunks |
| Backward compatibility | Deploying with no new environment variables produces identical behavior to specifying `reduce_llm_port=llm_port` and `map_llm_port=llm_port` |
| Logarithmic reduce depth | For N chunks with fan-in F, reduce completes in ceil(log_F(N)) levels |
| Budget correctness | No map call receives a budget below 500 characters |

---

## Assumptions

- LLM ports (`LLMPort.invoke`) are safe for concurrent invocation from multiple coroutines; the underlying adapter handles any necessary serialization or connection pooling.
- The existing refine prompts (`DOCUMENT_REFINE_SYSTEM`, etc.) are retained for potential future use or fallback; they are not deleted.
- The `asyncio.Semaphore` provides sufficient backpressure to prevent overwhelming LLM rate limits at the default concurrency of 5.
- Tree-reduce with fan-in of 10 is sufficient for corpora up to thousands of chunks without excessive concatenation depth.
