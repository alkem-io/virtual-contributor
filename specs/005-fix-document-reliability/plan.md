# Implementation Plan: Document Processing Reliability & Alignment

**Branch**: `fix/documents` | **Date**: 2026-04-06 | **Status**: Implemented | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-fix-document-reliability/spec.md`

## Summary

Fix document processing reliability by switching LLM calls to thread-based execution (preserving the event loop for RabbitMQ heartbeats), adding RabbitMQ heartbeat configuration and message retry logic, rewriting summarization prompts to match the original repo's structured format, increasing summary budget from 2000 to 10000 characters, aligning chunk ID format with the original repo, adding guidance plugin result deduplication, making summarization steps configurable, restoring `[source:N]` prefix formatting on retrieved chunks (alkem-io/virtual-contributor#7), adding score-threshold source filtering (alkem-io/virtual-contributor#8), reducing expert retrieval count from 10 to 5 (alkem-io/virtual-contributor#9), and deduplicating sources in the expert plugin.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, pydantic-settings ^2.11.0, aio-pika 9.5.7, chromadb-client ^1.5.0, httpx ^0.27.2  
**Storage**: ChromaDB (vector store via HTTP client), RabbitMQ (message transport)  
**Testing**: pytest (ruff for linting, pyright for type checking)  
**Target Platform**: Linux server (Docker container, single image)  
**Project Type**: Background service (message-driven worker)  
**Performance Goals**: N/A — throughput bound by external LLM and embedding services  
**Constraints**: Async-first (aio-pika prefetch=1), sequential document summarization, batch processing for embeddings and storage (default 50)  
**Scale/Scope**: 10-100 documents per ingestion invocation, 1-20 pages per website crawl

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Design Check

| Principle / Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Changes are independently testable with mock ports |
| P2 SOLID Architecture | PASS | Adapter changes stay within adapter boundary; prompt changes in domain layer |
| P3 No Vendor Lock-in | PASS | Thread offloading works with any LangChain LLM backend |
| P4 Optimised Feedback Loops | PASS | Existing tests updated to reflect new ID format |
| P5 Best Available Infrastructure | PASS | N/A — no CI/deployment changes |
| P6 Spec-Driven Development | PASS | SDD artifacts created for this feature |
| P7 No Filling Tests | PASS | Test changes verify real behavioral contracts (ID format) |
| P8 ADR | PASS | No port/contract/adapter interface changes; internal behavioral fixes only |
| Microkernel Architecture | PASS | Core domain and adapter changes stay within established boundaries |
| Hexagonal Boundaries | PASS | RabbitMQ adapter changes are adapter-internal; pipeline steps use port interfaces |
| Plugin Contract | PASS | No changes to PluginContract protocol |
| Event Schema | PASS | No changes to event schemas |
| Domain Logic Isolation | PASS | Pipeline steps continue to accept port interfaces via injection |
| Async-First Design | PASS | Thread offloading explicitly preserves async event loop; `asyncio.to_thread` is an asyncio primitive |
| Simplicity Over Speculation | PASS | All changes address observed production issues; no speculative features |

**Gate result**: PASS — no violations, no justifications needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-fix-document-reliability/
├── spec.md              # Feature specification
├── plan.md              # This file
├── tasks.md             # Task breakdown
└── checklists/
    └── requirements.md  # Quality checklist
```

### Source Code (files modified)

```text
core/
├── adapters/
│   ├── langchain_llm.py     # Thread-based LLM execution
│   └── rabbitmq.py           # Heartbeat, keepalive, retry logic
├── config.py                  # RabbitMQ + retrieval config fields
├── domain/pipeline/
│   ├── prompts.py             # Rewritten summarization prompts
│   └── steps.py               # Sequential summarization, chunk ID format
└── provider_factory.py        # LLM max_retries

plugins/
├── guidance/plugin.py         # [source:N] prefix, score filtering, dedup
├── expert/plugin.py           # [source:N] prefix, score filtering, dedup, n_results=5
└── ingest_website/plugin.py   # Conditional summarization

main.py                        # Pass heartbeat/retry/retrieval config to plugins

tests/
├── core/
│   ├── domain/
│   │   └── test_pipeline_steps.py  # Updated ID format assertions
│   └── test_langchain_llm.py       # Updated mocks for sync invoke
└── plugins/
    ├── test_guidance.py             # Score filtering + [source:N] tests
    └── test_expert.py               # n_results, score filtering, [source:N], dedup tests
```

## Design Decisions

### D1: Thread-based LLM execution over async ainvoke

**Problem**: `ainvoke()` on LangChain LLM objects blocks the event loop internally for some providers, preventing RabbitMQ heartbeat responses and causing connection drops during long LLM calls.

