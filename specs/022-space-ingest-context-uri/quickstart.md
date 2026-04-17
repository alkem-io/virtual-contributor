# Quickstart: Space Ingest Context Enrichment & URI Tracking

**Feature Branch**: `022-space-ingest-context-uri`
**Date**: 2026-04-17

## What it does

Improves space ingestion quality in two ways:
1. **Context enrichment**: Each contribution (post, whiteboard, link) is prefixed with its parent callout's title and description, so chunked content retains hierarchical context for better RAG retrieval.
2. **URI tracking**: Entity URLs from the Alkemio platform are propagated through the pipeline to the vector store, enabling clickable source links in expert responses.

## New Configuration

None. No new environment variables or settings.

## How to verify

1. Trigger a space ingest event for a space that has callouts with contributions.
2. After ingestion, query ChromaDB directly:
   ```python
   collection.peek()  # or collection.get(limit=5, include=["metadatas", "documents"])
   ```
3. Verify:
   - Post/whiteboard documents start with the parent callout's title
   - Metadata entries contain a `uri` field with the Alkemio entity URL
   - Link contributions' `uri` is the link target, not the profile URL

## Files Changed

| File | Change |
|------|--------|
| `core/domain/ingest_pipeline.py` | Added `uri` field to `DocumentMetadata` |
| `core/domain/pipeline/steps.py` | Conditional `uri` inclusion in stored metadata |
| `plugins/ingest_space/space_reader.py` | GraphQL `url` fetching, callout context enrichment, URI propagation |
