# Feature Specification: Composable Ingest Pipeline Engine

**Feature Branch**: `004-pipeline-engine-redesign`  
**Created**: 2026-04-02  
**Status**: Implemented  
**Input**: Redesign the ingestion pipeline as a composable, configurable engine with independently testable pipeline steps, while restoring the correctness lost during the migration from the original virtual-contributor-ingest-website codebase.

## Clarifications

### Session 2026-04-02

- Q: How should transient failures (LLM timeout, embeddings API 503) be handled? → A: No retry in pipeline — adapters handle retries internally at the port level.
- Q: Should the old monolithic pipeline function be removed or preserved alongside the new engine? → A: Remove `run_ingest_pipeline()` — clean replacement, no parallel paths.
- Q: What per-step metrics should PipelineContext track? → A: Timing + counts — duration per step, items-in/items-out per step, error count per step.
- Q: What should the default batch size be for embedding and storage steps? → A: 50.
- Q: What should be explicitly out of scope for this feature? → A: All out of scope: retrieval/query logic changes, ChromaDB collection lifecycle (create/delete), and embedding model selection.
- Q: How should re-ingestion handle existing ChromaDB entries for a document? → A: Pipeline only inserts — plugin/caller is responsible for clearing the collection before re-running the pipeline.
- Q: What should the default LLM concurrency semaphore limit be for document summarization? → A: 8.
- Q: What is the target character length for document summaries (100% budget)? → A: 2000 characters.
- Q: Should IngestEngine validate pipeline step ordering? → A: No — plugin author's responsibility; engine stays step-type-agnostic.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Correct Retrieval Granularity After Ingestion (Priority: P1)

When a knowledge base is ingested (website or space), every distinct section of every document must be independently retrievable. A user asking a specific question must receive the relevant section, not a generic summary repeated across all chunks.

**Why this priority**: This is the critical correctness bug. The current pipeline copies one document-level summary to all chunks, collapsing them to identical vectors in ChromaDB. This destroys the fundamental value of RAG — fine-grained retrieval. Fixing this restores the system to working correctly.

**Independent Test**: Ingest a multi-page website. Query for a specific fact that appears on only one page. The system returns the chunk containing that fact, not a generic summary.

**Acceptance Scenarios**:

1. **Given** a document with 10 chunks, **When** the pipeline ingests it, **Then** ChromaDB contains 10 entries each storing their original chunk text with `embeddingType="chunk"` and distinct embeddings.
2. **Given** a document with 5 chunks and summarization enabled, **When** the pipeline ingests it, **Then** ChromaDB contains 5 chunk entries (original text) PLUS 1 summary entry with `embeddingType="summary"` and `documentId="{original}-summary"` — total 6 entries.
3. **Given** a document with 2 chunks and summarization enabled, **When** the pipeline ingests it, **Then** ChromaDB contains only the 2 chunk entries — no summary is generated (below the >3 chunk threshold).
4. **Given** an ingested knowledge base, **When** a user queries for a specific fact contained in one chunk, **Then** the retriever returns that chunk's original text, not a summary.

---

### User Story 2 - Body-of-Knowledge Overview Retrieval (Priority: P2)

After a full knowledge base is ingested, the system stores a single high-level overview entry that captures themes, key entities, and scope across all documents. This enables the system to answer broad questions like "what is this knowledge base about?" without needing to retrieve and synthesize many individual chunks.

**Why this priority**: This was a feature in the original system that was dropped during migration. It provides significant value for orientation queries and relevance determination, but the system works without it (individual chunks still serve specific queries).

**Independent Test**: Ingest a multi-document knowledge base. Ask "what topics does this knowledge base cover?" The system returns a coherent overview derived from the body-of-knowledge summary entry.

**Acceptance Scenarios**:

