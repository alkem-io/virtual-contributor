# Feature Specification: Document Processing Reliability & Alignment

**Feature Branch**: `fix/documents`  
**Created**: 2026-04-06  
**Status**: Implemented  
**Input**: Fix document processing reliability — align pipeline behavior with original repo (prompts, summary length, chunk IDs), harden async execution to preserve RabbitMQ heartbeats, add message retry logic, improve guidance plugin result quality, restore `[source:N]` prefix formatting on retrieved chunks, add score-threshold source filtering, reduce expert retrieval count, and deduplicate sources in both plugins.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stable Document Ingestion Under Load (Priority: P1)

When a knowledge base with many documents is ingested, the system must complete the full pipeline without dropping RabbitMQ connections. Long-running LLM calls during summarization previously blocked the event loop, causing heartbeat timeouts and connection drops mid-ingestion.

**Why this priority**: Connection drops during ingestion cause silent data loss — documents are partially ingested with no retry, and the operator has no visibility into which documents succeeded or failed. This is the root cause of production ingestion failures.

**Independent Test**: Ingest a knowledge base with 10+ documents where each document has >3 chunks (triggering summarization). All documents complete ingestion without RabbitMQ connection errors in the logs.

**Acceptance Scenarios**:

1. **Given** a knowledge base with 15 documents requiring summarization, **When** the pipeline processes them, **Then** the RabbitMQ connection stays alive throughout (no heartbeat timeout errors in logs).
2. **Given** an LLM call that takes 90 seconds, **When** it executes during pipeline processing, **Then** the event loop remains responsive and RabbitMQ heartbeats continue on schedule.
3. **Given** a message that fails processing, **When** the failure occurs on the first attempt, **Then** the message is republished with an incremented retry count header and processed again (up to 3 attempts).
4. **Given** a message that has failed 3 times, **When** the third attempt also fails, **Then** the message is discarded and an error is logged with the failure reason.

---

### User Story 2 - High-Quality Summarization Aligned with Original System (Priority: P1)

Document and body-of-knowledge summaries must match the quality and format of the original virtual-contributor-ingest-website system. The previous implementation used generic prompts and a 2000-character budget that produced thin, low-information summaries.

**Why this priority**: Summary quality directly affects retrieval accuracy. Thin summaries lose entity information (names, dates, URLs), causing the guidance plugin to return irrelevant results for specific queries.

**Independent Test**: Ingest a document with 10+ chunks containing specific entities (names, dates, numbers). The generated summary preserves all key entities in structured markdown format with at least 5000 characters of content.

**Acceptance Scenarios**:

1. **Given** a document with specific entities (names, dates, URLs, technical terms), **When** the pipeline generates a summary, **Then** the summary preserves all key entities in structured markdown with headers and bullet points.
2. **Given** a multi-document knowledge base, **When** the body-of-knowledge overview is generated, **Then** it captures cross-document themes, temporal scope, and key entities in structured markdown.
3. **Given** the summarization budget, **When** early chunks are processed, **Then** they receive ~40% of the 10000-character target (4000 chars), scaling linearly to 100% for later chunks.
4. **Given** a single section to summarize, **When** processed, **Then** it receives the full 100% budget (10000 chars).

---

### User Story 3 - Correct Chunk ID Format for ChromaDB Compatibility (Priority: P2)

Chunk IDs stored in ChromaDB must follow the original repo's naming convention so that existing retrieval logic, re-ingestion operations, and any tooling that references chunks by ID continue to work correctly.

**Why this priority**: ID format mismatches break re-ingestion (duplicate entries instead of overwrites) and any external tooling that queries ChromaDB by document ID patterns.

**Independent Test**: Ingest a document with 5 chunks. Verify that ChromaDB entries use `{document_id}-chunk{index}` as the documentId for raw chunks, and the plain document_id for summary/BoK entries.

**Acceptance Scenarios**:

1. **Given** a raw chunk with document_id "my-doc" and chunk_index 0, **When** stored, **Then** its ChromaDB documentId is "my-doc-chunk0" and its entry ID is "my-doc-chunk0-0".
2. **Given** a summary chunk with document_id "my-doc-summary", **When** stored, **Then** its ChromaDB documentId is "my-doc-summary" (unchanged) and its entry ID is "my-doc-summary-0".
3. **Given** a body-of-knowledge chunk, **When** stored, **Then** its ChromaDB documentId is "body-of-knowledge-summary" (unchanged).

---

### User Story 4 - Source Attribution and Filtering in Retrieval (Priority: P2)

When a user asks a question, retrieved chunks must be prefixed with `[source:N]` indices so the LLM can reference and attribute individual sources. Low-relevance chunks must be filtered out before reaching the LLM, and results must be deduplicated by source URL in both guidance and expert plugins. The original engines had `combine_query_results()` for `[source:N]` formatting and LLM-based source scoring (0-10 scale); the port removed both.

