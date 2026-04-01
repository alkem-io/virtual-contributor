# Research: Async Performance Optimizations

**Feature**: 003-async-perf-optimize  
**Date**: 2026-04-02

## Research Tasks

### R1: asyncio.gather() for concurrent coroutines

**Decision**: Use `asyncio.gather()` with default `return_exceptions=False` for parallelizing independent async operations.

**Rationale**: `asyncio.gather()` is the standard Python mechanism for running multiple coroutines concurrently on the same event loop. It is well-suited for independent I/O-bound operations like LLM calls and database queries. Since error handling is done within each inner coroutine (via try/except), `return_exceptions=False` is appropriate -- exceptions are caught before they propagate to gather.

**Alternatives considered**:
- `asyncio.TaskGroup` (Python 3.11+): Provides structured concurrency with automatic cancellation on first error. Rejected because the use cases here need independent error handling per task (one failed summarization should not cancel others), which TaskGroup does not support without workarounds.
- `asyncio.create_task()` with manual tracking: More verbose with no benefit over `gather()` for this use case.
- `asyncio.Semaphore`-bounded gather: Considered for rate-limiting concurrent LLM calls. Deferred as unnecessary complexity -- if providers rate-limit, the retry logic in adapters handles it.

### R2: Dictionary-based chunk lookup vs linear scan

**Decision**: Replace per-document `[c for c in all_chunks if c.metadata.document_id == doc.metadata.document_id]` with a pre-built `dict[str, list[Chunk]]` keyed by `document_id`.

**Rationale**: The linear scan pattern is O(D * C) where D = documents and C = total chunks. The dictionary approach is O(C) to build + O(1) per lookup = O(C + D) total. For typical workloads (50+ documents, 500+ chunks), this is a significant improvement.

**Alternatives considered**:
- `collections.defaultdict(list)`: Equivalent to `dict.setdefault()` but requires an extra import. Either approach is correct; `setdefault` was chosen for simplicity.
- Grouping during chunking (Step 1): Would avoid a separate grouping pass but couples chunking logic with summarization prep. Rejected for separation of concerns.

### R3: httpx.AsyncClient connection reuse across retries

**Decision**: Move `async with httpx.AsyncClient(...)` outside the retry loop so a single client instance is reused across all retry attempts.

**Rationale**: Creating a new `httpx.AsyncClient` per retry attempt incurs TCP connection setup + TLS handshake overhead on each retry. Moving it outside the loop enables HTTP/1.1 keep-alive connection reuse. The client is still properly closed via the `async with` context manager after all retries complete or succeed.

**Alternatives considered**:
- Persistent client as instance variable: Would enable connection reuse across multiple `embed()` or `query()` calls, not just across retries. This is a larger refactor requiring lifecycle management (explicit connect/disconnect). Deferred to a future optimization.
- `httpx.AsyncClient` with connection pooling config: Could tune `limits=httpx.Limits(max_connections=...)`. Not needed for the single-request-with-retries pattern.

### R4: Combining embed and store batch loops

**Decision**: Merge the separate "embed in batches" and "store in batches" loops into a single loop that embeds a batch then immediately stores it.

**Rationale**: The original code iterates through all chunks twice (once for embedding, once for storage), computing `[c.summary or c.content for c in batch]` in both passes. The combined loop computes `texts` once per batch and uses `batch_embeddings` directly from the embed call, eliminating the need to store embeddings on chunk objects as intermediate state.

**Alternatives considered**:
- Keep separate loops but pre-compute shared data: Would reduce redundancy but still requires two passes. The combined loop is simpler.
- Fully parallel embed-then-store across batches: Could use `asyncio.gather()` to embed all batches concurrently, then store. Rejected because embedding providers typically have rate limits and the sequential-per-batch approach is already efficient with properly sized batches.

### R5: Non-blocking DNS resolution with asyncio.to_thread()

**Decision**: Wrap `socket.getaddrinfo()` with `await asyncio.to_thread()` in the SSRF validation function.

**Rationale**: `socket.getaddrinfo()` is a synchronous system call that performs DNS resolution. In an async context, it blocks the event loop thread, potentially stalling all concurrent operations. `asyncio.to_thread()` offloads it to the default thread pool executor, keeping the event loop responsive.

**Alternatives considered**:
- `aiodns` library: Purpose-built async DNS resolver. Would add a new dependency for a single call site. Rejected as overkill.
- `loop.getaddrinfo()`: asyncio's built-in async DNS resolution. Also viable but `asyncio.to_thread()` is more explicit about what's happening.
- Leave synchronous: The function is called once per crawl invocation (for the base URL only). Impact is minimal in practice but wrapping it is a low-cost defensive improvement.
