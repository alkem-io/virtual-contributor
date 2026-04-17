# ADR 0011: Pipeline Reliability and Thread Pool Sizing

## Status
Accepted

## Context
Production pipelines experienced thread pool exhaustion under concurrent ingest workloads. The default Python `ThreadPoolExecutor` size (`min(32, os.cpu_count() + 4)`) was insufficient when multiple LLM calls ran via `asyncio.to_thread`. Additionally, LLM adapter retries on timeout consumed thread pool capacity for minutes, amplifying the exhaustion. The body-of-knowledge summarization step lost all progress when a later refinement round failed.

## Decision

### Fixed thread pool
Set an explicit `ThreadPoolExecutor(max_workers=32)` on the event loop at startup. This provides a predictable, sufficient pool for concurrent `asyncio.to_thread` calls across all pipeline steps.

### No retry on timeout
The LLM adapter raises `TimeoutError` immediately without retry when a request times out. Retrying timed-out requests would consume thread pool capacity for extended periods under load. Non-timeout errors (API errors, rate limits) continue to retry with exponential backoff.

### Partial failure resilience in BoK summarization
`BodyOfKnowledgeSummaryStep._refine_summarize` returns partial summaries from completed refinement rounds when a later round fails, rather than discarding all work. This preserves LLM compute already spent.

### BoK inline persistence
When both `EmbeddingsPort` and `KnowledgeStorePort` are provided, `BodyOfKnowledgeSummaryStep` embeds and stores the BoK summary immediately after generation. The downstream `EmbedStep`/`StoreStep` act as fallbacks for any chunks not yet persisted.

### Batch-level deduplication
`StoreStep` deduplicates chunks by storage ID within each batch, keeping the last occurrence. This prevents ChromaDB duplicate ID errors when the same chunk appears multiple times in a single batch.

## Consequences
- **Positive**: Thread pool exhaustion eliminated under production workloads.
- **Positive**: Timeout handling is fast-fail — no wasted capacity on hopeless retries.
- **Positive**: BoK summaries are partially preserved even when refinement fails mid-way.
- **Positive**: Inline BoK persistence reduces the window where a crash could lose a completed summary.
- **Negative**: Fixed pool size of 32 may need adjustment for different deployment scales.
- **Negative**: No-retry on timeout means transient network issues that cause timeouts are not recovered automatically.
