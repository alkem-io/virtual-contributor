# Quickstart: Link Document Extraction

**Feature**: 026-link-document-extraction | **Date**: 2026-04-22

## Prerequisites

1. **Python 3.12** with Poetry installed.
2. **Extraction libraries** declared in `pyproject.toml` and installed:
   ```bash
   poetry install
   ```
   Verify the following are available:
   - `pypdf` (^5.0) -- PDF text extraction
   - `python-docx` (^1.1) -- DOCX text extraction
   - `openpyxl` (^3.1) -- XLSX text extraction
   - `beautifulsoup4` (^4.14) -- HTML text extraction
   - `httpx` (^0.27.2) -- async HTTP client

3. **Alkemio deployment** accessible with:
   - GraphQL endpoint URL
   - Kratos authentication credentials (email + password)
   - A space containing link contributions pointing to documents (PDF, DOCX, etc.)

## Running the Ingest

Start the ingest-space plugin:

```bash
PLUGIN_TYPE=ingest-space poetry run python main.py
```

The plugin listens for `IngestBodyOfKnowledge` events on RabbitMQ. When a space ingestion is triggered, the pipeline will:

1. Traverse the space tree via GraphQL.
2. For each link contribution, fetch the linked URL via authenticated HTTP.
3. Detect the document format (MIME type + magic bytes).
4. Extract text from supported formats (PDF, DOCX, XLSX, HTML, plain text).
5. Create `Document` objects with the extracted text as content.
6. Proceed through the standard pipeline (chunk, hash, change-detect, summarize, embed, store).

## Verifying Extraction

### Check Logs

Look for log messages from the space reader indicating successful extraction:

```
Extracted 15432 chars from https://dev.alkem.io/api/private/rest/storage/document/abc-123 (application/pdf)
```

At the end of ingestion, a summary line appears:

```
Space tree: emitted 42 unique documents (link bodies fetched=8, skipped=2)
```

### Check Knowledge Store

Query the ChromaDB collection for link-type documents to verify chunks contain extracted text rather than just URL metadata:

```python
# Example: inspect stored chunks for a link document
result = await knowledge_store.get(
    collection="<bok-id>-knowledge",
    where={"type": "link"},
    include=["documents", "metadatas"],
)
for doc, meta in zip(result.documents, result.metadatas):
    print(f"Title: {meta['title']}")
    print(f"Content preview: {doc[:200]}...")
    print()
```

If extraction worked, the content will contain substantive text from the linked document, not just `URL: https://...`.

### Check Fallback Behavior

For links that could not be fetched or extracted, the content will contain the metadata fallback:

```
<callout context>

# <link title>

<link description>

URL: <uri>
```

Log messages for failed fetches:
```
Link fetch returned 404 for https://example.com/missing.pdf
Failed to fetch https://example.com/broken: <error details>
Link body too large (15728640 bytes) for https://example.com/huge.zip -- skipping
```

## Running Tests

```bash
# All tests for this feature
poetry run pytest tests/plugins/test_link_extractor.py tests/plugins/test_graphql_client_fetch.py tests/plugins/test_ingest_space.py -v

# Full test suite
poetry run pytest
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| All links show "skipped" in stats | Authentication failure or network issue | Check Kratos credentials and network connectivity |
| PDFs show metadata-only content | `pypdf` not installed | Run `poetry install` to ensure all dependencies are present |
| Internal Alkemio links fail with 404 | URI rewriting not matching | Verify the link URI path starts with `/api/` or `/rest/`; check that the GraphQL endpoint is correctly configured |
| "Link body too large" for valid documents | Document exceeds 10 MB | This is by design; the size cap protects memory usage |
| Extraction returns empty text for a PDF | PDF contains only images (scanned document) | Expected -- pypdf cannot OCR scanned pages; the PDF will be indexed with metadata only |
