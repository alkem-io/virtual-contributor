# Feature Specification: Pipeline Reliability and BoK Resilience

**Feature Branch**: `story/020-pipeline-reliability`
**Created**: 2026-04-15
**Status**: Implemented

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Pipeline Completes Without Deadlock (Priority: P1)

As a platform operator, I want ingest pipelines to complete reliably even when multiple pipelines run concurrently and individual LLM calls time out, so that the system does not deadlock and require manual intervention.

**Why this priority**: A thread pool deadlock halts all ingestion across all tenants indefinitely. There is no recovery mechanism short of restarting the service. This is the highest-severity failure mode.

**Independent Test**: Run two concurrent ingest pipelines with an LLM endpoint that times out on some calls. Verify that both pipelines complete (with errors for timed-out documents) within the pipeline timeout period and that subsequent pipelines can still run.

**Acceptance Scenarios**:

1. **Given** a 120s LLM timeout and 8 concurrent summarizations per pipeline, **When** an LLM call times out, **Then** the adapter raises `TimeoutError` immediately without retrying, preserving thread pool capacity.
2. **Given** three concurrent ingest pipelines each running 8 summarizations, **When** the event loop starts, **Then** the thread pool has 32 workers available, preventing exhaustion from concurrent `asyncio.to_thread` calls.
3. **Given** a DocumentSummaryStep with background embedding tasks, **When** an exception occurs between task creation and the await loop, **Then** all background tasks are still awaited via `try/finally`, preventing orphaned coroutines and thread pool leaks.

---

### User Story 2 -- BoK Survives Partial LLM Failures (Priority: P2)

As a platform operator, I want the Body of Knowledge summary to be generated successfully even when some refinement rounds fail, so that partial LLM outages do not discard work from completed rounds.

**Why this priority**: BoK generation uses sequential refine-pattern summarization. A failure on round N of M currently discards all work from rounds 1..N-1. With slow models (2 min/call), this can waste 30+ minutes of LLM time.

**Independent Test**: Configure a mock LLM that fails on refinement round 3 of 5. Verify that the BoK summary returned contains the partial result from rounds 1-2, not an error.

**Acceptance Scenarios**:

1. **Given** a refine summarization with 5 rounds, **When** round 3 fails after rounds 1-2 succeeded, **Then** the partial summary from round 2 is returned with a warning log.
2. **Given** a refine summarization where round 1 fails, **When** no partial summary exists, **Then** the exception propagates (no empty string returned).
3. **Given** a BoK with 20 document sections, **When** sections are grouped by `max_section_chars=30000`, **Then** sections are grouped so no group exceeds `max_section_chars` (default 30,000), reducing the total number of sequential LLM calls.
4. **Given** a BoK summary is generated successfully, **When** both `embeddings_port` and `knowledge_store_port` are provided, **Then** the BoK is embedded and stored inline immediately, not deferred to later pipeline steps.

---

### User Story 3 -- BoK Is Not Regenerated Unnecessarily (Priority: P3)

As a platform operator, I want the BoK summary to be skipped when the corpus has not changed and a BoK already exists in the store, so that re-ingestion of unchanged content does not waste LLM calls.

**Why this priority**: BoK generation is the single most expensive LLM operation in the pipeline. Skipping it when unnecessary eliminates the largest avoidable cost during routine re-ingestion.

**Independent Test**: Ingest a corpus, then re-ingest the same corpus unchanged. Verify that `BodyOfKnowledgeSummaryStep` returns without calling the LLM when a BoK entry already exists in the store.

**Acceptance Scenarios**:

1. **Given** change detection ran and found no changes or removals, **When** a BoK entry exists in the store, **Then** `BodyOfKnowledgeSummaryStep.execute()` returns immediately without LLM calls.
2. **Given** change detection ran and found no changes, **When** no BoK entry exists in the store, **Then** BoK is regenerated (first-time ingestion or after store wipe).
3. **Given** change detection ran and found changed documents, **When** a BoK entry exists in the store, **Then** BoK is regenerated to reflect the changes.

