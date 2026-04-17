# Data Model: Space Ingest Context Enrichment & URI Tracking

**Feature Branch**: `022-space-ingest-context-uri`
**Date**: 2026-04-17

## Modified Entities

### DocumentMetadata (dataclass)

**File**: `core/domain/ingest_pipeline.py`

| Field | Type | Default | Change |
|-------|------|---------|--------|
| document_id | str | (required) | unchanged |
| source | str | (required) | unchanged |
| type | str | "knowledge" | unchanged |
| title | str | "" | unchanged |
| embedding_type | str | "knowledge" | unchanged |
| **uri** | **str \| None** | **None** | **NEW** |

**Relationships**: `DocumentMetadata` is embedded in `Document` and `Chunk` dataclasses. The `uri` field propagates from `Document.metadata` through chunking to `Chunk.metadata` without transformation.

### Stored Chunk Metadata (ChromaDB dict)

**File**: `core/domain/pipeline/steps.py` (`StoreStep`)

| Key | Type | Condition | Change |
|-----|------|-----------|--------|
| documentId | str | always | unchanged |
| source | str | always | unchanged |
| type | str | always | unchanged |
| title | str | always | unchanged |
| embeddingType | str | always | unchanged |
| chunkIndex | int | always | unchanged |
| **uri** | **str** | **only when non-null** | **NEW** |

## State Transitions

No state machine changes. Documents flow through the existing pipeline: Read -> Chunk -> Hash -> Detect -> Summarize -> Embed -> Store. The `uri` field is set at Read time and passively propagated.

## GraphQL Query Changes

The `SPACE_TREE_QUERY` and `_CALLOUT_FIELDS` templates now request `url` on all `profile` sub-selections. This is a read-only query change -- no mutations affected.
