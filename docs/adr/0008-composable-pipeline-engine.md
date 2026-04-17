# ADR 0008: Composable Ingest Pipeline Engine

## Status
Accepted

## Context
Both ingest plugins (website and space) need to chunk, embed, and store documents. Before consolidation, each plugin implemented its own ingestion logic with duplicated chunking, embedding, and storage code. Adding cross-cutting concerns (deduplication, summarization, change detection) required modifying every plugin independently.

## Decision
Introduce a **step-based pipeline engine** (`core/domain/pipeline/engine.py`) that executes an ordered sequence of `PipelineStep` implementations sharing a mutable `PipelineContext`:

1. **Step protocol**: Each step implements `async execute(chunks, context) -> list[Chunk]`. Steps are composable — plugins declare which steps to include and in what order.
2. **Shared context**: `PipelineContext` carries collection name, configuration, accumulated metrics, and inter-step state (e.g., `unchanged_chunk_hashes`, `changed_document_ids`, `orphan_ids`).
3. **Plugin-owned composition**: The engine does not validate step ordering or enforce required steps. Plugin authors are responsible for correct pipeline construction.
4. **Per-step error isolation**: Each step catches its own exceptions and records `StepMetrics` (duration, items in/out, error count). A failing step does not terminate the pipeline — remaining steps execute with whatever chunks survived.
5. **Dual embedding strategy**: Raw content chunks (`embeddingType="chunk"`) and summary chunks (`embeddingType="summary"`) coexist in the same ChromaDB collection with distinct metadata types.

### Standard step sequence

```
ChunkStep → ContentHashStep → ChangeDetectionStep → DocumentSummaryStep
  → BodyOfKnowledgeSummaryStep → EmbedStep → StoreStep → OrphanCleanupStep
```

## Consequences
- **Positive**: New pipeline concerns (e.g., content hashing, incremental embedding) are added as new steps without modifying existing ones.
- **Positive**: Plugins can omit steps they don't need (e.g., skip summarization) by simply not including them.
- **Positive**: Per-step metrics provide granular observability into pipeline performance.
- **Negative**: No engine-level validation means an incorrectly composed pipeline fails at runtime, not at startup.
- **Negative**: Mutable shared context couples steps implicitly — a step may depend on state set by a prior step without a compile-time guarantee.
