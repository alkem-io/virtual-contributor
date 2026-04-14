# Research: Incremental Embedding

**Feature Branch**: `story/1826-incremental-embedding`
**Date**: 2026-04-14

## Research Tasks

### R1: Pipeline bottleneck analysis — summarization vs. embedding ordering

**Context**: The ingest pipeline processes documents through ordered steps: Chunk -> ContentHash -> ChangeDetection -> DocumentSummary -> BoKSummary -> Embed -> Store -> OrphanCleanup. Summarization is LLM-bound (network I/O to LLM provider) and embedding is GPU-bound (network I/O to embedding service). Currently, all documents must complete summarization before any embedding begins, creating idle time on the embedding service.

**Findings**:

Three options were evaluated in the story (alkemio#1826):

1. **Option A — Per-document embed after summary**: Extend `DocumentSummaryStep` with an optional `EmbeddingsPort`. After each document's summary is produced, immediately embed that document's content chunks and the new summary chunk. The existing `EmbedStep` remains as a safety net.

2. **Option B — Background embedding worker**: Introduce an async queue where summarized chunks are pushed for background embedding. More complex, requires coordination primitives.

3. **Option C — Streaming pipeline engine**: Redesign the pipeline engine to support streaming/overlapping steps. Major architectural change.

**Decision**: Option A — Per-document embed after summary.
**Rationale**: Minimal change (one optional constructor param, one private helper method). No pipeline engine changes. No new abstractions. Full backward compatibility via `embeddings_port=None` default. The embedding service is called per-document rather than waiting for all documents, overlapping the two I/O phases naturally.
**Alternatives rejected**: Option B adds unnecessary complexity for the current use case. Option C is a major architectural change deferred to a future story.

---

### R2: Embedding skip semantics and safety-net behavior

**Context**: `EmbedStep` already skips chunks that have embeddings. Need to confirm this behavior serves as a reliable safety net when `DocumentSummaryStep` embeds chunks inline.

**Findings**:

`EmbedStep.execute()` filters chunks with `[c for c in context.chunks if c.embedding is None]`. This means:
- Chunks embedded inline by `DocumentSummaryStep` are automatically skipped.
- Chunks from below-threshold documents (no summary, no inline embedding) are still embedded by `EmbedStep`.
- The BoK summary chunk (produced by `BodyOfKnowledgeSummaryStep`, after `DocumentSummaryStep`) is still embedded by `EmbedStep`.
- If inline embedding fails for a document, those chunks remain un-embedded and `EmbedStep` picks them up.

**Decision**: No changes to `EmbedStep`. Its existing skip logic provides the safety-net behavior.
**Rationale**: The `embedding is None` check is the correct invariant. No new code paths needed.

---

### R3: Batch size alignment between inline and standalone embedding

**Context**: `EmbedStep` uses a default batch size of 50 for embedding calls. The inline embedding in `DocumentSummaryStep` should use the same default to avoid behavioral differences.

**Findings**:

The batch size controls how many texts are sent per `embed()` call. Using the same default (50) ensures:
- Consistent memory usage per batch.
- Consistent API call patterns to the embedding service.
- No surprise differences when switching between inline and standalone embedding.

A single document typically has 5-50 chunks, so most documents will be embedded in a single batch call.

**Decision**: Default `embed_batch_size=50` in `DocumentSummaryStep`, matching `EmbedStep`.
**Rationale**: Consistency with existing behavior. Most documents fit in one batch anyway.

---

### R4: Error handling strategy for inline embedding

**Context**: If inline embedding fails for a document, the pipeline should not halt. The error should be captured and the safety-net `EmbedStep` should retry those chunks.

**Findings**:

The existing `PipelineContext.errors` list is the standard mechanism for non-fatal pipeline errors. `DocumentSummaryStep` already uses it for summarization failures. The inline embedding error handling follows the same pattern:
1. Catch exceptions per-batch.
2. Append error message to `context.errors`.
3. Continue to the next document.
4. `EmbedStep` later picks up un-embedded chunks.

**Decision**: Per-batch error capture in `context.errors`. No re-raising.
**Rationale**: Consistent with existing summarization error handling. The safety-net `EmbedStep` provides automatic retry semantics.

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Approach | Option A: per-document embed after summary | Minimal change, full backward compat, no engine changes |
| Safety net | No changes to `EmbedStep` | Existing `embedding is None` check handles all cases |
| Batch size | Default 50, matching `EmbedStep` | Consistency, most documents fit in one batch |
| Error handling | Per-batch capture in `context.errors` | Consistent with existing patterns, `EmbedStep` retries |
| Backward compat | `embeddings_port=None` default | Constructor remains compatible with all existing callers |
