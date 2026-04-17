# Data Model: Pipeline Reliability and BoK Resilience

**Feature Branch**: `story/020-pipeline-reliability`
**Date**: 2026-04-15

## Overview

This feature modifies behavior in existing pipeline steps and the LLM adapter. No new database tables, event schemas, or domain entities are introduced. No changes to stored data format or wire format. All constructor changes are additive with backward-compatible defaults.

## Entity: LangChainLLMAdapter (modified)

**File**: `core/adapters/langchain_llm.py`

### Behavior Change: invoke()

| Aspect | Before | After |
|--------|--------|-------|
| `asyncio.TimeoutError` handling | Caught by generic `except Exception`, retried up to 3 times | Caught explicitly, raises `TimeoutError` immediately without retry |
| Zombie thread impact per timeout | Up to 3 zombie threads (original + 2 retries) | Exactly 1 zombie thread (unavoidable with `asyncio.to_thread`) |
| Thread pool pressure per 8 concurrent timeouts | Up to 24 zombies (8 x 3 retries) | Exactly 8 zombies (8 x 1) |

### Exception Mapping

```text
asyncio.TimeoutError -> TimeoutError("LLM call timed out after {timeout}s")
ConnectionError/OSError -> ConnectionError (unchanged)
Other Exception -> retried 3x with exponential backoff (unchanged)
```

## Entity: _refine_summarize (modified)

**File**: `core/domain/pipeline/steps.py`

### Behavior Change: Partial Failure Resilience

| Aspect | Before | After |
|--------|--------|-------|
| Round N failure (N > 1) | Exception propagates, all prior work lost | Returns partial summary from round N-1, logs warning |
| Round 1 failure | Exception propagates | Exception propagates (unchanged) |
| Logging | None per round | Debug log per round: "Refine round {i+1}/{total} complete ({len} chars)" |

### Contract

```python
async def _refine_summarize(
    chunks: list[str],       # Unchanged
    llm_invoke,              # Unchanged
    max_length: int,         # Unchanged
    system_prompt: str,      # Unchanged
    initial_template: str,   # Unchanged
    subsequent_template: str,# Unchanged
) -> str:                    # Now may return partial summary on mid-stream failure
```

## Entity: DocumentSummaryStep (modified)

**File**: `core/domain/pipeline/steps.py`

### Behavior Change: execute()

| Aspect | Before | After |
|--------|--------|-------|
| `assert` for None summary/chunk | `AssertionError` on unexpected None | Graceful error: appends to `context.errors` |
| Background task lifecycle | Tasks created inline, awaited in a separate loop | Tasks created in `try` block, awaited in `finally` block via `asyncio.gather(*tasks, return_exceptions=True)` |
| Task orphaning on exception | Tasks created before the exception are never awaited | All tasks are always awaited regardless of exceptions |

### No Constructor Changes

The `DocumentSummaryStep` constructor is unchanged. The `embeddings_port` parameter was already optional.

## Entity: BodyOfKnowledgeSummaryStep (modified)

**File**: `core/domain/pipeline/steps.py`

### New Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_section_chars` | `int` | `30000` | Character limit for section grouping. Minimum enforced at 1000. Groups consecutive sections until this limit is reached to reduce refinement rounds |
| `knowledge_store_port` | `KnowledgeStorePort \| None` | `None` | Used for `_bok_exists()` check and inline BoK persistence |
| `embeddings_port` | `EmbeddingsPort \| None` | `None` | Used for inline BoK embedding before store |

### Existing Parameters (unchanged)

| Parameter | Type | Default |
|-----------|------|---------|
| `llm_port` | `LLMPort` | (required) |
| `summary_length` | `int` | `10000` |

### New Method: _bok_exists()

```python
async def _bok_exists(self, collection: str) -> bool
```

Queries the store for entries with `{"embeddingType": "body-of-knowledge"}`. Returns `True` if any exist. Returns `False` if no store port is configured or on query error.

