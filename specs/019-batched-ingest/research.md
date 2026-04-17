# Research 019: Batched Ingest Pipeline Processing

**Date:** 2026-04-15

## Decision 1: Batched vs. Streaming Processing

### Context

Two approaches were considered for breaking up the all-or-nothing pipeline:

1. **Batched**: Partition documents into fixed-size groups, run all batch_steps per group sequentially, persist, then proceed to the next group.
2. **Streaming**: Process documents one at a time through the entire pipeline, persisting each individually.

### Decision

**Batched processing** was chosen.

### Rationale

- **Amortized overhead**: Steps like ChangeDetectionStep query the store once per batch (for the batch's document IDs), not once per document. With a batch_size of 5, this is a 5x reduction in store round-trips compared to streaming.
- **EmbedStep efficiency**: Embedding APIs are optimized for batch calls. Sending 1 document's chunks at a time would underutilize GPU batch parallelism.
- **DocumentSummaryStep concurrency**: The existing concurrency model (semaphore-bounded `asyncio.gather`) works naturally within a batch of N documents. Per-document streaming would eliminate this parallelism.
- **Simplicity**: The PipelineStep protocol is unchanged. Steps still operate on a `PipelineContext` with a list of chunks. No streaming abstractions, backpressure, or windowing needed.
- **Configurable trade-off**: `batch_size` lets operators tune the balance between failure blast radius (smaller batches = less wasted work) and throughput (larger batches = fewer store round-trips).

### Rejected Alternative: Streaming

Per-document streaming would minimize failure blast radius to a single document but at the cost of:
- N store queries for ChangeDetection instead of ceil(N/batch_size)
- Loss of cross-document embedding batching
- Loss of cross-document summarization concurrency
- Need for a fundamentally different step protocol (iterator/generator-based)

## Decision 2: batch_steps + finalize_steps Split

### Context

The BoK summary step needs content from all documents to generate a corpus-level overview. In the previous sequential model, it simply read the `chunks` list after all documents had been chunked. In batched mode, each batch's chunks are discarded after storage to keep memory bounded.

### Decision

Split the pipeline into two explicit phases: `batch_steps` (per-batch) and `finalize_steps` (run once after all batches).

### Rationale

- **Explicit phase boundary**: Rather than having steps implicitly detect whether they're in "batch mode" or "finalize mode," the engine makes the split explicit at construction time. This keeps step implementations simple.
- **Finalize context construction**: The engine builds the finalize context with accumulated state from all batches: `document_summaries`, `orphan_ids`, `removed_document_ids`, `raw_chunks_by_doc`, error lists, and counters. This gives finalize steps everything they need without re-querying the store.
- **OrphanCleanup placement**: OrphanCleanupStep is destructive and should run exactly once after all batches have persisted. Placing it in finalize_steps enforces this naturally.
- **BoK Summary placement**: BoK needs all document summaries and raw chunk content. Finalize phase guarantees this data is complete.

### Step Assignment

| Phase | Steps | Rationale |
|-------|-------|-----------|
| batch_steps | ChunkStep | Per-document, no cross-batch dependency |
| batch_steps | ContentHashStep | Per-chunk, no cross-batch dependency |
| batch_steps | ChangeDetectionStep | Per-document (needs all_document_ids for removal detection) |
| batch_steps | DocumentSummaryStep | Per-document with concurrency within batch |
| batch_steps | EmbedStep | Per-chunk, batches embeddings efficiently |
| batch_steps | StoreStep | Persists batch results, enables partial-failure recovery |
| finalize_steps | BodyOfKnowledgeSummaryStep | Needs all document summaries |
| finalize_steps | EmbedStep | Embeds BoK summary chunk |
| finalize_steps | StoreStep | Persists BoK summary |
| finalize_steps | OrphanCleanupStep | Destructive; must run after all batches |

## Decision 3: Why Not Character-Based Grouping

### Context

An alternative batching strategy was considered: group documents by total character count rather than document count, to ensure each batch has roughly equal processing cost.

### Decision

Use simple document-count partitioning (`batch_size` = number of documents per batch).

### Rationale

- **Predictability**: Document-count batching produces deterministic batch boundaries. The same corpus always produces the same batches, making debugging and logging straightforward.
- **Simplicity**: No need to pre-scan document lengths, sort, or apply bin-packing. `documents[i:i+batch_size]` is a single slice operation.
- **Sufficient for the use case**: In practice, documents from the same source (website pages, space entities) tend to be similar in size. The variance within a batch is small enough that character-based grouping would add complexity without meaningful benefit.
- **Configurable mitigation**: If an operator has a corpus with extreme size variance, they can reduce `batch_size` to minimize per-batch memory usage.

### When Character-Based Grouping Would Matter

If the system later supports mixed-source ingestion (e.g., combining 50KB PDFs with 200-char metadata documents in a single pipeline run), character-based grouping would produce more balanced batches. This can be added as a future enhancement without breaking the current API.

## Decision 4: Backward Compatibility Approach

### Context

Existing code uses `IngestEngine(steps=[...])` in multiple places: cleanup pipelines (zero-document re-ingestion), tests, and any future callers.

### Decision

Keep the `steps=` constructor parameter alongside the new `batch_steps=`/`finalize_steps=` parameters. The `run()` method dispatches to `_run_sequential()` or `_run_batched()` based on which parameters were provided.

### Rationale

- **Zero migration cost**: No existing code needs to change. `IngestEngine(steps=[...])` continues to work identically.
- **Explicit mutual exclusion**: Constructor validation ensures you cannot accidentally specify both `steps` and `batch_steps`, preventing ambiguous behavior.
- **Clean separation**: Sequential and batched execution paths are separate private methods (`_run_sequential`, `_run_batched`), sharing only the `_run_steps` helper and `_build_result` static method.

### Validation Rules

| Condition | Result |
|-----------|--------|
| `steps` and `batch_steps` both provided | `ValueError` |
| Neither `steps` nor `batch_steps` provided | `ValueError` |
| `batch_steps` without `finalize_steps` | `ValueError` |
| `steps` only | Sequential mode |
| `batch_steps` + `finalize_steps` | Batched mode |

## Decision 5: Context Accumulation Strategy

### Context

In batched mode, each batch has its own `PipelineContext`. Cross-batch state must be accumulated for the finalize phase and for the final `IngestResult`.

### Decision

Use explicit Python accumulators (`global_document_summaries`, `global_orphan_ids`, etc.) in `_run_batched()`, merged after each batch completes. The finalize context is constructed from these accumulators.

### Rationale

- **Transparency**: Every piece of accumulated state is explicitly declared and merged. No hidden shared-state mutations.
- **No shared mutable context**: Batches do not share a `PipelineContext`. Each batch gets a fresh context with only its documents and the `all_document_ids` set. This prevents steps from accidentally reading/writing cross-batch state.
- **raw_chunks_by_doc**: After each batch's steps complete, chunk content (embedding_type="chunk" only) is extracted into the `raw_chunks_by_doc` accumulator before the batch context is discarded. This gives the BoK step access to all raw content without holding all chunks in memory simultaneously.

### Accumulated Fields

| Accumulator | Merge Strategy | Purpose |
|-------------|----------------|---------|
| `global_document_summaries` | `dict.update()` | Per-doc summaries for BoK |
| `global_orphan_ids` | `set \|=` | Orphan chunk IDs for cleanup |
| `global_removed_document_ids` | `set \|=` | Removed doc IDs for cleanup |
| `global_changed_document_ids` | `set \|=` | Changed doc IDs for BoK regeneration |
| `global_unchanged_chunk_hashes` | `set \|=` | Unchanged hashes for StoreStep skip |
| `global_errors` | `list.extend()` | Error messages |
| `global_metrics` | `dict.update()` | Per-step metrics (keyed with batch suffix) |
| `global_raw_chunks_by_doc` | `dict.setdefault().append()` | Raw chunk content for BoK |
| `global_chunks_stored` | `+= int` | Counter |
| `global_chunks_skipped` | `+= int` | Counter |
| `global_change_detection_ran` | `\|= bool` | Flag |
