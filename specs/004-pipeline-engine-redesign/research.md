# Research: Composable Ingest Pipeline Engine

**Feature**: 004-pipeline-engine-redesign
**Date**: 2026-04-02

## Decision 1: Pipeline Step Interface

**Decision**: Use a `typing.Protocol` class for `PipelineStep` with a `name` property and a single `async execute(context: PipelineContext) -> None` method.

**Rationale**:
- Consistent with the codebase convention where all interfaces use `Protocol` (EmbeddingsPort, KnowledgeStorePort, LLMPort)
- Structural subtyping means steps don't need to inherit from a base class
- Single method keeps the interface minimal (ISP)
- Mutating the shared context (rather than returning a new one) avoids allocation overhead and matches the spec's "shared mutable state" description
- `name` property enables per-step metrics tracking without a separate registry

**Alternatives considered**:
- ABC with `@abstractmethod`: Requires inheritance, inconsistent with existing port conventions
- Callable protocol `(PipelineContext) -> None`: Loses type identity, harder to inspect/configure steps
- Return new context (immutable pipeline): Over-engineered for sequential execution with shared state

## Decision 2: Context Design

**Decision**: `PipelineContext` is a mutable `@dataclass` carrying: documents (input), chunks (accumulated output), document_summaries (intermediate mapping), errors, and per-step metrics.

**Rationale**:
- Steps need to read chunks from prior steps and append new chunks (e.g., summary chunks)
- `document_summaries` dict enables DocumentSummaryStep -> BoKSummaryStep communication without tight coupling
- Per-step metrics (StepMetrics dataclass with duration, items_in, items_out, error_count) satisfy FR-013 and spec clarification on timing + counts
- Mutable context avoids copying large chunk lists between steps

**Alternatives considered**:
- Separate input/output per step: Requires engine to manage merging — complex, no benefit for sequential execution
- Event-based step communication: Over-engineered for a synchronous sequential pipeline
- Global state / module-level: Violates domain logic isolation, not testable

## Decision 3: Module Organization

**Decision**: New `core/domain/pipeline/` package with 3 files: `engine.py` (~80 LOC), `steps.py` (~250 LOC), `prompts.py` (~40 LOC).

**Rationale**:
- Total ~370 LOC — well under the 500 LOC evaluation threshold per constitution
- engine.py contains the framework types (PipelineStep, PipelineContext, IngestEngine)
- steps.py contains all 5 concrete step implementations
- prompts.py isolates prompt templates for easy review and modification
- Package structure keeps the flat `core/domain/` namespace clean

**Alternatives considered**:
- Single `pipeline.py` file (~400 LOC): Viable but mixes framework, steps, and prompts
- One file per step (8 files): Excessive for 30-80 LOC per step class
- Extend existing `ingest_pipeline.py`: Would mix legacy data classes with new engine

## Decision 4: Summarization Prompt Design

**Decision**: Rich system prompts with structured requirements — entity preservation, markdown formatting, anti-repetition constraints. Separate prompt templates for document summary (refine pattern) and BoK overview. Target length: 2000 characters (per spec clarification).

**Rationale**:
- FR-006 mandates structured markdown output, entity preservation, and anti-repetition
- Original system (pre-migration) used detailed prompts that are documented as the quality standard
- Prompt templates in a dedicated file enable iteration without touching step logic
- Progressive length budgeting (FR-007): 2000 char target, 40% (800 chars) -> 100% (2000 chars) linear scaling

**Alternatives considered**:
- Minimal prompts ("summarize in N chars"): Current state — produces low-quality summaries per User Story 4
- External prompt files (YAML/JSON): Over-engineered for 2 prompt templates
- LangChain prompt templates: Unnecessary dependency on LangChain's template system for simple string formatting

## Decision 5: Data Class Preservation Strategy

**Decision**: Keep all existing data classes (Document, DocumentMetadata, Chunk, IngestResult, DocumentType) in `core/domain/ingest_pipeline.py`. Remove only `run_ingest_pipeline()`. New pipeline types go in `core/domain/pipeline/`.

**Rationale**:
- FR-015 mandates preserving existing data classes without breaking changes
- Data classes are imported throughout the codebase (plugins, tests, adapters)
- Moving them would cause unnecessary import churn with no architectural benefit
- `ingest_pipeline.py` becomes a data-classes-only module

**Alternatives considered**:
- Move data classes to `core/domain/models.py`: Import churn, no benefit
- Move data classes into `pipeline/` package: Couples data model to pipeline engine
- Duplicate in both locations: Violates DRY

## Decision 6: Handling of summarize_graph.py

