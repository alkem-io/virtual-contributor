# Spec: Incremental Embedding -- Embed Documents as They Finish Summarization

**Story:** alkem-io/alkemio#1826
**Epic:** alkem-io/alkemio#1820

---

## User Value

Pipeline operators and end-users experience 20+ minutes of unnecessary idle time during ingestion because all documents must finish summarization before any embedding begins. By interleaving embedding with summarization -- embedding each document's chunks immediately after its summary completes -- we overlap LLM-bound (summarization) and GPU-bound (embedding) I/O, reducing total wall-clock ingest time significantly.

---

## Scope

### In Scope

1. Modify `DocumentSummaryStep` to accept an `EmbeddingsPort` and embed each document's chunks immediately after its summary is produced.
2. Update `EmbedStep` to skip chunks that were already embedded during the summarization phase (incremental embedding).
3. Update both ingest plugins (`ingest_space`, `ingest_website`) to pass `EmbeddingsPort` to `DocumentSummaryStep`.
4. Preserve existing change-detection optimization: chunks with pre-loaded embeddings from `ChangeDetectionStep` are still skipped.
5. Ensure `BodyOfKnowledgeSummaryStep` summary chunks (produced after all document summaries) are still embedded by the trailing `EmbedStep`.
6. Unit tests covering incremental embedding behavior, skip logic, and error isolation.

### Out of Scope

- Concurrent (parallel) document summarization (that is story #1823).
- Streaming pipeline engine redesign (Option C from the issue).
- Background async embedding worker with a queue (Option B from the issue).
- Changes to `StoreStep`, `OrphanCleanupStep`, or `ChangeDetectionStep` internals.
- Performance benchmarking or metrics dashboards.

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-1 | After each document summary completes, that document's content chunks are embedded immediately (before summarization of the next document begins). | Unit test: mock EmbeddingsPort records embed calls interleaved with LLM invoke calls. |
| AC-2 | The document's summary chunk itself is also embedded immediately after summarization. | Unit test: summary chunk has a non-None embedding after DocumentSummaryStep completes. |
| AC-3 | `EmbedStep` skips all chunks that already have embeddings (from incremental embedding or change detection). | Unit test: EmbedStep with pre-embedded chunks produces zero embed calls. |
| AC-4 | Chunks from documents below the chunk_threshold (not summarized) are still embedded by the trailing `EmbedStep`. | Unit test: below-threshold document chunks get embeddings from EmbedStep. |
| AC-5 | Embedding failure for one document's chunks during summarization does not prevent summarization of remaining documents. | Unit test: FailingEmbeddings on first doc, second doc still summarized and embedded. |
| AC-6 | Both ingest plugins pass `EmbeddingsPort` to `DocumentSummaryStep`. | Code inspection + integration-level pipeline tests. |
| AC-7 | Full existing test suite passes without modification (backward compatible). | CI gate. |

---

## Constraints

- Python 3.12, async/await throughout.
- No new dependencies; `EmbeddingsPort` is an existing port.
- `DocumentSummaryStep.__init__` signature change must be backward-compatible: `embeddings_port` defaults to `None` so existing callers without it still work (they just skip incremental embedding).
- The pipeline step protocol (`PipelineStep`) is unchanged.
- All embedding uses `chunk.content` as the text to embed (consistent with current `EmbedStep` behavior).
