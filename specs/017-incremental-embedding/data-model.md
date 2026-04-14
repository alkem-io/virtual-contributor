# Data Model: Incremental Embedding

**Feature Branch**: `story/1826-incremental-embedding`
**Date**: 2026-04-14

## Overview

This feature does not introduce new domain entities, database tables, event schemas, or data models. All changes are additive constructor parameters on an existing pipeline step class. The existing `Chunk`, `Document`, `DocumentMetadata`, `PipelineContext`, and `IngestResult` models are unchanged.

## Entity: DocumentSummaryStep (modified)

**File**: `core/domain/pipeline/steps.py`

### New Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `embeddings_port` | `EmbeddingsPort \| None` | `None` | Optional embeddings port for inline embedding after summarization |
| `embed_batch_size` | `int` | `50` | Batch size for inline embedding calls (matches `EmbedStep` default) |

### New Private Method

| Method | Signature | Description |
|--------|-----------|-------------|
| `_embed_document_chunks` | `async (chunks: list[Chunk], context: PipelineContext, doc_id: str) -> None` | Embeds a document's chunks in batches, skipping already-embedded chunks, capturing errors in `context.errors` |

### Changed Behavior in `execute()`

- **Before**: After producing a document's summary, appends summary chunk to `context.chunks` and moves to next document.
- **After**: After producing a document's summary, appends summary chunk to `context.chunks`, then (when `embeddings_port` is not None) embeds all of that document's content chunks plus the summary chunk via `_embed_document_chunks()`.

## Entity: IngestSpacePlugin (modified)

**File**: `plugins/ingest_space/plugin.py`

### Changed Behavior

- `DocumentSummaryStep` constructor call now includes `embeddings_port=self._embeddings`.
- No new constructor parameters on the plugin itself.

## Entity: IngestWebsitePlugin (modified)

**File**: `plugins/ingest_website/plugin.py`

### Changed Behavior

- `DocumentSummaryStep` constructor call now includes `embeddings_port=self._embeddings`.
- No new constructor parameters on the plugin itself.

## Relationships

```text
DocumentSummaryStep
  ├── uses → LLMPort (for summarization, unchanged)
  ├── uses → EmbeddingsPort (NEW, optional, for inline embedding)
  └── writes → PipelineContext.chunks (summary chunks, unchanged)
                PipelineContext.errors (embedding errors, unchanged mechanism)

EmbedStep
  └── uses → EmbeddingsPort (unchanged, safety net for un-embedded chunks)

IngestSpacePlugin
  └── passes → self._embeddings to DocumentSummaryStep(embeddings_port=...)

IngestWebsitePlugin
  └── passes → self._embeddings to DocumentSummaryStep(embeddings_port=...)
```

## State Transitions

No state machines affected. The `Chunk.embedding` field transitions from `None` to a `list[float]` either during `DocumentSummaryStep` (inline) or during `EmbedStep` (safety net), but this is the same transition that existed before — only the timing changes.
