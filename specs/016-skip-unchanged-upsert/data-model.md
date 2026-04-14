# Data Model: Skip Upsert for Unchanged Chunks in StoreStep

**Feature Branch**: `story/1825-skip-upsert-unchanged-chunks`
**Date**: 2026-04-14

## Overview

This feature introduces no new data structures, entities, or schema changes. It leverages two existing data structures already in the pipeline to filter unchanged chunks before upsert.

## Entity: PipelineContext (unchanged)

**File**: `core/domain/ingest_pipeline.py`

### Relevant Existing Fields

| Field | Type | Description |
|-------|------|-------------|
| `unchanged_chunk_hashes` | `set[str]` | Content hashes of chunks identified as unchanged by ChangeDetectionStep. Default: empty set. |
| `chunks` | `list[Chunk]` | All chunks in the pipeline, including changed, unchanged, and summary chunks. |
| `chunks_stored` | `int` | Counter incremented by StoreStep for each chunk actually written to the store. |
| `change_detection_ran` | `bool` | Whether ChangeDetectionStep executed. When False, `unchanged_chunk_hashes` is empty. |

### Behavioral Change

- **Before**: `chunks_stored` counted all chunks with embeddings.
- **After**: `chunks_stored` counts only chunks with embeddings whose `content_hash` is NOT in `unchanged_chunk_hashes`.

## Entity: Chunk (unchanged)

**File**: `core/domain/ingest_pipeline.py`

### Relevant Existing Fields

| Field | Type | Description |
|-------|------|-------------|
| `content_hash` | `str \| None` | SHA-256 hash of chunk content. Computed by ContentHashStep. `None` for summary and BoK chunks. |
| `embedding` | `list[float] \| None` | Embedding vector. Pre-loaded by ChangeDetectionStep for unchanged chunks, computed by EmbedStep for changed chunks. `None` if embedding failed. |

## Entity: StoreStep (modified behavior)

**File**: `core/domain/pipeline/steps.py`

### Changed Behavior

- **Before**: `storable = [c for c in context.chunks if c.embedding is not None]`
- **After**: `storable = [c for c in context.chunks if c.embedding is not None and c.content_hash not in context.unchanged_chunk_hashes]`

### New Logging

| Log Level | Condition | Message |
|-----------|-----------|---------|
| INFO | `unchanged_skipped > 0` | `"StoreStep: skipped %d unchanged chunks"` |

The existing error log for chunks without embeddings is unchanged in purpose but now correctly counts only no-embedding chunks (previously it conflated no-embedding and unchanged counts).

## Relationships

```text
ChangeDetectionStep
  └── populates → PipelineContext.unchanged_chunk_hashes

ContentHashStep
  └── populates → Chunk.content_hash

StoreStep
  ├── reads → PipelineContext.unchanged_chunk_hashes
  ├── reads → Chunk.content_hash
  ├── filters → chunks where content_hash in unchanged_chunk_hashes
  └── calls → KnowledgeStorePort.ingest() for remaining chunks only
```

## State Transitions

No state machines affected. The filter is applied during a single `StoreStep.execute()` call with no persistent state changes beyond the pipeline context counters.