1. **Given** a knowledge base with multiple documents, **When** the pipeline completes ingestion, **Then** ChromaDB contains one entry with `documentId="body-of-knowledge-summary"`, `type="bodyOfKnowledgeSummary"`, and `embeddingType="summary"`.
2. **Given** a knowledge base where all documents have fewer than 4 chunks, **When** the body-of-knowledge summary is generated, **Then** it uses the raw chunk content (not document summaries) as input.
3. **Given** a knowledge base where some documents have document-level summaries, **When** the body-of-knowledge summary is generated, **Then** it uses those document summaries as input for documents that have them, and raw chunk content for documents that do not.

---

### User Story 3 - Composable Pipeline for Plugin Authors (Priority: P2)

Plugin developers can assemble an ingestion pipeline by selecting which steps to include and configuring each step independently. A website ingestion plugin and a space ingestion plugin can use different pipeline configurations (different chunk sizes, different summarization thresholds) without modifying shared pipeline code.

**Why this priority**: The current monolithic function requires boolean flags and parameter explosion to accommodate different plugin needs. A composable architecture makes the system extensible and each step independently testable — critical for long-term maintainability.

**Independent Test**: Create two pipelines with different step compositions (one with summarization, one without). Run each on the same input documents. Verify each pipeline produces the expected output for its configuration.

**Acceptance Scenarios**:

1. **Given** a plugin author building a new ingestion plugin, **When** they compose a pipeline with ChunkStep + EmbedStep + StoreStep (no summarization), **Then** the pipeline ingests documents correctly without requiring an LLM port.
2. **Given** a plugin author, **When** they compose a pipeline with ChunkStep + DocumentSummaryStep + BodyOfKnowledgeSummaryStep + EmbedStep + StoreStep, **Then** all steps execute in sequence with shared context.
3. **Given** a pipeline with a step that fails for some items, **When** the pipeline runs, **Then** errors are collected in context without halting subsequent items or steps, and the final result reports both successes and failures.

---

### User Story 4 - Rich Summarization Quality (Priority: P3)

When document or body-of-knowledge summaries are generated, they use structured, information-dense prompts that preserve all key entities (names, dates, numbers, URLs), use markdown formatting, and avoid vague or repetitive language. The summaries are optimized for semantic search retrieval.

**Why this priority**: The original system had carefully crafted prompts with specific formatting requirements, entity preservation rules, and anti-repetition constraints. The migrated system replaced these with bare "summarize in N characters" prompts. Restoring prompt quality improves summary usefulness, but the system functions with simpler prompts.

**Independent Test**: Summarize a document containing specific names, dates, and technical terms. The summary preserves all named entities and uses markdown structure.

**Acceptance Scenarios**:

1. **Given** a document with specific entities (names, dates, URLs), **When** the document summary is generated, **Then** the summary preserves all named entities from the source.
2. **Given** a multi-chunk document, **When** summarization runs, **Then** the summarizer uses a system prompt specifying structured markdown output, entity preservation, and anti-repetition rules.
3. **Given** a multi-chunk document, **When** summarization runs with progressive length budgeting, **Then** early chunks receive ~40% of the length budget and later chunks scale up to 100%.

---

### User Story 5 - Independent Step Testing (Priority: P3)

Each pipeline step can be instantiated and tested in isolation with mock inputs and outputs, without requiring the full pipeline or external services.

**Why this priority**: The current monolithic function can only be tested end-to-end. Independent step testing enables faster development cycles, clearer failure diagnostics, and confident refactoring.

**Independent Test**: Unit test each step class by providing mock chunks/context and asserting the output transformation.

**Acceptance Scenarios**:

1. **Given** a ChunkStep with configured chunk_size and overlap, **When** tested with a list of Documents, **Then** it returns Chunks with correct content, metadata, and indices — no external dependencies required.
2. **Given** an EmbedStep with a mock EmbeddingsPort, **When** tested with a list of Chunks, **Then** it calls embed() in batches and attaches embeddings to each chunk.
3. **Given** a DocumentSummaryStep with a mock LLMPort, **When** tested with chunks from a document with >3 chunks, **Then** it appends a new summary Chunk with correct metadata and does not modify the original chunks.
4. **Given** a StoreStep with a mock KnowledgeStorePort, **When** tested with embedded chunks, **Then** it calls ingest() with correct document texts, metadata dicts, ids, and pre-computed embeddings.