**Why this priority**: Without source indices, the LLM cannot attribute answers to specific sources. Without filtering, irrelevant chunks waste context window space and degrade answer quality. Without deduplication, multiple chunks from the same page dominate results.

**Independent Test**: Query a knowledge base. Verify the LLM prompt contains `[source:0]`, `[source:1]` etc. prefixes. Verify low-relevance chunks (score < 0.3) are excluded. Verify no duplicate source URLs appear in the response sources list.

**Acceptance Scenarios**:

1. **Given** retrieved chunks from any plugin, **When** assembled into the LLM prompt, **Then** each chunk is prefixed with `[source:N]` where N is a zero-based contiguous index.
2. **Given** a chunk with a relevance score below 0.3, **When** results are processed, **Then** the chunk is excluded from both the LLM prompt and the sources list.
3. **Given** a query that matches 3 chunks from the same source URL, **When** the guidance plugin processes results, **Then** only the highest-scoring chunk from that source is included.
4. **Given** a query with many matching results across collections, **When** results are returned, **Then** they are sorted by relevance score (highest first) and limited to 5.
5. **Given** multiple chunks from the same source URL in the expert plugin, **When** the sources list is built, **Then** only the first occurrence per source URL is included (matching the original `{doc["source"]: doc for doc in sources}.values()` deduplication).
6. **Given** a result with a source metadata field, **When** either plugin constructs the Source object, **Then** the `uri` field is set to the source URL.

---

### User Story 5 - Reduced Expert Retrieval Count (Priority: P2)

The expert plugin must retrieve fewer chunks to avoid context overload. The original expert engine retrieved 4 results; the port increased this to 10. With 9000-character space chunks, 10 results means ~90,000 characters (~22,500 tokens) of context, leaving insufficient room for the system prompt and response in a 32K context window.

**Why this priority**: Context overload risks silent truncation or degraded answers. Reducing to 5 results keeps context within safe limits while still providing sufficient knowledge.

**Independent Test**: Query the expert plugin. Verify it requests 5 results from ChromaDB (configurable via `RETRIEVAL_N_RESULTS` env var).

**Acceptance Scenarios**:

1. **Given** the default configuration, **When** the expert plugin queries the knowledge store, **Then** it requests 5 results (both graph and simple RAG paths).
2. **Given** `RETRIEVAL_N_RESULTS` is set to 3, **When** the expert plugin queries, **Then** it requests 3 results.
3. **Given** the score threshold filters out some results, **When** combined with the reduced n_results, **Then** the LLM prompt contains at most 5 chunks, each above the relevance threshold.

---

### User Story 6 - Configurable Summarization Pipeline (Priority: P3)

Operators must be able to disable summarization steps for use cases where only raw chunk ingestion is needed (e.g., fast re-indexing, testing, or resource-constrained environments).

**Why this priority**: Summarization is the most expensive pipeline step (multiple LLM calls per document). Operators need the ability to skip it when not needed without code changes.

**Independent Test**: Set `summarize_concurrency=0` in configuration. Ingest a website. Verify only ChunkStep, EmbedStep, and StoreStep execute — no DocumentSummaryStep or BodyOfKnowledgeSummaryStep.

**Acceptance Scenarios**:

1. **Given** `summarize_concurrency` is set to 0, **When** the ingest website plugin runs, **Then** no summarization steps are included in the pipeline.
2. **Given** `summarize_concurrency` is set to a positive integer, **When** the ingest website plugin runs, **Then** both DocumentSummaryStep and BodyOfKnowledgeSummaryStep are included.

---

### Edge Cases

