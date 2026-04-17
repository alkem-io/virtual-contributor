# Data Model 019: Batched Ingest Pipeline Processing

**Date:** 2026-04-15

## PipelineContext Changes

`PipelineContext` is a `@dataclass` in `core/domain/pipeline/engine.py`. Two new fields are added to support batched execution.

### New Fields

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `all_document_ids` | `set[str]` | `field(default_factory=set)` | The complete set of document IDs across the entire ingest corpus. Set by `_run_batched()` on each batch context so that `ChangeDetectionStep` can distinguish "doc in a different batch" from "doc was removed." Empty in sequential mode (falls back to current-batch document IDs). |
| `raw_chunks_by_doc` | `dict[str, list[str]]` | `field(default_factory=dict)` | Maps document_id to a list of raw chunk content strings. Populated by `_run_batched()` after each batch's steps complete (extracting content from chunks with `embedding_type="chunk"`). Used by `BodyOfKnowledgeSummaryStep` in finalize mode to access chunk content that was already persisted and discarded from earlier batches. Empty in sequential mode. |

### Full PipelineContext Dataclass (post-change)

```python
@dataclass
class PipelineContext:
    collection_name: str
    documents: list[Document]
    chunks: list[Chunk] = field(default_factory=list)
    document_summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, StepMetrics] = field(default_factory=dict)
    chunks_stored: int = 0
    unchanged_chunk_hashes: set[str] = field(default_factory=set)
    orphan_ids: set[str] = field(default_factory=set)
    removed_document_ids: set[str] = field(default_factory=set)
    changed_document_ids: set[str] = field(default_factory=set)
    chunks_skipped: int = 0
    chunks_deleted: int = 0
    change_detection_ran: bool = False
    all_document_ids: set[str] = field(default_factory=set)       # NEW
    raw_chunks_by_doc: dict[str, list[str]] = field(default_factory=dict)  # NEW
```

### Field Usage by Mode

| Field | Sequential Mode | Batch Context | Finalize Context |
|-------|----------------|---------------|------------------|
| `all_document_ids` | Empty (unused) | Full corpus document IDs | Full corpus document IDs |
| `raw_chunks_by_doc` | Empty (unused) | Empty (not used in batch) | Accumulated from all batches |
| `documents` | All documents | Batch slice only | All documents |
| `chunks` | All chunks from all steps | Batch chunks only | Empty initially; finalize steps append |
| `document_summaries` | Populated by DocSummaryStep | Batch-local summaries | Merged from all batches |
| `orphan_ids` | From ChangeDetection | Batch-local orphans | Merged from all batches |

## IngestEngine Constructor Changes

### Before

```python
class IngestEngine:
    def __init__(self, steps: list[PipelineStep]) -> None:
        self._steps = steps
```

### After

```python
class IngestEngine:
    def __init__(
        self,
        steps: list[PipelineStep] | None = None,
        *,
        batch_steps: list[PipelineStep] | None = None,
        finalize_steps: list[PipelineStep] | None = None,
        batch_size: int = 5,
    ) -> None:
```

### Validation Rules

| Condition | Result |
|-----------|--------|
| `steps is not None and batch_steps is not None` | `ValueError("Cannot specify both 'steps' and 'batch_steps'")` |
| `steps is None and batch_steps is None` | `ValueError("Must specify either 'steps' or 'batch_steps'")` |
| `batch_steps is not None and finalize_steps is None` | `ValueError("'finalize_steps' is required when using 'batch_steps'")` |
| `batch_size < 1` | Clamped to 1 via `max(1, batch_size)` |

### New Methods

| Method | Visibility | Purpose |
|--------|-----------|---------|
| `_run_batched(documents, collection_name)` | Private | Partitions documents, runs batch_steps per batch, accumulates state, runs finalize_steps, returns IngestResult |
| `_run_steps(steps, context, metrics_suffix="")` | Private | Shared helper extracted from sequential mode. Runs steps in order with metrics, error handling, and destructive-step gating. |
| `_build_result(context, doc_count)` | Static | Constructs IngestResult from PipelineContext. Extracted to share between sequential and batched paths. |

### Dispatch Logic

```python
async def run(self, documents, collection_name) -> IngestResult:
    if self._batch_steps is not None:
        return await self._run_batched(documents, collection_name)
    return await self._run_sequential(documents, collection_name)
```

## Config Changes

### core/config.py

| Before | After | Default | Env Var |
|--------|-------|---------|---------|
| `batch_size: int = 20` | `ingest_batch_size: int = 5` | 5 | `INGEST_BATCH_SIZE` |

The rename disambiguates from other batch_size parameters (e.g., EmbedStep's internal batch_size of 50, StoreStep's batch_size of 50) and the default was reduced from 20 to 5 for a tighter failure blast radius.

## Plugin Constructor Changes

Both `IngestWebsitePlugin` and `IngestSpacePlugin` gain an `ingest_batch_size` keyword parameter:

```python
def __init__(
    self,
    ...,
    *,
    ingest_batch_size: int = 5,
) -> None:
    ...
    self._ingest_batch_size = max(1, ingest_batch_size)
```

### main.py Injection

```python
if "ingest_batch_size" in sig.parameters:
    deps["ingest_batch_size"] = config.ingest_batch_size
```

## Step Changes

### ChangeDetectionStep._detect()

Changed line for removed-document detection:

```python
# Before:
context.removed_document_ids = existing_doc_ids - current_doc_ids

# After:
all_ids = context.all_document_ids if context.all_document_ids else current_doc_ids
context.removed_document_ids = existing_doc_ids - all_ids
```

When `all_document_ids` is populated (batched mode), documents present in other batches are not falsely flagged as removed.

### BodyOfKnowledgeSummaryStep.execute()

New branch at the start of section collection:

```python
if context.raw_chunks_by_doc:
    # Batched finalize: use pre-accumulated raw chunk content
    seen_doc_ids = list(dict.fromkeys(
        doc.metadata.document_id
        for doc in context.documents
        if doc.metadata.document_id in context.raw_chunks_by_doc
    ))
    chunks_by_doc = context.raw_chunks_by_doc
else:
    # Sequential: extract from chunks list (existing behavior)
    ...
```

This enables the BoK step to generate a corpus summary from raw chunk content that was already persisted and discarded from earlier batches.