---

### Edge Cases

- What happens when a document has exactly 3 chunks? No document summary is generated (threshold is >3, matching original system behavior).
- What happens when a document produces 0 chunks (empty content)? The document is skipped with no error — chunking produces nothing, pipeline continues with remaining documents.
- What happens when the LLM fails during document summarization? The error is recorded in context, the document's raw chunks are still stored (they are never replaced), and the pipeline continues.
- What happens when the LLM fails during body-of-knowledge summarization? The error is recorded, all document chunks and any document summaries are already stored, only the BoK overview entry is missing.
- What happens when the embeddings service fails for a batch? The error is recorded, those chunks remain without embeddings. When StoreStep runs, it detects that some chunks have embeddings (from successful batches) and skips the unembedded chunks to prevent storing entries with mismatched embedding models. Remaining batches with embeddings are stored normally.
- What happens when a pipeline has zero steps? The engine returns an empty result with 0 chunks stored and 0 documents processed.
- What happens when summarization steps are omitted from the pipeline? Only raw chunks are embedded and stored — no LLM calls occur during ingestion.
- What happens when a document's content is shorter than chunk_size? It becomes a single chunk. Since 1 chunk is below the >3 threshold, no summary is generated.
- What happens when a previously ingested document is ingested again? The pipeline inserts new entries without clearing old ones. The plugin/caller must clear the collection before re-ingestion to avoid duplicates.

## Out of Scope

- **Retrieval / query logic**: No changes to how queries are processed, ranked, or returned to users.
- **ChromaDB collection lifecycle**: Collection creation, deletion, and management are not part of this feature.
- **Embedding model selection**: Which embedding model is used is configured externally; this feature does not introduce model selection or switching logic.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The pipeline engine MUST execute steps in the order they are composed, passing chunks and a shared context through each step sequentially.
- **FR-002**: Raw chunk content MUST always be stored in ChromaDB with `embeddingType="chunk"`. Summaries MUST NOT replace or overwrite chunk content.
- **FR-003**: Document summaries MUST be stored as separate, additional entries in ChromaDB with `embeddingType="summary"` and `documentId="{originalDocumentId}-summary"`.
- **FR-004**: Document summarization MUST only trigger for documents with more than 3 chunks, matching the original system's threshold.
- **FR-005**: Body-of-knowledge summarization MUST aggregate all document summaries (or raw chunk content for documents below the summary threshold) into a single overview entry with `documentId="body-of-knowledge-summary"` and `type="bodyOfKnowledgeSummary"`.
- **FR-006**: Summarization prompts MUST include a system prompt requiring structured markdown output, entity preservation (names, dates, numbers, URLs, technical terms), and anti-repetition constraints.
- **FR-007**: Summarization MUST use progressive length budgeting with a target length of 2000 characters — early chunks receive ~40% of the target (800 chars), scaling linearly to 100% (2000 chars) for later chunks. When there is only a single section/chunk to summarize, it receives the full 100% budget.
- **FR-008**: Each pipeline step MUST be independently instantiable and testable without requiring other steps or external services.
- **FR-009**: The pipeline context MUST collect errors from all steps without halting execution. Individual item failures within a step MUST NOT prevent processing of remaining items.
- **FR-010**: The EmbedStep MUST process chunks in configurable batches (default: 50), calling the embeddings service once per batch.
- **FR-011**: The StoreStep MUST process chunks in configurable batches (default: 50), calling the knowledge store once per batch with pre-computed embeddings. StoreStep MUST skip chunks without embeddings — the current ChromaDB adapter requires precomputed embeddings (`embedding_function=None`), so EmbedStep is a required predecessor to StoreStep in any pipeline that persists to ChromaDB.
- **FR-012**: Document summarization MUST limit concurrency using a configurable semaphore (default: 8) to avoid overwhelming the LLM service.
- **FR-013**: The pipeline MUST produce an IngestResult reporting collection name, documents processed, chunks stored, errors list, and overall success status. The `chunks_stored` count MUST reflect the number of chunks actually persisted to the knowledge store, not the total number of chunks produced by the pipeline.
- **FR-014**: Both existing ingest plugins (ingest-website, ingest-space) MUST be updated to compose their pipelines using the new engine, maintaining their current plugin-specific configurations (chunk sizes, page limits, etc.).
- **FR-015**: Existing data classes (Document, DocumentMetadata, Chunk, IngestResult, DocumentType), port protocols (EmbeddingsPort, KnowledgeStorePort, LLMPort), and adapter implementations MUST be preserved without breaking changes.
- **FR-016**: The pipeline engine MUST only insert new entries — it MUST NOT delete or clear existing ChromaDB entries. Collection cleanup before re-ingestion is the responsibility of the plugin or caller.