- What happens when a message retry header is missing or corrupted? The system treats it as attempt 0 (first try).
- What happens when the RabbitMQ exchange is unavailable during a retry publish? The message is lost and the error is logged.
- What happens when all documents have fewer than 4 chunks? No document summaries are generated; the BoK summary uses raw chunk content.
- What happens when guidance plugin gets zero results from all collections? It returns "No relevant context found." as context.
- What happens when all retrieved chunks score below the threshold? The LLM receives "No relevant context found." (guidance) or an empty knowledge string (expert).
- What happens when the LLM times out during summarization? The error is recorded in context.errors and the document is skipped; remaining documents continue processing.
- What happens when expert results have no distance data? Score is set to None and the chunk is not filtered (no threshold applied without a score).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The LLM adapter MUST execute synchronous LLM calls in a separate thread (via `asyncio.to_thread`) to prevent blocking the async event loop during long-running calls.
- **FR-002**: The RabbitMQ adapter MUST support configurable heartbeat interval (default 300 seconds) and enable TCP keepalive on connections.
- **FR-003**: The RabbitMQ consumer MUST implement retry logic — failed messages are republished with an `x-retry-count` header, up to a configurable maximum (default 3 attempts). Messages exceeding the retry limit are discarded with error logging.
- **FR-004**: Summarization prompts MUST use structured format with explicit FORMAT, REQUIREMENTS, and FORBIDDEN sections, requiring markdown output with headers and bullet points, entity preservation, and anti-repetition constraints.
- **FR-005**: Document and body-of-knowledge summary target length MUST be 10000 characters, with progressive budgeting from 40% (4000 chars) for early chunks to 100% (10000 chars) for later chunks.
- **FR-006**: Document summarization MUST process documents sequentially (not concurrently) to reduce event loop contention during LLM calls.
- **FR-007**: Raw chunks MUST be stored with ChromaDB documentId format `{document_id}-chunk{chunk_index}`. Summary and BoK chunks MUST use their document_id as-is.
- **FR-008**: Both guidance and expert plugins MUST prefix each retrieved chunk with `[source:N]` (zero-based, contiguous) before passing to the LLM, matching the original `combine_query_results()` format.
- **FR-009**: Both plugins MUST filter out chunks with relevance score below a configurable threshold (default 0.3) before passing them to the LLM prompt.
- **FR-010**: Both plugins MUST deduplicate the sources list by source URL — guidance keeps the highest-scoring chunk per source, expert keeps the first occurrence per source (matching the original `{doc["source"]: doc}.values()` pattern).
- **FR-011**: The expert plugin MUST retrieve a configurable number of results (default 5, via `RETRIEVAL_N_RESULTS` env var), down from the previous hardcoded 10.
- **FR-012**: The guidance plugin MUST deduplicate query results by source URL, keeping only the highest-scoring chunk per source, sort by relevance score descending, and limit results to 5.
- **FR-013**: The ingest website plugin MUST conditionally include summarization steps based on `summarize_concurrency` configuration — summarization steps are omitted when the value is 0.
- **FR-014**: The LLM provider factory MUST set `max_retries=3` on all LLM client instances for automatic retry of transient API failures.
- **FR-015**: Configuration MUST expose `rabbitmq_heartbeat` (int, default 300), `rabbitmq_max_retries` (int, default 3), `retrieval_n_results` (int, default 5), and `retrieval_score_threshold` (float, default 0.3) settings via environment variables.
- **FR-016**: The `score_threshold` and `n_results` parameters MUST be injectable into plugins via constructor kwargs, with main.py introspecting plugin signatures to pass config-derived values.

### Key Entities

- **RabbitMQ Message**: Incoming message with body, content_type, and headers (including `x-retry-count` for retry tracking).
- **LLM Adapter**: Wrapper around LangChain LLM that manages async execution via thread offloading and timeout handling.
- **Summarization Prompt**: System/initial/subsequent prompt templates used in the refine summarization pattern.
- **Guidance Result**: Query result from ChromaDB collection with score, source URL, and document content — subject to deduplication and ranking.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Knowledge base ingestion with 15+ documents completes without RabbitMQ connection drops (zero heartbeat timeout errors).
- **SC-002**: Generated document summaries contain at least 3x more content than the previous 2000-character budget (measured by character count of summary chunks in ChromaDB).
- **SC-003**: All key entities (names, dates, numbers, URLs) from source documents are preserved in generated summaries (verified by spot-checking 3 documents post-ingestion).
- **SC-004**: Both guidance and expert plugins return no duplicate source URLs in a single query response.
- **SC-005**: LLM prompts from both plugins contain `[source:0]`, `[source:1]` etc. prefixes on every retrieved chunk.
- **SC-006**: Chunks with relevance score below 0.3 do not appear in LLM prompts or source lists.
- **SC-007**: Expert plugin retrieves 5 results (not 10), keeping total context within Mistral's 32K window.
- **SC-008**: Failed messages are retried up to 3 times before being discarded, with each attempt logged.
- **SC-009**: ChromaDB chunk IDs follow the `{document_id}-chunk{index}` format for raw chunks, matching the original system's convention.

## Assumptions

- The existing RabbitMQ infrastructure supports heartbeat negotiation and TCP keepalive.
- LLM providers (Mistral, OpenAI, Anthropic) support synchronous `invoke()` calls in addition to async `ainvoke()`.
- The original virtual-contributor-ingest-website repo's prompt format and summary length (10000 chars) represent the desired quality baseline.
- Sequential document summarization is acceptable for the current scale (10-100 documents per ingestion).
- The `summarize_concurrency` config field at value 0 is a clear enough signal to disable summarization (no separate boolean flag needed).
