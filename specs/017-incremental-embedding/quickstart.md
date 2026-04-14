# Quickstart: Incremental Embedding

**Feature Branch**: `story/1826-incremental-embedding`
**Date**: 2026-04-14

## What This Feature Does

Reduces ingest pipeline wall-clock time by embedding each document's chunks immediately after its summary is produced, instead of waiting for all documents to finish summarization before any embedding begins. This overlaps LLM-bound summarization I/O with GPU-bound embedding I/O.

The change is fully transparent: no new environment variables, no configuration changes, no API changes. Both `ingest_space` and `ingest_website` plugins automatically use incremental embedding.

## How It Works

### Before (sequential)

```
DocumentSummaryStep: summarize doc1, doc2, doc3, ..., docN
EmbedStep: embed ALL chunks from ALL documents
```

### After (incremental)

```
DocumentSummaryStep:
  summarize doc1 -> embed doc1 chunks
  summarize doc2 -> embed doc2 chunks
  summarize doc3 -> embed doc3 chunks
  ...
EmbedStep: embed remaining chunks (BoK summary, below-threshold docs, failed inline)
```

## Quick Verification

### 1. Run ingest and observe logs

```bash
export PLUGIN_TYPE=ingest-space
poetry run python main.py

# Look for log lines:
#   INFO: Summarized document <doc_id>
#   INFO: Inline-embedded N/M chunks for document <doc_id>
# These appear per-document, interleaved with summarization.
```

### 2. Verify EmbedStep safety net

```bash
# After inline embedding, EmbedStep should only embed:
# - BoK summary chunk (produced after DocumentSummaryStep)
# - Below-threshold document chunks (not summarized)
# - Any chunks where inline embedding failed

# Look for:
#   INFO: EmbedStep: embedded N chunks (should be small if inline worked)
```

### 3. Run tests

```bash
poetry run pytest tests/core/domain/test_pipeline_steps.py -k "IncrementalEmbedding" -v

# Expected: 6 tests pass
# - test_inline_embedding_after_summary
# - test_embed_step_skips_already_embedded
# - test_inline_embed_error_handling
# - test_no_embeddings_port_backward_compat
# - test_below_threshold_not_embedded_inline
# - test_full_pipeline_with_incremental_embedding
```

## Files Changed

| File | Change |
|------|--------|
| `core/domain/pipeline/steps.py` | `DocumentSummaryStep`: +`embeddings_port` param, +`_embed_document_chunks()` helper, inline embedding in `execute()` |
| `plugins/ingest_space/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` |
| `plugins/ingest_website/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` |
| `tests/core/domain/test_pipeline_steps.py` | 6 new tests in `TestDocumentSummaryStepIncrementalEmbedding` |

## Contracts

No external interface changes:
- **EmbeddingsPort**: Unchanged (reused by `DocumentSummaryStep`)
- **LLMPort**: Unchanged
- **PluginContract**: Unchanged (no new lifecycle methods)
- **Event schemas**: Unchanged
- **Pipeline engine**: Unchanged
- **PipelineContext**: Unchanged
