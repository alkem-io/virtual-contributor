# Quickstart: Async Performance Optimizations

**Feature**: 003-async-perf-optimize  
**Date**: 2026-04-02

## Overview

This feature applies 7 performance optimizations across 5 files. All changes are internal -- no configuration, environment variables, or external interfaces change.

## What Changed

| # | File | Optimization | Impact |
|---|------|-------------|--------|
| 1 | `core/domain/ingest_pipeline.py` | Parallel document summarization via `asyncio.gather()` | ~Nx faster for N documents |
| 2 | `core/domain/ingest_pipeline.py` | O(n) chunk lookup via pre-built dict | Eliminates quadratic scaling |
| 3 | `core/domain/ingest_pipeline.py` | Combined embed+store batch loop | Single iteration, no intermediate state |
| 4 | `plugins/guidance/plugin.py` | Parallel collection queries via `asyncio.gather()` | ~3x faster query phase |
| 5 | `core/adapters/openai_compatible_embeddings.py` | `httpx.AsyncClient` reuse across retries | Eliminates connection overhead |
| 6 | `plugins/ingest_space/graphql_client.py` | `httpx.AsyncClient` reuse across retries | Eliminates connection overhead |
| 7 | `plugins/ingest_website/crawler.py` | Non-blocking DNS via `asyncio.to_thread()` | Prevents event loop blocking |

## Verification

Run existing tests to verify no behavioral changes:

```bash
# Lint
uvx ruff check core/ plugins/ tests/

# Tests
pytest tests/ -x -q
```

No new configuration or deployment steps required. The optimizations are transparent to all callers.

## Key Design Decisions

1. **`asyncio.gather()` over `TaskGroup`**: TaskGroup cancels all tasks on first error, which is undesirable here -- we want independent error handling per operation.
2. **Client reuse within method, not across calls**: A larger refactor (persistent client as instance variable) was deferred. Current scope limits connection reuse to retry attempts within a single method call.
3. **No concurrency limits on parallel summarization**: LLM provider rate limiting is handled by adapter retry logic. If needed, a semaphore can be added later.
