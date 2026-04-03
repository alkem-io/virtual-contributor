# Tasks: Composable Ingest Pipeline Engine

**Input**: Design documents from `/specs/004-pipeline-engine-redesign/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/pipeline-api.md, quickstart.md

**Tests**: Included in Phase 7 (User Story 5) as independent step testing is an explicit user story.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new pipeline package structure

- [x] T001 Create core/domain/pipeline/ package directory with empty __init__.py in core/domain/pipeline/__init__.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core pipeline framework types and engine that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 Implement PipelineStep protocol (runtime_checkable, name property, async execute method), StepMetrics dataclass (duration, items_in, items_out, error_count), and PipelineContext dataclass (collection_name, documents, chunks, document_summaries, errors, metrics) in core/domain/pipeline/engine.py
- [x] T003 Implement IngestEngine class with __init__(steps: list[PipelineStep]) and async run(documents, collection_name) -> IngestResult that creates PipelineContext, executes steps sequentially, and assembles IngestResult from final context state in core/domain/pipeline/engine.py

**Checkpoint**: Pipeline framework ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Correct Retrieval Granularity After Ingestion (Priority: P1) MVP

**Goal**: Fix the critical correctness bug where document summaries overwrite chunk embeddings. After ingestion, every distinct section of every document must be independently retrievable with its original text embedded.

**Independent Test**: Ingest a multi-page website. Query for a specific fact that appears on only one page. The system returns the chunk containing that fact, not a generic summary.

### Implementation for User Story 1

- [x] T004 [P] [US1] Create FR-006-compliant summarization prompt templates in core/domain/pipeline/prompts.py: document refine system/human prompts and BoK overview system/human prompts with structured markdown output requirements, entity preservation rules (names, dates, numbers, URLs, technical terms), and anti-repetition constraints
- [x] T005 [P] [US1] Implement ChunkStep using RecursiveCharacterTextSplitter with configurable chunk_size (default 2000) and chunk_overlap (default 400), setting metadata.embedding_type="chunk" for all raw chunks, skipping documents producing 0 chunks in core/domain/pipeline/steps.py
- [x] T006 [US1] Implement _refine_summarize() async helper (refine pattern with progressive length budgeting: 40% to 100% of summary_length) and DocumentSummaryStep with >3 chunk threshold, asyncio.Semaphore concurrency control (default 8), separate summary Chunk creation (documentId="{original}-summary", embeddingType="summary"), and context.document_summaries population in core/domain/pipeline/steps.py
- [x] T007 [US1] Implement EmbedStep with configurable batch_size (default 50), always embedding chunk.content, skipping chunks with existing embeddings, and per-batch error collection in core/domain/pipeline/steps.py
- [x] T008 [US1] Implement StoreStep with configurable batch_size (default 50), metadata dict construction (documentId, source, type, title, embeddingType, chunkIndex), ID format "{document_id}-{chunk_index}", precomputed embeddings pass-through, per-batch error collection in context.errors on storage failure (FR-009), and insert-only behavior in core/domain/pipeline/steps.py
- [x] T009 [US1] Update core/domain/pipeline/__init__.py to export PipelineStep, PipelineContext, StepMetrics, IngestEngine, ChunkStep, DocumentSummaryStep, EmbedStep, and StoreStep
- [x] T010 [P] [US1] Update plugins/ingest_website/plugin.py to replace run_ingest_pipeline() call with IngestEngine composed of ChunkStep + DocumentSummaryStep + EmbedStep + StoreStep, using default chunk_size=2000 and injecting LLM, embeddings, and knowledge store ports
- [x] T011 [P] [US1] Update plugins/ingest_space/plugin.py to replace run_ingest_pipeline() call with IngestEngine composed of ChunkStep(chunk_size=9000, chunk_overlap=500) + DocumentSummaryStep + EmbedStep + StoreStep, injecting LLM, embeddings, and knowledge store ports
- [x] T012 [US1] Remove run_ingest_pipeline() function from core/domain/ingest_pipeline.py preserving all data classes (Document, DocumentMetadata, Chunk, IngestResult, DocumentType) per FR-015
- [x] T013 [US1] Update tests/core/domain/test_ingest_pipeline.py to remove all pipeline execution tests (test_chunking_produces_chunks, test_embedding_batching, test_batch_storage, etc.) and retain only data-class instantiation assertions
- [x] T014 [P] [US1] Update tests/plugins/test_ingest_website.py to assert IngestEngine is instantiated with correct step types and configuration instead of run_ingest_pipeline() call assertions
- [x] T015 [P] [US1] Update tests/plugins/test_ingest_space.py to assert IngestEngine is instantiated with correct step types (chunk_size=9000, chunk_overlap=500) instead of run_ingest_pipeline() call assertions

**Checkpoint**: US1 is fully functional. ChromaDB contains raw chunks with embeddingType="chunk" (distinct embeddings) plus separate summary entries with embeddingType="summary". Queries return relevant chunk text, not generic summaries.

---

## Phase 4: User Story 2 - Body-of-Knowledge Overview Retrieval (Priority: P2)

**Goal**: After full knowledge base ingestion, store a single high-level overview entry that captures themes, key entities, and scope across all documents. Enables answering broad questions like "what is this knowledge base about?"

**Independent Test**: Ingest a multi-document knowledge base. Ask "what topics does this knowledge base cover?" The system returns a coherent overview from the body-of-knowledge summary entry.

### Implementation for User Story 2

- [x] T016 [US2] Implement BodyOfKnowledgeSummaryStep that reads context.document_summaries (falling back to concatenated raw chunk content for documents without summaries), generates a single overview via refine pattern using BoK-specific prompts, and appends one Chunk with documentId="body-of-knowledge-summary", type="bodyOfKnowledgeSummary", embeddingType="summary" in core/domain/pipeline/steps.py
- [x] T017 [US2] Update core/domain/pipeline/__init__.py to export BodyOfKnowledgeSummaryStep
- [x] T018 [P] [US2] Update plugins/ingest_website/plugin.py to insert BodyOfKnowledgeSummaryStep(llm_port=llm) after DocumentSummaryStep in pipeline composition
- [x] T019 [P] [US2] Update plugins/ingest_space/plugin.py to insert BodyOfKnowledgeSummaryStep(llm_port=llm) after DocumentSummaryStep in pipeline composition

**Checkpoint**: US2 is fully functional. ChromaDB contains one body-of-knowledge-summary entry per collection. System can answer orientation queries using this overview.

---

## Phase 5: User Story 3 - Composable Pipeline for Plugin Authors (Priority: P2)

**Goal**: Plugin developers can assemble ingestion pipelines by selecting which steps to include and configuring each independently. Error-resilient execution ensures individual failures don't halt the entire pipeline.

**Independent Test**: Create two pipelines with different step compositions (one with summarization, one without). Run each on the same documents. Verify each produces expected output for its configuration.

**Note**: The composable architecture is established by IngestEngine (Phase 2) and step implementations (Phases 3-4). This phase adds the error-resilience execution contract (FR-009) that makes the architecture safe for plugin authors.

### Implementation for User Story 3

- [x] T020 [US3] Implement step-level error boundaries in IngestEngine.run(): wrap each step.execute() call in try/except, append step-name-prefixed error message to context.errors on failure, record error_count in StepMetrics, continue to next step, and set IngestResult.success=False when any errors exist in core/domain/pipeline/engine.py

**Checkpoint**: US3 is satisfied. Pipelines composed without summarization steps work without LLM port. Step and item errors are collected without halting execution. StepMetrics recorded per step.

---

## Phase 6: User Story 5 - Independent Step Testing (Priority: P3)

**Note**: User Story 4 (Rich Summarization Quality) is satisfied by T004, which creates FR-006-compliant prompts from the start. No separate phase needed.

**Goal**: Each pipeline step can be instantiated and tested in isolation with mock inputs and outputs, without requiring the full pipeline or external services.

**Independent Test**: Unit test each step class by providing mock chunks/context and asserting the output transformation.

### Tests for User Story 5

- [x] T022 [US5] Write ChunkStep unit tests in tests/core/domain/test_pipeline_steps.py: test chunking produces chunks with embeddingType="chunk", configurable chunk_size/overlap, empty document handling, metadata propagation, and chunk_index correctness
- [x] T023 [US5] Write EmbedStep unit tests with MockEmbeddingsPort in tests/core/domain/test_pipeline_steps.py: test batch processing respects batch_size, always embeds chunk.content, skips chunks with existing embeddings, and handles per-batch errors
- [x] T024 [US5] Write DocumentSummaryStep unit tests with MockLLMPort in tests/core/domain/test_pipeline_steps.py: test >3 chunk threshold, summary Chunk creation with correct metadata (documentId="{id}-summary", embeddingType="summary"), context.document_summaries population, per-document error handling, and documents with <=3 chunks produce no summary
- [x] T025 [US5] Write StoreStep unit tests with MockKnowledgeStorePort in tests/core/domain/test_pipeline_steps.py: test batch storage calls ingest() with correct document texts, metadata dicts, ids ("{document_id}-{chunk_index}"), precomputed embeddings, and per-batch error handling
- [x] T026 [US5] Write BodyOfKnowledgeSummaryStep unit tests with MockLLMPort in tests/core/domain/test_pipeline_steps.py: test aggregation using document_summaries when available, fallback to raw chunk content, single BoK entry with documentId="body-of-knowledge-summary" and type="bodyOfKnowledgeSummary"
- [x] T027 [US5] Write IngestEngine integration tests in tests/core/domain/test_pipeline_steps.py: test step sequencing order, context propagation between steps, IngestResult assembly (collection_name, documents_processed, chunks_stored, errors, success), error collection from failing steps, and zero-step pipeline returns empty result

**Checkpoint**: All 5 step classes and IngestEngine have dedicated unit tests that run without external services.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Clean up superseded code and validate the complete system

- [x] T028 [P] Remove core/domain/summarize_graph.py (functionality absorbed into _refine_summarize() in pipeline steps per research decision 6)
- [x] T029 [P] Remove tests/core/domain/test_summarize_graph.py (replaced by tests/core/domain/test_pipeline_steps.py)
- [x] T030 Run full validation: poetry run pytest && poetry run ruff check core/ plugins/ tests/ && poetry run pyright core/ plugins/
- [x] T031 Run quickstart.md pipeline composition and step isolation examples to verify documentation accuracy

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - **US1 (Phase 3)**: Can start after Foundational - No dependencies on other stories. FR-006-compliant prompts created here (T004), satisfying US4.
  - **US2 (Phase 4)**: Depends on US1 (DocumentSummaryStep populates context.document_summaries used by BoKSummaryStep)
  - **US3 (Phase 5)**: Can start after Foundational - Hardens IngestEngine error handling
  - **US5 (Phase 6)**: Depends on US1 + US2 (all steps must exist to test)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Start after Phase 2 - Creates the core steps, plugin integrations, and FR-006-compliant prompts (satisfying US4)
- **US2 (P2)**: Start after US1 - Adds BoK step that reads DocumentSummaryStep's output
- **US3 (P2)**: Start after Phase 2 - Independent of US1/US2 (hardens engine only)
- **US5 (P3)**: Start after US1 + US2 - Tests all step implementations

### Within Each User Story

- Steps in the same file (steps.py) are sequential
- Plugin updates (different files) can be parallel
- Test updates (different files) can be parallel

### Parallel Opportunities

**Phase 3 (US1)**:
- T004 (prompts.py) and T005 (ChunkStep in steps.py) can run in parallel
- T010 (website plugin) and T011 (space plugin) can run in parallel
- T014 (test_website) and T015 (test_space) can run in parallel

**Phase 4 (US2)**:
- T018 (website plugin) and T019 (space plugin) can run in parallel

**Phase 7 (Polish)**:
- T028 (remove summarize_graph.py) and T029 (remove test_summarize_graph.py) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch prompts and first step in parallel (different files):
Task: "Create FR-006-compliant summarization prompt templates in core/domain/pipeline/prompts.py"
Task: "Implement ChunkStep in core/domain/pipeline/steps.py"

# Launch both plugin updates in parallel (different files):
Task: "Update plugins/ingest_website/plugin.py to use IngestEngine"
Task: "Update plugins/ingest_space/plugin.py to use IngestEngine"

# Launch both plugin test updates in parallel (different files):
Task: "Update tests/plugins/test_ingest_website.py for pipeline composition"
Task: "Update tests/plugins/test_ingest_space.py for pipeline composition"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (package creation)
2. Complete Phase 2: Foundational (IngestEngine framework)
3. Complete Phase 3: User Story 1 (critical correctness fix)
4. **STOP and VALIDATE**: Ingest a multi-page website, query for a specific fact on one page, verify the correct chunk is returned (not a summary)
5. Deploy/demo if ready - system now retrieves correctly

### Incremental Delivery

1. Setup + Foundational -> Pipeline framework ready
2. **US1** -> Correct chunk storage, document summaries as separate entries, FR-006-compliant prompts -> **MVP!**
3. **US2** -> Add body-of-knowledge overview entry -> Orientation queries work
4. **US3** -> Error-resilient execution -> Safe for plugin authors
5. **US5** -> Full step test coverage -> Confident refactoring
6. Polish -> Remove legacy code, full validation

### Key Architectural Note

The critical correctness fix (US1) is: EmbedStep always embeds `chunk.content`. Raw chunks store original text as content. Summary chunks store summary text as content. The `Chunk.summary` field is preserved (FR-015) but no longer written by the pipeline. This eliminates the bug where `c.summary or c.content` caused all chunks to be embedded by the same summary text.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable (except US2 depends on US1's DocumentSummaryStep)
- New source code: ~370 LOC across 3 files (engine.py ~80, steps.py ~250, prompts.py ~40)
- Modified files: 2 plugins, 1 data module, 3 test files
- Removed files: summarize_graph.py, test_summarize_graph.py
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