### Key Entities

- **PipelineStep**: A single transformation stage in the ingestion pipeline. Receives chunks and shared context, returns transformed or augmented chunks.
- **PipelineContext**: Shared mutable state that flows through all steps — carries collection name, accumulated chunks, accumulated errors, per-step metrics (wall-clock duration, items-in count, items-out count, error count per step), document-to-summary mappings needed by downstream steps, and a `chunks_stored` counter tracking successful persistence.
- **IngestEngine**: The compositor that accepts an ordered list of PipelineSteps and executes them sequentially, producing an IngestResult.
- **Chunk**: A unit of content with metadata, optional embedding. Chunks with `embeddingType="chunk"` contain raw document sections; chunks with `embeddingType="summary"` contain generated summaries.
- **Document**: Input to the pipeline — raw content with metadata, before chunking.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After ingestion, a query for a specific fact contained in one chunk returns that chunk's original text — not a summary — in the top 3 results.
- **SC-002**: After ingestion of a multi-document knowledge base with summarization enabled, the system contains exactly one body-of-knowledge summary entry per collection.
- **SC-003**: Each pipeline step can be unit-tested independently — test files exist for every step, each test runs without external services.
- **SC-004**: The number of entries in ChromaDB after ingestion equals: (total chunks across all documents) + (one document summary per document with >3 chunks) + (one body-of-knowledge summary if summarization steps are included).
- **SC-005**: All existing pipeline and summarization tests continue to pass after refactoring (updated to reflect new architecture).
- **SC-006**: Both ingest plugins (website, space) produce the same ChromaDB entry structure as the original pre-migration system: raw chunks with `embeddingType="chunk"`, document summaries with `embeddingType="summary"`, and one BoK summary with `type="bodyOfKnowledgeSummary"`.

## Assumptions

- The existing port protocols (EmbeddingsPort, KnowledgeStorePort, LLMPort) and their adapter implementations are correct and do not need modification.
- The existing plugin event types (IngestWebsite, IngestBodyOfKnowledge) and response types remain unchanged.
- The >3 chunk threshold for document summarization (from the original system) is the correct business rule.
- The original system's summarization prompts (entity preservation, markdown structure, anti-repetition) represent the desired quality standard.
- The composable pipeline replaces the monolithic `run_ingest_pipeline()` function — all callers will be updated to use the new engine directly. The old function will be removed entirely (no deprecation period or backward-compatibility wrapper).
- Existing ChromaDB collections will need re-ingestion to benefit from the corrected entry structure. No automatic data migration is needed.
- The `summarize_body_of_knowledge()` function in `summarize_graph.py` will be restructured as part of the BoK summary step rather than preserved as a standalone function.
- Retry and backoff for transient failures (LLM timeouts, embeddings API errors) are the responsibility of port adapters, not the pipeline engine or individual pipeline steps. The pipeline treats adapter-level failures as final errors to collect in context.
- IngestEngine does not validate step ordering or composition correctness. The engine is step-type-agnostic; correct step ordering is the plugin author's responsibility.