### Section Grouping Logic

```text
Input: [section_1, section_2, ..., section_N]
Output: [group_1, group_2, ..., group_M] where M <= N

Each group_i = section_a + "\n\n---\n\n" + section_b + ... 
  such that sum(len(section)) <= max_section_chars

Grouping only applied when len(sections) > 1.
Log: "Grouped {N} sections into {M} refinement rounds (max_section_chars={limit})"
```

### Inline Persistence Logic

When both `self._embeddings` and `self._store` are not None:

1. Embed the BoK summary text.
2. Store with metadata: `{documentId, source, type, title, embeddingType, chunkIndex}`.
3. Storage ID: `"body-of-knowledge-summary-0"`.
4. Increment `context.chunks_stored`.
5. On failure: log warning, defer to EmbedStep/StoreStep.

The BoK chunk is always appended to `context.chunks` regardless of inline persist success.

## Entity: StoreStep (modified)

**File**: `core/domain/pipeline/steps.py`

### Behavior Change: Batch-Level Deduplication

| Aspect | Before | After |
|--------|--------|-------|
| Duplicate storage IDs in batch | Sent to ChromaDB, causing upsert of both (last wins in ChromaDB, but wastes bandwidth) | Deduplicated before sending: keeps last occurrence per ID |
| Dedup mechanism | None | `seen_ids: dict[str, int]` maps ID to last index; rebuild batch from unique indices |

### Dedup Logic

```text
For each batch:
  1. Build seen_ids = {storage_id: last_index}
  2. If len(seen_ids) < len(ids):  # duplicates exist
     a. unique_indices = sorted(seen_ids.values())
     b. Filter documents, metadatas, ids, embeddings to unique_indices
  3. Ingest the deduplicated batch
```

## Entity: ChangeDetectionStep (modified)

**File**: `core/domain/pipeline/steps.py`

### Bug Fix: _detect() Embeddings Check

| Aspect | Before | After |
|--------|--------|-------|
| Embeddings check | `if existing.embeddings` | `if existing.embeddings is not None and len(existing.embeddings) > 0` |
| Empty list `[]` behavior | Truthy in Python, enters loop with no items (harmless but incorrect) | Correctly treated as "no embeddings" |
| `None` behavior | Falsy, skips loop (correct) | Same: `is not None` is False, skips loop (correct) |

## Entity: main.py main() (modified)

**File**: `main.py`

### New: Explicit Thread Pool

```python
loop = asyncio.new_event_loop()
loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=32))
```

| Aspect | Before | After |
|--------|--------|-------|
| Thread pool | Default (`min(32, cpu_count + 4)`, typically 8-16) | Explicit 32 workers |
| Import | None | `import concurrent.futures` |

## Relationships

```text
main.py
  └── sets ThreadPoolExecutor(32) on event loop

LangChainLLMAdapter.invoke()
  └── asyncio.TimeoutError -> immediate TimeoutError (no retry)

_refine_summarize()
  └── used by DocumentSummaryStep and BodyOfKnowledgeSummaryStep
  └── returns partial summary on mid-stream failure

DocumentSummaryStep.execute()
  └── try/finally guarantees background task cleanup

BodyOfKnowledgeSummaryStep
  ├── _bok_exists() -> queries knowledge_store_port
  ├── section grouping -> reduces refinement rounds
  ├── inline persist -> embed + store via injected ports
  └── fallback -> appends chunk to context for deferred path

StoreStep.execute()
  └── dedup by storage ID within batch

ChangeDetectionStep._detect()
  └── fixed embeddings truthiness check

IngestWebsitePlugin / IngestSpacePlugin
  └── pass embeddings_port + knowledge_store_port to BodyOfKnowledgeSummaryStep
```

## State Transitions

No state machines affected. Changes are to runtime behavior within existing pipeline step execution. The `_bok_exists()` check is a read-only query during pipeline execution. Inline persistence is an idempotent upsert (same storage ID).