**Decision**: Remove `summarize_graph.py`. The refine summarization algorithm moves into a private `_refine_summarize()` helper in `steps.py`, called by both `DocumentSummaryStep` and `BoKSummaryStep`.

**Rationale**:
- Spec assumption: "summarize_body_of_knowledge() will be restructured as part of the BoK summary step"
- Both document and BoK summarization use the same refine pattern — shared helper avoids duplication
- The helper is private to the steps module (not a public API)
- Existing tests for summarize_graph.py are replaced by step-level tests

**Alternatives considered**:
- Keep summarize_graph.py as utility: Creates split responsibility — steps would be thin wrappers
- Move to prompts.py: Mixes prompt templates with orchestration logic
- Inline in each step: Duplicates the ~30-line refine algorithm

## Decision 7: Embedding Text Selection (Critical Correctness Fix)

**Decision**: EmbedStep always embeds `chunk.content` (the raw text stored in the chunk). Summary chunks store summary text as their `content`. Raw chunks store original document text as their `content`. The `Chunk.summary` field is no longer written by the pipeline.

**Rationale**:
- This is the critical correctness fix. The current bug: embedding uses `c.summary or c.content`, causing raw chunks with summaries to be embedded by summary text instead of original text — collapsing all chunks to identical vectors
- In the new design, a raw chunk's content IS its original text
- A summary chunk's content IS the summary text
- EmbedStep doesn't need conditional logic — it always embeds `content`
- The `Chunk.summary` field is preserved (FR-015) but unused by the pipeline

**Alternatives considered**:
- Keep summary field, embed conditionally: Preserves the bug-prone pattern
- Separate embedding strategies per chunk type: Over-complicated, same result
- Remove summary field entirely: Breaking change, violates FR-015

## Decision 8: StoreStep Embedding Safety Guard

**Decision**: StoreStep detects whether an EmbedStep ran by checking if any chunk has a precomputed embedding. When embeddings exist, it only stores chunks that have embeddings — skipping unembedded chunks with an error. When no chunks have embeddings, it stores all chunks and delegates embedding to the knowledge store.

**Rationale**:
- If EmbedStep partially fails (e.g., embedding service timeout on one batch), some chunks have embeddings from the pipeline's embedding model and others have none
- Storing unembedded chunks alongside embedded ones would cause ChromaDB to embed those chunks with its default model — a different model producing incompatible vectors in the same collection
- This creates a mixed vector space where similarity search produces wrong results
- Skipping unembedded chunks preserves vector space consistency at the cost of completeness
- When no EmbedStep is in the pipeline at all, all chunks are stored without embeddings, allowing the knowledge store to handle embedding uniformly

**Alternatives considered**:
- Store all chunks regardless: Creates mixed embedding model vectors in the same collection — corrupts retrieval
- Fail the entire batch if any chunk lacks embeddings: Too aggressive, discards successfully embedded chunks
- Re-embed failed chunks inline: Violates the step separation principle; EmbedStep is the embedding boundary

## Decision 9: Accurate `chunks_stored` Tracking

**Decision**: `PipelineContext` carries a `chunks_stored: int` counter that StoreStep increments only on successful batch persistence. IngestEngine reads this counter for the final `IngestResult`.

**Rationale**:
- The previous approach used `len(context.chunks)` which counts all chunks produced, including those from failed storage batches and those skipped by the embedding safety guard
- Consumers of `IngestResult.chunks_stored` (plugins, monitoring) need an accurate count of what actually made it to ChromaDB
- Tracking in PipelineContext keeps the engine step-agnostic — it doesn't need to know which step is StoreStep

**Alternatives considered**:
- Return stored count from StoreStep.execute(): Requires changing the PipelineStep protocol return type, breaking all steps
- Post-hoc query ChromaDB for count: Network round-trip, race conditions, over-engineered

## Decision 10: Single-Section Full Budget in Refine Summarization

**Decision**: When `_refine_summarize` receives a single section/chunk, it assigns `progress = 1.0` (full 100% budget) instead of using the general formula which produces 40%.

**Rationale**:
- The progressive budgeting formula `budget = max_length * (0.4 + 0.6 * progress)` is designed for multi-chunk refinement where early chunks get less space to leave room for later refinement
- With a single section, there's no refinement — the one section should use the full budget
- The general formula `progress = 0 / max(0, 1) = 0` produces `budget = 0.4 * max_length`, wasting 60% of the available space
- This commonly occurs in BodyOfKnowledgeSummaryStep when a knowledge base has only one document

**Alternatives considered**:
- Special-case in BoKSummaryStep only: Same issue could appear in any single-section scenario; fix belongs in the shared helper