**Decision**: Use `asyncio.to_thread(self._sync_invoke, ...)` to run the synchronous `invoke()` in a thread pool, wrapped in `asyncio.wait_for()` for timeout. This keeps the event loop free for heartbeats.

**Alternatives rejected**:
- Increase heartbeat interval only: Masks the problem; sufficiently long LLM calls would still block.
- Run each LLM call in a subprocess: Excessive overhead for CPU-unbound I/O work.

### D2: Sequential document summarization over concurrent

**Problem**: Concurrent summarization with `asyncio.gather` + `Semaphore` created event loop contention when many LLM calls completed simultaneously, contributing to heartbeat issues.

**Decision**: Process documents sequentially with a simple `for` loop. Since LLM calls now run in threads, the event loop stays responsive. Sequential processing is simpler to debug and produces deterministic ordering.

**Alternatives rejected**:
- Keep concurrent with lower semaphore: Still creates contention spikes; complexity without benefit at current scale.
- Use a worker pool: Over-engineering for 10-100 documents.

### D3: Message retry via republish with header tracking

**Problem**: The previous `requeue=True` approach had no visibility into retry count, risking infinite retry loops.

**Decision**: Use `requeue=False` and manually republish with an `x-retry-count` header. After max retries (default 3), discard the message with error logging.

**Alternatives rejected**:
- RabbitMQ dead-letter exchange: Requires infrastructure changes (DLX configuration) outside the application.
- External retry queue: Additional complexity for a simple retry count.

### D4: Chunk ID format alignment

**Problem**: The redesigned pipeline used `{document_id}-{chunk_index}` for all chunks, while the original repo used `{document_id}-chunk{chunk_index}` for raw chunks. This mismatch would break any tooling that queries by ID pattern.

**Decision**: Raw chunks use `{document_id}-chunk{chunk_index}` as both the ChromaDB `documentId` metadata and the base for the entry ID. Summary and BoK chunks keep their `document_id` as-is.

### D5: Guidance plugin deduplication strategy

**Problem**: Multiple chunks from the same source page could dominate query results, reducing diversity.

**Decision**: Collect all results, sort by score descending, deduplicate by source URL (keep highest-scoring per source), limit to top 5. Simple and effective for the current retrieval pattern.

### D6: `[source:N]` prefix formatting (Issue #7)

**Problem**: The original `combine_query_results()` in `alkemio_virtual_contributor_engine/chromadb_utils.py` prefixed each chunk with `[source:0]`, `[source:1]` etc. The port removed this, making LLM source attribution impossible.

**Decision**: Apply the same `f"[source:{i}] {doc}"` formatting in both plugins — guidance at context assembly, expert via a shared `_filter_and_format()` helper. Indices are contiguous and zero-based, assigned after filtering/dedup so they match the final sources list.

### D7: Distance-threshold source filtering over LLM-based scoring (Issue #8)

**Problem**: The original engines used an LLM graph node to score each `[source:N]` 0-10 and exclude 0-scored sources. This added an LLM call per query.

**Decision**: Use vector distance threshold (score < 0.3 excluded) as a cheaper alternative (Issue #8 Option 2). This filters pre-generation rather than post-generation, removing irrelevant chunks from the prompt entirely. The threshold is configurable via `RETRIEVAL_SCORE_THRESHOLD` env var.

**Alternatives rejected**:
- Restore LLM-based scoring: Adds latency and cost per query. Can be re-added later as a second pass if needed (Issue #8 Option 3).
- No filtering: All chunks reach the LLM regardless of relevance, wasting context.

### D8: Expert n_results reduction and source deduplication (Issue #9)

**Problem**: Expert retrieved 10 results (original: 4). With 9000-char space chunks, this risks exceeding Mistral's 32K context window. Expert sources were also not deduplicated.

**Decision**: Default to 5 results (configurable via `RETRIEVAL_N_RESULTS`). Deduplicate `_build_sources()` by source URL using `seen` dict, matching the original `{doc["source"]: doc for doc in sources}.values()` pattern.

### D9: Config injection via constructor introspection

**Problem**: Plugins receive port interfaces via the Container's `resolve_for_plugin()`, which only resolves registered port types. Scalar config values (n_results, score_threshold) need a different injection path.

**Decision**: Add keyword-only params with defaults to plugin constructors (`n_results: int = 5`, `score_threshold: float = 0.3`). In `main.py`, introspect the plugin's `__init__` signature and inject config values for matching param names. Plugins work with defaults in tests; production gets config-derived values.

**Alternatives rejected**:
- Read `BaseConfig()` inside plugin `__init__`: Fails in tests (requires `LLM_API_KEY` env var).
- Register scalars in Container: Breaks the port-type-based resolution model.

## Complexity Tracking

No constitution violations — no justifications needed.
