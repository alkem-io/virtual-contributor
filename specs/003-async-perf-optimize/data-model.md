# Data Model: Async Performance Optimizations

**Feature**: 003-async-perf-optimize  
**Date**: 2026-04-02

## Entity Changes

This feature introduces no new entities, fields, or relationships. All optimizations are behavioral changes within existing code paths.

### Modified Internal Structures

#### chunks_by_doc_id (new transient variable)

**Location**: `core/domain/ingest_pipeline.py`, within `run_ingest_pipeline()`  
**Type**: `dict[str, list[Chunk]]`  
**Lifecycle**: Created during Step 2 (summarization), garbage-collected when function returns  
**Purpose**: Pre-built index mapping `document_id` to its chunks, replacing the O(n^2) linear scan pattern  

#### batch_embeddings (changed scope)

**Location**: `core/domain/ingest_pipeline.py`, within `run_ingest_pipeline()`  
**Previous**: Stored on `Chunk.embedding` field as intermediate state between separate embed and store loops  
**Current**: Held as a local variable within the combined embed+store loop iteration, used directly without intermediate storage on chunk objects  
**Impact**: The `Chunk.embedding` field is no longer populated during pipeline execution. This field was only read within the same function and is not part of any external interface.

## Unchanged Entities

The following entities are unmodified:

- **Document**: content + metadata, input to the pipeline
- **Chunk**: content fragment with metadata and chunk_index
- **DocumentMetadata**: document_id, source, type, title, embedding_type
- **IngestResult**: pipeline result with collection_name, counts, errors, success flag
- **Source** (guidance plugin): source reference with score for RAG responses

## Port/Adapter Interfaces

No changes to any port or adapter interface signatures. All optimizations are internal implementation changes:

- `EmbeddingsPort.embed()` -- signature unchanged
- `KnowledgeStorePort.query()` -- signature unchanged
- `KnowledgeStorePort.ingest()` -- signature unchanged
- `LLMPort.invoke()` -- signature unchanged
