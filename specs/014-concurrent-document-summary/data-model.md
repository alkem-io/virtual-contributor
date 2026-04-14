# Data Model: Concurrent Document Summarization in DocumentSummaryStep

**Feature Branch**: `story/1823-implement-actual-concurrency-in-document-summary-step`
**Date**: 2026-04-14

## Overview

This feature modifies the internal execution strategy of `DocumentSummaryStep` without changing any external data models, database schemas, event schemas, or port interfaces. One new module-private dataclass is introduced as an internal implementation detail.

## Entity: _SummaryResult (new, module-private)

**File**: `core/domain/pipeline/steps.py`

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | `str` | (required) | Document ID being summarized |
| `summary` | `str \| None` | `None` | Generated summary text (None on failure) |
| `chunk` | `Chunk \| None` | `None` | Summary chunk ready for appending to context (None on failure) |
| `error` | `str \| None` | `None` | Error message (None on success) |

**Scope**: Module-private (underscore prefix). Used only within `DocumentSummaryStep.execute()` as a return type from `_summarize_one()` coroutines.

**Purpose**: Decouples concurrent computation from sequential context mutation. Each concurrent task returns a `_SummaryResult` instead of mutating `PipelineContext` directly.

## Entity: DocumentSummaryStep (modified)

**File**: `core/domain/pipeline/steps.py`

### Changed Behavior

- **Before**: `execute()` iterates sequentially over qualifying documents in a `for` loop, mutating `PipelineContext` inline
- **After**: `execute()` creates an `asyncio.Semaphore`, fans out concurrent `_summarize_one()` coroutines via `asyncio.gather`, then applies `_SummaryResult` entries to `PipelineContext` sequentially

### Constructor Parameters (unchanged)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm_port` | `LLMPort` | (required) | LLM adapter for summarization |
| `summary_length` | `int` | `10000` | Target summary length |
| `concurrency` | `int` | `8` | Max concurrent summarizations (now actually used) |
| `chunk_threshold` | `int` | `4` | Min chunks for a document to qualify |

## Unchanged Entities

- **PipelineContext**: No structural changes. Same fields (`document_summaries`, `chunks`, `errors`) used with same semantics.
- **Chunk**: Unchanged.
- **DocumentMetadata**: Unchanged.
- **LLMPort**: Unchanged. No new methods or parameters.

## Relationships

```text
DocumentSummaryStep.execute()
    creates -> asyncio.Semaphore(concurrency)
    fans out -> _summarize_one() coroutines (one per qualifying document)
    gathers -> list[_SummaryResult] via asyncio.gather
    applies -> results to PipelineContext in input order
```

## State Transitions

No state machines affected. The change is purely in execution strategy (sequential to concurrent), not in data flow or state management.
