# Quickstart 019: Batched Ingest Pipeline Processing

**Date:** 2026-04-15

## Configuration

The ingest batch size is controlled by a single environment variable:

```bash
# Set the number of documents per batch (default: 5)
INGEST_BATCH_SIZE=5
```

Minimum value is 1 (clamped internally). Higher values mean fewer store round-trips but larger failure blast radius. Lower values mean more frequent persistence at the cost of more store queries.

### Recommended Values

| Corpus Size | Recommended Batch Size | Rationale |
|-------------|----------------------|-----------|
| < 10 documents | 5 (default) | Single or two batches; minimal overhead |
| 10-50 documents | 5-10 | Balance between persistence frequency and throughput |
| 50+ documents | 3-5 | Tighter failure recovery; more frequent checkpoints |
| Slow LLM (2+ min/call) | 2-3 | Minimize wasted summarization work on failure |

### Docker Compose Example

```yaml
services:
  virtual-contributor-ingest-website:
    environment:
      - INGEST_BATCH_SIZE=5
      - PLUGIN_TYPE=ingest-website
```

## How It Works

When an ingest pipeline runs (website or space), documents are now processed in batches:

1. All documents are partitioned into groups of `INGEST_BATCH_SIZE`.
2. Each batch runs through: Chunk -> ContentHash -> ChangeDetection -> Summarize -> Embed -> Store.
3. After each batch, results (summaries, orphan IDs, errors) are accumulated.
4. After all batches complete, finalize steps run once: BoK Summary -> Embed -> Store -> OrphanCleanup.

If batch 3 of 5 fails, batches 1 and 2 are already persisted in the vector store. Only batch 3's work is lost.

## Verifying Batched Processing

### Log Output

With `LOG_LEVEL=INFO`, you will see batch progress in logs:

```
INFO  Running batch 0 (5 documents) for collection example.com-knowledge
INFO  Running batch 1 (5 documents) for collection example.com-knowledge
INFO  Running batch 2 (3 documents) for collection example.com-knowledge
INFO  Running finalize steps for collection example.com-knowledge
```

### Metrics

Batch step metrics include a batch index suffix:

```
chunk_batch_0: duration=0.12s, items_in=0, items_out=15
chunk_batch_1: duration=0.11s, items_in=0, items_out=14
store_batch_0: duration=0.45s, items_in=15, items_out=15
store_batch_1: duration=0.42s, items_in=14, items_out=14
```

## Files Changed

| File | What Changed |
|------|-------------|
| `core/domain/pipeline/engine.py` | PipelineContext: `all_document_ids`, `raw_chunks_by_doc` fields. IngestEngine: `batch_steps`/`finalize_steps` constructor, `_run_batched()`, `_run_steps()`, `_build_result()`. |
| `core/domain/pipeline/steps.py` | ChangeDetectionStep uses `all_document_ids`. BoKSummaryStep supports `raw_chunks_by_doc`. |
| `core/config.py` | `batch_size` renamed to `ingest_batch_size`, default 5. |
| `main.py` | Injects `ingest_batch_size` into plugin constructors. |
| `plugins/ingest_website/plugin.py` | Split steps into `batch_steps` + `finalize_steps`. Added `ingest_batch_size` param. |
| `plugins/ingest_space/plugin.py` | Same as website plugin. |
| `tests/core/domain/test_pipeline_steps.py` | 22 new + 2 updated tests for batched engine, change detection, and BoK finalize mode. |
| `tests/plugins/test_ingest_website.py` | Updated to assert `batch_steps`/`finalize_steps` kwargs. |
| `tests/plugins/test_ingest_space.py` | Same. |

## Backward Compatibility

The existing `IngestEngine(steps=[...])` API is unchanged. Cleanup pipelines (zero-document re-ingestion) continue to use sequential mode:

```python
# This still works exactly as before
cleanup_engine = IngestEngine(steps=[
    ChangeDetectionStep(knowledge_store_port=store),
    OrphanCleanupStep(knowledge_store_port=store),
])
await cleanup_engine.run([], collection_name)
```

## Running Tests

```bash
# All tests
poetry run pytest

# Batched engine tests only
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestIngestEngineBatched

# Batched change detection tests
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestChangeDetectionStepBatched

# Batched BoK tests
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestBoKSummaryStepBatchedMode

# Plugin tests (verify batch_steps/finalize_steps wiring)
poetry run pytest tests/plugins/test_ingest_website.py::TestIngestWebsiteSummarizationBehavior
poetry run pytest tests/plugins/test_ingest_space.py::TestIngestSpaceSummarizationBehavior
```
