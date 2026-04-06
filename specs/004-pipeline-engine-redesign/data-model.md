# Data Model: Composable Ingest Pipeline Engine

**Feature**: 004-pipeline-engine-redesign
**Date**: 2026-04-02

## Existing Entities (Preserved — FR-015)

### DocumentType (Enum)

| Value | Description |
|---|---|
| KNOWLEDGE | Generic knowledge document |
| SPACE | Top-level Alkemio space |
| SUBSPACE | Nested space |
| CALLOUT | Space callout |
| PDF_FILE | PDF attachment |
| SPREADSHEET | Excel/CSV |
| DOCUMENT | Word document |
| LINK | External URL |
| MEMO | Internal memo |
| WHITEBOARD | Visual whiteboard |
| COLLECTION | Document collection |
| POST | Discussion post |
| NONE | Untyped |

No changes.

### DocumentMetadata (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| document_id | str | required | Unique identifier for source document |
| source | str | required | Source URL or reference |
| type | str | "knowledge" | Document type |
| title | str | "" | Human-readable title |
| embedding_type | str | "knowledge" | Embedding category |

**Change**: `embedding_type` field will be set to `"chunk"` for raw chunks and `"summary"` for summary entries by the pipeline steps (previously always inherited as `"knowledge"` from document metadata).

### Chunk (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| content | str | required | Text content (raw text OR summary text) |
| metadata | DocumentMetadata | required | Metadata (shared with parent document or custom for summaries) |
| chunk_index | int | required | 0-based position in document |
| summary | str \| None | None | DEPRECATED — no longer written by pipeline |
| embedding | list[float] \| None | None | Precomputed embedding vector |

**Change**: `summary` field is no longer written by the pipeline. Summary text is stored as `content` in a separate summary Chunk with its own metadata. Field preserved for backward compatibility (FR-015).

### Document (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| content | str | required | Full document text |
| metadata | DocumentMetadata | required | Document-level metadata |
| chunks | list[Chunk] \| None | None | Optional pre-chunked chunks |

No changes.

### IngestResult (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| collection_name | str | required | ChromaDB collection name |
| documents_processed | int | required | Number of input documents |
| chunks_stored | int | required | Chunks successfully persisted |
| errors | list[str] | [] | Non-fatal error messages |
| success | bool | True | Overall success flag |

No changes.

## New Entities

### PipelineStep (Protocol)

```python
@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str: ...

    async def execute(self, context: PipelineContext) -> None: ...
```

| Member | Type | Description |
|---|---|---|
| name | property -> str | Step identifier for metrics tracking |
| execute | async method | Transform/augment the shared pipeline context |

### StepMetrics (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| duration | float | 0.0 | Wall-clock seconds for step execution |
| items_in | int | 0 | Number of items entering the step |
| items_out | int | 0 | Number of items after step execution |
| error_count | int | 0 | Errors encountered during step |

### PipelineContext (Dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| collection_name | str | required | Target ChromaDB collection |
| documents | list[Document] | required | Input documents |
| chunks | list[Chunk] | [] | Accumulated chunks (raw + summary) |
| document_summaries | dict[str, str] | {} | doc_id -> summary text (for BoK step) |
| errors | list[str] | [] | Accumulated error messages |
| metrics | dict[str, StepMetrics] | {} | step_name -> metrics |
| chunks_stored | int | 0 | Count of chunks successfully persisted by StoreStep |

**Relationships**:
- `documents` is read by ChunkStep (input)
- `chunks` is written by ChunkStep, DocumentSummaryStep, BoKSummaryStep; read by EmbedStep, StoreStep
- `document_summaries` is written by DocumentSummaryStep; read by BoKSummaryStep

### IngestEngine (Class)

| Method | Signature | Description |
|---|---|---|
| \_\_init\_\_ | (steps: list[PipelineStep]) | Accept ordered list of steps |
| run | async (documents: list[Document], collection_name: str) -> IngestResult | Execute all steps, return result |

**Behavior**: Creates PipelineContext, executes each step in order (recording metrics, with step-level error boundaries), assembles IngestResult from final context state. Uses `context.chunks_stored` (set by StoreStep) for the result's `chunks_stored` count. Does NOT validate step ordering (per spec clarification).