---

### Edge Cases

- When `_refine_summarize()` receives an empty chunks list, it returns `""` without calling the LLM.
- When `BodyOfKnowledgeSummaryStep` inline persist fails (embed or store error), the BoK chunk is still appended to context for the deferred EmbedStep/StoreStep to handle.
- When `StoreStep` encounters duplicate storage IDs within a batch (identical content hashes across documents), it keeps the last occurrence to avoid ChromaDB duplicate ID errors.
- When `ChangeDetectionStep._detect()` finds existing chunks with `embeddings=[]` (empty list, not None), it correctly treats them as having no embeddings rather than truthy.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The LLM adapter MUST NOT retry on `asyncio.TimeoutError`. A timed-out call MUST raise `TimeoutError` immediately.
- **FR-002**: The event loop MUST be configured with a `ThreadPoolExecutor(max_workers=32)` to prevent thread pool exhaustion under concurrent pipeline load.
- **FR-003**: `DocumentSummaryStep.execute()` MUST wrap background embedding task creation and awaiting in `try/finally` with `asyncio.gather(*tasks, return_exceptions=True)`.
- **FR-004**: `_refine_summarize()` MUST return a partial summary from prior rounds when a refinement round fails, rather than raising, provided at least one round completed.
- **FR-005**: `BodyOfKnowledgeSummaryStep` MUST accept optional `max_section_chars`, `knowledge_store_port`, and `embeddings_port` constructor parameters.
- **FR-006**: `BodyOfKnowledgeSummaryStep` MUST group sections by character count (default 30000) to reduce refinement rounds.
- **FR-007**: `BodyOfKnowledgeSummaryStep` MUST embed and store the BoK inline when both `embeddings_port` and `knowledge_store_port` are provided.
- **FR-008**: `BodyOfKnowledgeSummaryStep` MUST skip regeneration when change detection has been executed (`change_detection_ran` is true) AND found no changes/removals AND a BoK entry exists in the store.
- **FR-009**: `StoreStep` MUST deduplicate chunks by storage ID within each batch, keeping the last occurrence.
- **FR-010**: `ChangeDetectionStep._detect()` MUST check `existing.embeddings is not None and len(existing.embeddings) > 0` rather than just `if existing.embeddings`.
- **FR-011**: Both ingest plugins MUST pass `embeddings_port` and `knowledge_store_port` to `BodyOfKnowledgeSummaryStep`.

### Key Entities

- **ThreadPoolExecutor**: Explicit 32-worker pool set on the event loop in `main.py` to size capacity for concurrent pipeline workloads.
- **_refine_summarize**: Shared helper function for refine-pattern summarization with partial failure resilience.
- **BodyOfKnowledgeSummaryStep**: Pipeline step with inline persistence and section grouping capabilities.
- **StoreStep**: Pipeline step with batch-level deduplication by storage ID.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No thread pool deadlocks when 3+ concurrent pipelines run with occasional LLM timeouts.
- **SC-002**: Partial BoK summaries are returned when intermediate refinement rounds fail, preserving completed LLM work.
- **SC-003**: BoK regeneration is skipped on re-ingestion of unchanged corpora with an existing BoK in the store.
- **SC-004**: Background embedding tasks in DocumentSummaryStep are always awaited, even when exceptions occur during result processing.
- **SC-005**: StoreStep handles duplicate storage IDs without ChromaDB errors.

## Assumptions

- The default Python thread pool (typically 5 * CPU count) is insufficient for concurrent pipeline workloads that each spawn 8+ thread-based LLM calls.
- `asyncio.wait_for` cancels the coroutine but not the underlying thread when using `asyncio.to_thread`, creating zombie threads that consume pool capacity.
- The BoK summary storage ID convention is `body-of-knowledge-summary-0` and the metadata uses `embeddingType: "body-of-knowledge"`.
- Inline BoK persistence is a best-effort optimization; the deferred EmbedStep/StoreStep path handles fallback.
