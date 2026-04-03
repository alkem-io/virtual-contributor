# Pipeline Composition API Contract

**Feature**: 004-pipeline-engine-redesign
**Date**: 2026-04-02

## Overview

The pipeline engine exposes a composable API for plugin authors to assemble ingestion pipelines from independent steps. This is an internal contract between `core/domain/pipeline/` and `plugins/*/plugin.py`.

## PipelineStep Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str:
        """Unique step identifier for metrics tracking."""
        ...

    async def execute(self, context: PipelineContext) -> None:
        """Transform or augment the pipeline context.

        Steps MUST:
        - Catch per-item errors and append to context.errors
        - NOT halt on individual item failures
        - Record metrics in context.metrics[self.name]
        """
        ...
```

## IngestEngine API

```python
class IngestEngine:
    def __init__(self, steps: list[PipelineStep]) -> None:
        """Create engine with ordered steps."""
        ...

    async def run(
        self,
        documents: list[Document],
        collection_name: str,
    ) -> IngestResult:
        """Execute all steps in order, return result."""
        ...
```

## Built-in Steps

### ChunkStep

```python
ChunkStep(chunk_size: int = 2000, chunk_overlap: int = 400)
```

No port dependencies.

### DocumentSummaryStep

```python
DocumentSummaryStep(
    llm_port: LLMPort,
    summary_length: int = 2000,
    concurrency: int = 8,
)
```

Requires: LLMPort

### BodyOfKnowledgeSummaryStep

```python
BodyOfKnowledgeSummaryStep(
    llm_port: LLMPort,
    summary_length: int = 2000,
)
```

Requires: LLMPort

### EmbedStep

```python
EmbedStep(
    embeddings_port: EmbeddingsPort,
    batch_size: int = 50,
)
```

Requires: EmbeddingsPort

### StoreStep

```python
StoreStep(
    knowledge_store_port: KnowledgeStorePort,
    batch_size: int = 50,
)
```

Requires: KnowledgeStorePort

**Embedding safety**: When any chunk has a precomputed embedding (EmbedStep ran), StoreStep only stores chunks with embeddings — chunks without embeddings are skipped to prevent embedding model mismatch. When no chunks have embeddings (no EmbedStep), all chunks are stored and embedding is delegated to the knowledge store. Tracks successful persists via `context.chunks_stored`.

## Composition Examples

### Minimal pipeline (no summarization)

```python
engine = IngestEngine(steps=[
    ChunkStep(chunk_size=2000),
    EmbedStep(embeddings_port=embeddings),
    StoreStep(knowledge_store_port=store),
])
result = await engine.run(documents, "my-collection")
```

### Full pipeline (with summarization)

```python
engine = IngestEngine(steps=[
    ChunkStep(chunk_size=9000, chunk_overlap=500),
    DocumentSummaryStep(llm_port=llm, summary_length=2000),
    BodyOfKnowledgeSummaryStep(llm_port=llm, summary_length=2000),
    EmbedStep(embeddings_port=embeddings, batch_size=50),
    StoreStep(knowledge_store_port=store, batch_size=50),
])
result = await engine.run(documents, "space-collection")
```

## Step Ordering

The engine does NOT validate step ordering. Plugin authors are responsible for correct composition:

1. **ChunkStep** must precede all other steps (produces chunks)
2. **DocumentSummaryStep** must precede **BodyOfKnowledgeSummaryStep** (produces document summaries)
3. **EmbedStep** must precede **StoreStep** (produces embeddings)
4. Summary steps are optional — omitting them skips LLM calls entirely
5. **EmbedStep** is optional — omitting it causes StoreStep to delegate embedding to the knowledge store. However, if EmbedStep is present and partially fails, StoreStep will skip unembedded chunks to maintain vector space consistency.
