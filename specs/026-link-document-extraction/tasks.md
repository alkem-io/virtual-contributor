# Tasks: Link Document Extraction

**Input**: Design documents from `specs/026-link-document-extraction/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Not included in this implementation. The P4 constitution check notes a test coverage gap for `link_extractor` and `fetch_url()` that should be addressed in a follow-up.

**Organization**: Tasks are grouped by user story phases. Phase 1 is a foundational prerequisite (async conversion) that enables the async fetch integration in later phases.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Plugins**: `plugins/` at repository root
- **Core domain**: `core/` at repository root (not modified in this feature)

---

## Phase 1: Foundational -- Async Conversion

**Purpose**: Convert space reader traversal functions from sync to async to enable non-blocking HTTP fetch calls within the tree walk.

- [X] T001 Convert `_process_space()` from sync to `async def` in `plugins/ingest_space/space_reader.py`. Add `graphql_client` and `stats` parameters to the function signature. Update all call sites to use `await`.
- [X] T002 Convert `_process_callout()` from sync to `async def` in `plugins/ingest_space/space_reader.py`. Add `graphql_client` and `stats` parameters to the function signature. Update call site in `_process_space()` to use `await`.
- [X] T003 Update `read_space_tree()` in `plugins/ingest_space/space_reader.py` to accept `graphql_client` as a parameter (already async). Initialize `stats` dict and pass both through to `_process_space()`.

**Checkpoint**: Space reader traversal is fully async. Existing behavior unchanged -- posts and whiteboards still processed synchronously within the async functions.

---

## Phase 2: US1 -- Fetch and Extract Linked Documents (Priority: P1) MVP

**Purpose**: Enable authenticated HTTP fetching and multi-format text extraction for link contributions.

- [X] T004 [P] [US1] Implement `fetch_url()` method on `GraphQLClient` in `plugins/ingest_space/graphql_client.py`. Method accepts a URL and optional `max_bytes` parameter (default 10 MB). Uses `httpx.AsyncClient` with 60s timeout, follows redirects, sends Bearer token in Authorization header. Returns `tuple[bytes, str] | None` -- body and content-type on success, `None` on any failure. Never raises.
- [X] T005 [P] [US1] Create `plugins/ingest_space/link_extractor.py` module. Implement `extract_text(body: bytes, content_type: str) -> str | None` as the public entry point. Implement `_detect_kind()` with MIME token matching dict (`_MIME_KIND`) and magic byte signature list (`_MAGIC`), including `docx_or_xlsx` fallback for ZIP magic.
- [X] T006 [P] [US1] Implement `_extract_pdf()` in `plugins/ingest_space/link_extractor.py` using lazy `from pypdf import PdfReader`. Read pages from `io.BytesIO(body)`, extract text per page with per-page exception handling, join with double newlines.
- [X] T007 [P] [US1] Implement `_extract_docx()` in `plugins/ingest_space/link_extractor.py` using lazy `from docx import Document as DocxDocument`. Extract paragraph text and table cell content (pipe-delimited rows) from `io.BytesIO(body)`.
- [X] T008 [P] [US1] Implement `_extract_xlsx()` in `plugins/ingest_space/link_extractor.py` using lazy `from openpyxl import load_workbook`. Open workbook in `read_only=True, data_only=True` mode from `io.BytesIO(body)`. Extract sheet titles as markdown headers and cell values as pipe-delimited rows. Close workbook after extraction.
- [X] T009 [P] [US1] Implement `_extract_html()` in `plugins/ingest_space/link_extractor.py` using lazy `from bs4 import BeautifulSoup`. Remove script/style/noscript tags via `tag.decompose()`, extract visible text with newline separator. Fall back to raw UTF-8 decode if beautifulsoup4 is not installed.
- [X] T010 [P] [US1] Implement `_normalise()` in `plugins/ingest_space/link_extractor.py`. Collapse horizontal whitespace (tabs and spaces) to single space. Reduce three or more consecutive newlines to two. Strip leading/trailing whitespace.
- [X] T011 [US1] Integrate fetch and extract into link contribution handling in `_process_callout()` in `plugins/ingest_space/space_reader.py`. For each link contribution with a URI: call `await graphql_client.fetch_url(uri)`, then `extract_text(body, content_type)`. When text is extracted, compose content as title heading + description + body. When extraction fails, compose content as callout context + title + description + URL.

**Checkpoint**: Link contributions with supported document formats produce `Document` objects containing the full extracted text. The standard pipeline (chunk/hash/embed/store) processes them like any other document.

---

## Phase 3: US2 -- URI Rewriting (Priority: P2)

**Purpose**: Enable document fetching on non-production deployments using seed data with production-shaped URIs.

- [X] T012 [US2] Cache the scheme and netloc from the GraphQL endpoint URL in `GraphQLClient.__init__()` in `plugins/ingest_space/graphql_client.py`. Store as `_base_scheme` and `_base_netloc`.
- [X] T013 [US2] Implement `_rewrite_alkemio_uri()` method on `GraphQLClient` in `plugins/ingest_space/graphql_client.py`. Accept a URL, parse with `urlsplit()`, check if path starts with `/api/` or `/rest/`. If matched, reconstruct URL with the deployment's scheme and netloc, preserving path/query/fragment. Return unchanged URL for external hosts or empty input.
- [X] T014 [US2] Call `_rewrite_alkemio_uri()` on the target URL inside `fetch_url()` before the HTTP request in `plugins/ingest_space/graphql_client.py`.

**Checkpoint**: Internal Alkemio storage URIs are transparently redirected to the correct deployment host. External URLs pass through unmodified.

---

## Phase 4: US3 -- Graceful Degradation and Stats (Priority: P3)

**Purpose**: Ensure no single link failure disrupts ingestion and provide operator visibility.

- [X] T015 [P] [US3] Add authentication attempt with exception handling at the start of `fetch_url()` in `plugins/ingest_space/graphql_client.py`. If no session token exists, call `self.authenticate()` in a try/except; log warning and return `None` on failure.
- [X] T016 [P] [US3] Add response body size check in `fetch_url()` in `plugins/ingest_space/graphql_client.py`. After reading `resp.content`, if `len(body) > max_bytes`, log the size and URL and return `None`.
- [X] T017 [P] [US3] Wrap the entire fetch logic in `fetch_url()` in a try/except that catches all exceptions, logs a warning with the URL and error, and returns `None`.
- [X] T018 [US3] Add fetch stats tracking in `_process_callout()` in `plugins/ingest_space/space_reader.py`. Increment `stats["fetched"]` when text extraction succeeds, `stats["skipped"]` when `fetch_url()` or `extract_text()` returns `None`.
- [X] T019 [US3] Add summary log line at the end of `read_space_tree()` in `plugins/ingest_space/space_reader.py` reporting total documents emitted, link bodies fetched, and link bodies skipped.

**Checkpoint**: Ingestion completes successfully regardless of individual link fetch/extraction failures. Operators can see fetch success rates in the logs.

---

## Phase 5: Polish

**Purpose**: Final cleanup and validation.

- [X] T020 Verify `pypdf`, `python-docx`, `openpyxl`, and `beautifulsoup4` are declared in `pyproject.toml` as project dependencies.
- [X] T021 Add module docstrings to `plugins/ingest_space/link_extractor.py` explaining the allowlist approach and the relationship between format detection, extraction, and normalization.
- [X] T022 Verify the extraction fallback path in `extract_text()` handles the `docx_or_xlsx` kind correctly -- tries DOCX extraction first, catches exceptions, then tries XLSX.

**Checkpoint**: Feature complete. All link contributions in space ingestion are processed with full document text extraction where possible, with graceful fallback to metadata-only indexing.
