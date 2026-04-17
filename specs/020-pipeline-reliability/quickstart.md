# Quickstart: Pipeline Reliability and BoK Resilience

**Feature Branch**: `story/020-pipeline-reliability`
**Date**: 2026-04-15

## What Changed

1. **Thread pool deadlock prevention** -- The event loop now uses an explicit `ThreadPoolExecutor(max_workers=32)` and the LLM adapter no longer retries on timeout, preventing zombie thread accumulation that exhausts the pool.

2. **Background task safety** -- `DocumentSummaryStep` wraps background embedding tasks in `try/finally` so they are always awaited, even when exceptions occur during result processing.

3. **Partial BoK fallback** -- `_refine_summarize()` returns a partial summary from completed rounds when a later round fails, instead of discarding all work.

4. **BoK section grouping** -- `BodyOfKnowledgeSummaryStep` groups sections by character count (default 30000) to reduce the number of sequential LLM calls. A 20-page website that previously needed 20 refinement rounds may now need only 2-3.

5. **BoK inline persistence** -- When both `embeddings_port` and `knowledge_store_port` are provided, the BoK is embedded and stored immediately after generation, protecting the LLM work against downstream step failures.

6. **BoK skip on unchanged corpus** -- `BodyOfKnowledgeSummaryStep` checks the store for an existing BoK entry and skips regeneration when change detection found no changes.

7. **StoreStep batch dedup** -- Duplicate storage IDs within a batch (from identical content hashes across documents) are deduplicated before sending to ChromaDB.

8. **Embeddings truthiness fix** -- `ChangeDetectionStep._detect()` now checks `is not None and len(...) > 0` instead of bare `if existing.embeddings`, correctly handling empty lists.

## How to Verify

### 1. Thread pool configuration

After starting the service, the log output shows the event loop using an explicit executor. To verify programmatically:

```python
# In a test or debug session:
import asyncio
loop = asyncio.get_event_loop()
executor = loop._default_executor
assert executor._max_workers == 32
```

### 2. Timeout behavior (no retry on timeout)

```python
# The LLM adapter raises TimeoutError immediately on asyncio.TimeoutError:
from core.adapters.langchain_llm import LangChainLLMAdapter

# With a mock LLM that sleeps longer than the timeout:
adapter = LangChainLLMAdapter(slow_mock_llm, timeout=0.1)
try:
    await adapter.invoke([{"role": "human", "content": "test"}])
except TimeoutError:
    pass  # Expected: immediate raise, no retry
```

### 3. Partial summary behavior

```python
# _refine_summarize returns partial summary when mid-stream failure occurs:
call_count = 0
async def failing_llm(messages):
    nonlocal call_count
    call_count += 1
    if call_count >= 3:
        raise RuntimeError("LLM error")
    return f"Summary round {call_count}"

result = await _refine_summarize(
    ["chunk1", "chunk2", "chunk3", "chunk4"],
    failing_llm, 1000,
    "system", "initial {budget} {text}", "subsequent {summary} {text} {budget}",
)
# result contains partial summary from round 2
assert "round 2" in result
```

### 4. BoK inline persistence

When running an ingest pipeline with both embeddings and knowledge store configured, the log output shows:

```
INFO: BoK summary embedded and stored inline
```

If inline persist fails, the log shows:

```
WARNING: BoK inline persist failed, deferring to finalize EmbedStep/StoreStep: ...
```

### 5. BoK skip on unchanged corpus

Ingest a corpus, then re-ingest the same corpus:

```bash
# First ingest (BoK generated)
# Log: "Generating body-of-knowledge summary (N sections)"

# Second ingest (unchanged)
# No BoK generation log -- step returns immediately
```

### 6. Run tests

```bash
# All pipeline step tests
poetry run pytest tests/core/domain/test_pipeline_steps.py -v

# Specific test classes related to this feature
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestBodyOfKnowledgeSummaryStep -v
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestBoKSummaryStepDedup -v
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestStoreStepDedup -v
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestDocumentSummaryStepConcurrency -v
```

## Files Changed

| File | Change |
|------|--------|
| `core/adapters/langchain_llm.py` | `invoke()` catches `asyncio.TimeoutError` explicitly and raises `TimeoutError` without retry |
| `core/domain/pipeline/steps.py` | `_refine_summarize` partial fallback; `DocumentSummaryStep` try/finally for tasks; `BodyOfKnowledgeSummaryStep` adds `max_section_chars`, `knowledge_store_port`, `embeddings_port`, `_bok_exists()`, section grouping, inline persist; `StoreStep` batch dedup; `ChangeDetectionStep` embeddings fix |
| `main.py` | Explicit `ThreadPoolExecutor(max_workers=32)` on event loop |
| `plugins/ingest_website/plugin.py` | Pass `embeddings_port` and `knowledge_store_port` to `BodyOfKnowledgeSummaryStep` |
| `plugins/ingest_space/plugin.py` | Pass `embeddings_port` and `knowledge_store_port` to `BodyOfKnowledgeSummaryStep` |
| `tests/core/domain/test_pipeline_steps.py` | BoK skip test pre-populates `MockKnowledgeStorePort` with existing BoK entry |

## Contracts

No external interface changes:

- **LLMPort**: Unchanged
- **EmbeddingsPort**: Unchanged
- **KnowledgeStorePort**: Unchanged
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
- **IngestEngine / PipelineStep protocol**: Unchanged
- **BodyOfKnowledgeSummaryStep constructor**: Additive only (new params have defaults)
