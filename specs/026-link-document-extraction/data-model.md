# Data Model: Link Document Extraction

**Feature**: 026-link-document-extraction | **Date**: 2026-04-22

## Overview

This feature does not introduce new Pydantic models, dataclasses, or database schema changes. It changes the _content_ written into existing data structures, not their shape. The core ingest pipeline data model (`Document`, `Chunk`, `DocumentMetadata`, `IngestResult`) remains unchanged.

## Data Flow Changes

### Document.content for Link Contributions

**Before**: Link contributions produced a `Document` whose `content` field contained only lightweight metadata:

```
<callout context>

# <link title>

<link description>

URL: <uri>
```

**After**: When document text is successfully extracted, the `content` field contains the full document body:

```
# <link title>

<link description>

<extracted document text>
```

When extraction fails or is not applicable, the content falls back to the previous metadata-only format (including callout context and URL).

### DocumentMetadata

No changes. The existing fields are used as follows for link contributions:

| Field | Value |
|---|---|
| `document_id` | `link["id"]` from the GraphQL response |
| `source` | `link:<id>` |
| `type` | `DocumentType.LINK.value` ("link") |
| `title` | `link.profile.displayName` |
| `uri` | `link.uri` or `link.profile.url` |

### fetch_url() Return Type

`fetch_url()` returns `tuple[bytes, str] | None`:
- `bytes` -- the raw response body
- `str` -- the Content-Type header value (MIME type only, parameters stripped)
- `None` -- on any failure (network error, non-200 status, oversized response, auth failure)

This is not a persisted data model; it is an in-memory return type used within the space reader during ingestion.

### Stats Dictionary

`read_space_tree()` tracks fetch statistics via a simple dict passed through the tree traversal:

```python
stats = {"fetched": 0, "skipped": 0}
```

- `fetched`: Count of link contributions where text was successfully extracted from the fetched body.
- `skipped`: Count of link contributions where fetching returned `None` or extraction returned `None`.

These stats are logged at the end of `read_space_tree()` and are not persisted.

## Unchanged Models

| Model | File | Impact |
|---|---|---|
| `Document` | `core/domain/ingest_pipeline.py` | No change -- `content` field type (`str`) unchanged; only the value written by the space reader changes |
| `DocumentMetadata` | `core/domain/ingest_pipeline.py` | No change -- `uri` field already existed |
| `Chunk` | `core/domain/ingest_pipeline.py` | No change |
| `IngestResult` | `core/domain/ingest_pipeline.py` | No change |
| `DocumentType` | `core/domain/ingest_pipeline.py` | No change -- `LINK` enum value already existed |
| `PipelineContext` | `core/domain/pipeline/engine.py` | No change |
