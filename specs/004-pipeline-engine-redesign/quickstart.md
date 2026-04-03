# Quickstart: Composable Ingest Pipeline Engine

**Feature**: 004-pipeline-engine-redesign
**Branch**: `004-pipeline-engine-redesign`

## Prerequisites

```bash
poetry install
```

## Run Tests

```bash
# All tests
poetry run pytest

# Pipeline step tests only
poetry run pytest tests/core/domain/test_pipeline_steps.py -v

# Lint and type check
poetry run ruff check core/ plugins/ tests/
poetry run pyright core/ plugins/
```

## Key Files

| File | Purpose |
|---|---|
| `core/domain/pipeline/engine.py` | IngestEngine, PipelineStep protocol, PipelineContext |
| `core/domain/pipeline/steps.py` | ChunkStep, EmbedStep, StoreStep, DocumentSummaryStep, BoKSummaryStep |
| `core/domain/pipeline/prompts.py` | Summarization prompt templates |
| `core/domain/ingest_pipeline.py` | Data classes (Document, Chunk, IngestResult, etc.) |
| `plugins/ingest_website/plugin.py` | Website ingestion — composes pipeline |
| `plugins/ingest_space/plugin.py` | Space ingestion — composes pipeline |
| `tests/core/domain/test_pipeline_steps.py` | Step unit tests |

## Pipeline Composition

```python
from core.domain.pipeline import IngestEngine, ChunkStep, EmbedStep, StoreStep
from core.domain.pipeline import DocumentSummaryStep, BodyOfKnowledgeSummaryStep

# Without summarization
engine = IngestEngine(steps=[
    ChunkStep(chunk_size=2000),
    EmbedStep(embeddings_port=embeddings),
    StoreStep(knowledge_store_port=store),
])

# With summarization
engine = IngestEngine(steps=[
    ChunkStep(chunk_size=2000),
    DocumentSummaryStep(llm_port=llm),
    BodyOfKnowledgeSummaryStep(llm_port=llm),
    EmbedStep(embeddings_port=embeddings),
    StoreStep(knowledge_store_port=store),
])

result = await engine.run(documents, "collection-name")
```

## Data Flow

```
Documents
    |
    v
ChunkStep --- splits documents into Chunks (embeddingType="chunk")
    |
    v
DocumentSummaryStep --- adds summary Chunks for docs with >3 chunks (embeddingType="summary")
    |                    populates context.document_summaries for BoK step
    v
BoKSummaryStep --- adds one overview Chunk (documentId="body-of-knowledge-summary")
    |
    v
EmbedStep --- calls EmbeddingsPort in batches, attaches embeddings to all chunks
    |
    v
StoreStep --- persists embedded chunks to ChromaDB in batches
    |           skips unembedded chunks when EmbedStep ran (embedding safety)
    |           tracks actual stored count in context.chunks_stored
    v
IngestResult (collection_name, documents_processed, chunks_stored, errors, success)
```

**Note**: `chunks_stored` reflects what was actually persisted, not total chunks produced. If EmbedStep partially fails, StoreStep skips unembedded chunks to prevent embedding model mismatch in ChromaDB.

## Testing a Step in Isolation

```python
from core.domain.pipeline.engine import PipelineContext
from core.domain.pipeline.steps import ChunkStep
from core.domain.ingest_pipeline import Document, DocumentMetadata

# Create context with test documents
context = PipelineContext(
    collection_name="test",
    documents=[
        Document(
            content="Long text content...",
            metadata=DocumentMetadata(document_id="doc-1", source="test"),
        )
    ],
)

# Execute step
step = ChunkStep(chunk_size=500, chunk_overlap=100)
await step.execute(context)

# Assert results
assert len(context.chunks) > 0
assert all(c.metadata.embedding_type == "chunk" for c in context.chunks)
```
