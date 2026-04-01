# Feature Specification: Async Performance Optimizations

**Feature Branch**: `003-async-perf-optimize`  
**Created**: 2026-04-02  
**Status**: Draft  
**Input**: User description: "Performance optimizations across the codebase covering parallel code execution, connection reuse, algorithmic improvements, and non-blocking I/O."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Faster Document Ingestion (Priority: P1)

As a platform operator ingesting a large knowledge base with many documents, the system processes document summarizations and embeddings significantly faster by executing independent operations concurrently rather than sequentially.

**Why this priority**: Document ingestion is the most resource-intensive pipeline in the system. With N documents requiring LLM summarization, sequential processing creates a linear bottleneck. Parallelizing this operation provides the single largest performance gain, scaling improvement with the number of documents.

**Independent Test**: Can be tested by ingesting a batch of 10+ multi-chunk documents with summarization enabled and measuring total pipeline duration compared to sequential baseline.

**Acceptance Scenarios**:

1. **Given** a batch of 10 documents each exceeding the summary length threshold, **When** the ingest pipeline runs with summarization enabled, **Then** all document summarizations execute concurrently and total summarization time is bounded by the slowest single document rather than the sum of all documents.
2. **Given** a batch of documents during ingestion, **When** one document's summarization fails, **Then** the error is captured and all other documents still complete summarization successfully.
3. **Given** a batch of documents during ingestion, **When** chunks are looked up per document, **Then** the lookup completes in linear time regardless of the total number of chunks.

---

### User Story 2 - Faster Guidance Responses (Priority: P1)

As a user asking a question through the guidance plugin, the system retrieves relevant knowledge from all configured collections concurrently, reducing response latency.

**Why this priority**: Guidance responses are user-facing and latency-sensitive. With 3 knowledge collections queried sequentially, users experience approximately 3x the necessary wait time. Parallelizing these independent queries directly improves user experience.

**Independent Test**: Can be tested by sending a guidance query and measuring the time spent in the knowledge store query phase compared to sequential baseline.

**Acceptance Scenarios**:

1. **Given** a user question submitted to the guidance plugin, **When** the system queries 3 knowledge collections, **Then** all 3 queries execute concurrently and total query time is bounded by the slowest single collection rather than the sum of all collections.
2. **Given** a user question submitted to the guidance plugin, **When** one collection query fails, **Then** results from the other collections are still returned and the failure is logged.

---

### User Story 3 - Efficient Network Connection Usage (Priority: P2)

As a system handling embedding requests and GraphQL queries with retry logic, the system reuses network connections across retry attempts rather than creating new connections each time, reducing overhead from repeated TLS handshakes and connection setup.

**Why this priority**: Connection reuse eliminates unnecessary overhead during retries. While retries are infrequent in the happy path, when they do occur (e.g., transient network issues), connection reuse ensures faster recovery and lower resource consumption.

**Independent Test**: Can be tested by triggering retry scenarios in embedding and GraphQL adapters and verifying that connections are reused across attempts.

**Acceptance Scenarios**:

1. **Given** an embedding request that fails on the first attempt, **When** the system retries, **Then** the retry uses the same underlying network connection rather than establishing a new one.
2. **Given** a GraphQL query that fails on the first attempt, **When** the system retries, **Then** the retry uses the same underlying network connection.
3. **Given** a successful request on the first attempt, **Then** the connection is properly closed after the response is received.

---

### User Story 4 - Non-blocking Web Crawling (Priority: P3)

As the system crawling external websites for ingestion, DNS resolution does not block the async event loop, preventing stalls that could affect other concurrent operations.

**Why this priority**: While DNS resolution is generally fast, it is a synchronous system call that can block the event loop for hundreds of milliseconds on slow DNS servers. Offloading it to a thread pool ensures the event loop remains responsive.

**Independent Test**: Can be tested by initiating a crawl against a URL requiring DNS resolution and verifying the event loop is not blocked during the resolution phase.

**Acceptance Scenarios**:

1. **Given** a URL with a hostname requiring DNS resolution, **When** the crawler validates the URL for SSRF safety, **Then** the DNS resolution executes without blocking the async event loop.
2. **Given** a URL that resolves to a private or reserved IP, **Then** the SSRF protection still correctly blocks the request.

---

### Edge Cases

- What happens when all documents in a batch fail summarization concurrently? The pipeline collects all errors and continues to the embed/store phase with unsummarized chunks.
- What happens when all 3 knowledge collection queries fail simultaneously? The guidance plugin returns a response based on "No relevant context found."
- What happens when an embedding batch fails? The pipeline skips storage for that specific batch and continues with remaining batches.
- What happens when the network connection is dropped between retries? The connection context manager handles cleanup gracefully and the outer retry logic surfaces the error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST execute document summarizations concurrently across all qualifying documents in an ingestion batch.
- **FR-002**: System MUST use a pre-built index for chunk-to-document lookups, avoiding repeated scans of the full chunk list per document.
- **FR-003**: System MUST perform embedding and storage in a single pass per batch, computing text representations once and reusing them for both operations.
- **FR-004**: System MUST execute knowledge store collection queries concurrently across all configured collections in the guidance plugin.
- **FR-005**: System MUST reuse network connections across retry attempts in the embedding adapter.
- **FR-006**: System MUST reuse network connections across retry attempts in the GraphQL client.
- **FR-007**: System MUST perform DNS resolution without blocking the async event loop during URL safety validation in the web crawler.
- **FR-008**: System MUST preserve existing error isolation -- individual failures in concurrent operations must not prevent other operations from completing.
- **FR-009**: System MUST maintain identical functional output (same results, same error messages) as before the optimizations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Document ingestion with summarization for N documents completes in approximately 1/Nth of the previous sequential duration (bounded by the slowest single summarization).
- **SC-002**: Guidance plugin query phase completes in approximately 1/3 of the previous sequential duration (bounded by the slowest single collection query).
- **SC-003**: Document chunk lookups during summarization scale linearly with the number of chunks, not quadratically.
- **SC-004**: Embedding and storage phases iterate through chunks once instead of twice, eliminating redundant batch computation.
- **SC-005**: Network retry scenarios complete without redundant connection setup overhead.
- **SC-006**: All existing tests continue to pass with identical behavior.

## Assumptions

- The LLM provider can handle concurrent summarization requests without rate-limiting issues for typical batch sizes.
- The knowledge store can handle concurrent query requests across different collections.
- The embedding provider's endpoint supports connection keep-alive for reuse across retries.
- DNS resolution latency is generally low but may spike unpredictably; offloading to a thread pool is a defensive measure.
- Cooperative concurrency ensures thread safety for shared mutable state (e.g., error lists) without explicit locking.
- These optimizations are backward-compatible and require no changes to external interfaces, configuration, or deployment.