## Step Implementations

### ChunkStep

- **Reads**: context.documents
- **Writes**: context.chunks (raw chunks with embeddingType="chunk")
- **Config**: chunk_size (int, default 2000), chunk_overlap (int, default 400)
- **Ports**: None
- **Behavior**: Uses RecursiveCharacterTextSplitter. Creates Chunk objects with metadata.embedding_type = "chunk". Documents producing 0 chunks are skipped silently.

### DocumentSummaryStep

- **Reads**: context.chunks
- **Writes**: Appends summary Chunks to context.chunks; populates context.document_summaries
- **Config**: summary_length (int, default 10000), concurrency (int, default 8)
- **Ports**: LLMPort (constructor injected)
- **Behavior**: Groups chunks by document_id. For each document with >3 chunks, generates summary via refine pattern with rich prompts (FR-006) and progressive length budgeting (FR-007). Creates new Chunk with:
  - content = summary text
  - metadata.document_id = "{original_id}-summary"
  - metadata.embedding_type = "summary"
  - chunk_index = 0
- Stores summary text in context.document_summaries[original_id] for BoK step.
- Uses asyncio.Semaphore for concurrency control (FR-012).
- Per-document errors are captured without halting (FR-009).

### BodyOfKnowledgeSummaryStep

- **Reads**: context.document_summaries, context.chunks
- **Writes**: Appends one BoK summary Chunk to context.chunks
- **Config**: summary_length (int, default 10000)
- **Ports**: LLMPort (constructor injected)
- **Behavior**: Identifies raw document chunks by filtering on `embedding_type != "summary"`. For each unique document_id in raw chunks:
  - If document_summaries has a summary for it, use that
  - Otherwise, concatenate raw chunk content
- Generates single overview via refine pattern with BoK-specific prompt.
- Creates Chunk with:
  - content = BoK summary text
  - metadata.document_id = "body-of-knowledge-summary"
  - metadata.type = "bodyOfKnowledgeSummary"
  - metadata.embedding_type = "summary"
  - chunk_index = 0

### EmbedStep

- **Reads**: context.chunks
- **Writes**: chunk.embedding for each chunk
- **Config**: batch_size (int, default 50)
- **Ports**: EmbeddingsPort (constructor injected)
- **Behavior**: Processes chunks in batches. Always embeds chunk.content. Skips chunks that already have embeddings. Per-batch errors are captured without halting (FR-009).

### StoreStep

- **Reads**: context.chunks (with embeddings)
- **Writes**: Persists to ChromaDB via KnowledgeStorePort; increments context.chunks_stored on success
- **Config**: batch_size (int, default 50)
- **Ports**: KnowledgeStorePort (constructor injected)
- **Behavior**: Processes chunks in batches. Builds metadata dict:
  - documentId, source, type, title, embeddingType, chunkIndex
- Creates ChromaDB `documentId` as `{document_id}-chunk{chunk_index}` for raw chunks (matching original repo format), and uses the chunk's `document_id` as-is for summary/BoK entries.
- Creates ChromaDB entry IDs as `{storage_id}-{chunk_index}`.
- **Embedding requirement**: Only stores chunks that have precomputed embeddings. Chunks without embeddings are skipped with an error. The current ChromaDB adapter requires precomputed embeddings (`embedding_function=None`), making EmbedStep a required predecessor.
- Calls knowledge_store_port.ingest() with precomputed embeddings.
- Increments context.chunks_stored only on successful batch persistence.
- Per-batch errors are captured without halting (FR-009).
- Insert-only — never deletes (FR-016).

## ChromaDB Entry Structure (Post-Ingestion)

For a knowledge base with N documents, where M documents have >3 chunks:

| Entry Type | Count | documentId | embeddingType | type | Content |
|---|---|---|---|---|---|
| Raw chunk | total chunks | original doc ID | "chunk" | document type | Original text |
| Doc summary | M | "{doc_id}-summary" | "summary" | document type | Summary text |
| BoK summary | 1 | "body-of-knowledge-summary" | "summary" | "bodyOfKnowledgeSummary" | Overview text |

**Total entries** = total_chunks + M + 1 (matches SC-004)
