# Spec: Incremental Embedding After Summarization

**Story:** alkem-io/alkemio#1826
**Status:** Draft
**Created:** 2026-04-08

## User Value

Reduce total ingest pipeline wall-clock time by overlapping summarization (LLM-bound I/O) with embedding (GPU-bound I/O). Currently, all document chunks wait idle after summarization until every document finishes before embedding begins. By embedding each document's chunks immediately after its summary completes, the pipeline exploits the fact that summarization and embedding use different resources (LLM vs GPU), enabling parallel utilization and cutting total pipeline time significantly.

## Scope

- Modify `DocumentSummaryStep` to accept an `EmbeddingsPort` and embed each document's chunks immediately after that document's summary is produced.
- Ensure the existing `EmbedStep` gracefully handles chunks that were already embedded by `DocumentSummaryStep` (skip pre-embedded chunks, which it already does).
- Maintain backward compatibility: pipelines that do not use `DocumentSummaryStep` continue to work unchanged with `EmbedStep` alone.
- Update both plugin pipeline assemblies (`ingest_space`, `ingest_website`) to pass the embeddings port to `DocumentSummaryStep`.

## Out of Scope

- Background embedding workers or async queues (Option B from the story).
- Streaming pipeline engine redesign (Option C from the story).
- Concurrent summarization across documents (covered by sibling story #1823).
- Changes to `BodyOfKnowledgeSummaryStep` -- its single summary chunk can be embedded by the existing `EmbedStep` which runs after.
- Changes to the pipeline engine itself (`IngestEngine`).

## Acceptance Criteria

1. After `DocumentSummaryStep` completes summarization of a document, all of that document's content chunks (that need embedding) are embedded before the next document's summarization begins.
2. The summary chunk produced for each document is also embedded immediately after creation.
3. `EmbedStep` continues to embed any remaining un-embedded chunks (e.g., BoK summary, chunks from documents below the chunk threshold that were not summarized).
4. No change in the final stored data -- the same chunks with the same embeddings and metadata end up in ChromaDB.
5. Existing tests pass without modification (EmbedStep skip-pre-embedded behavior is already tested).
6. New unit tests cover the incremental embedding behavior within DocumentSummaryStep.
7. Pipeline assembly in both ingest plugins passes embeddings_port to DocumentSummaryStep.

## Constraints

- Python 3.12, async throughout.
- No new dependencies.
- Must not break the pipeline step protocol (`PipelineStep` with `name` property and `async execute(context)` method).
- Embedding is done via `EmbeddingsPort.embed(texts)` which accepts batches.
- Change detection pre-loads embeddings for unchanged chunks; these must not be re-embedded.
