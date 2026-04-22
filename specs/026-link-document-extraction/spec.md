# Feature Specification: Link Document Extraction

**Feature Branch**: `026-link-document-extraction`
**Created**: 2026-04-22
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fetch and Extract Text from Linked Documents (Priority: P1)

As a virtual contributor user searching for information that lives inside linked documents (PDFs, Word files, spreadsheets, HTML pages), I want the space ingest pipeline to fetch those linked files and extract their full text content, so that the actual document body becomes searchable through the knowledge base rather than only the link URL and title being indexed.

**Why this priority**: Without document body extraction, link contributions store only a URL string and a short description. Users asking questions whose answers live inside a linked PDF or DOCX get no relevant retrieval results, making the virtual contributor unable to leverage a significant category of contributed knowledge.

**Independent Test**: Ingest a space that contains a callout with a link contribution pointing to a PDF document. After ingestion, query the knowledge store and verify that chunks contain the extracted text from the PDF body, not just the URL.

**Acceptance Scenarios**:

1. **Given** a space with a link contribution pointing to a PDF, **When** the space is ingested, **Then** the knowledge store contains chunks with the extracted text from the PDF body, and the document title appears as a heading in the content.
2. **Given** a space with a link contribution pointing to a DOCX file, **When** the space is ingested, **Then** the extracted text includes both paragraph content and table cell content from the Word document.
3. **Given** a space with a link contribution pointing to an XLSX spreadsheet, **When** the space is ingested, **Then** the extracted text includes sheet titles and cell values formatted as pipe-delimited rows.
4. **Given** a space with a link contribution pointing to an HTML page, **When** the space is ingested, **Then** the extracted text is the visible text content with script/style blocks removed.
5. **Given** a space with a link contribution pointing to a plain text or CSV file, **When** the space is ingested, **Then** the raw text content is decoded and stored as the document body.

---

### User Story 2 - URI Rewriting for Cross-Deployment Compatibility (Priority: P2)

As a platform operator deploying seed data that carries production-shaped Alkemio URIs (e.g., `https://alkem.io/api/private/rest/storage/document/<id>`) onto a dev or staging installation, I want the system to automatically redirect known Alkemio internal API URIs to the configured deployment host, so that document fetching works regardless of which environment the link metadata was created in.

**Why this priority**: Seed data frequently contains production URIs that are unreachable from non-production environments. Without URI rewriting, all such document fetches fail silently and fall back to metadata-only indexing, defeating the purpose of document extraction for development and testing workflows.

**Independent Test**: Configure a deployment with a GraphQL endpoint at `https://dev.alkem.io/api/private/graphql`. Ingest a space whose link contribution has URI `https://alkem.io/api/private/rest/storage/document/abc-123`. Verify the fetch request targets `https://dev.alkem.io/api/private/rest/storage/document/abc-123`.

**Acceptance Scenarios**:

1. **Given** a link URI with path starting with `/api/`, **When** `fetch_url()` is called, **Then** the URI scheme and host are rewritten to match the configured GraphQL endpoint before the HTTP request is made.
2. **Given** a link URI with path starting with `/rest/`, **When** `fetch_url()` is called, **Then** the URI is similarly rewritten to the deployment host.
3. **Given** a link URI pointing to an external host (e.g., `https://example.com/report.pdf`), **When** `fetch_url()` is called, **Then** the URI is not rewritten and the request goes to the original host.
4. **Given** an empty or null URI, **When** the rewriting function is called, **Then** it returns the input unchanged without error.

---

### User Story 3 - Graceful Degradation on Fetch or Extraction Failure (Priority: P3)

As a platform operator, I want the ingest pipeline to never fail or halt when a linked document cannot be fetched or its content cannot be extracted, so that all other documents in the space continue to be ingested and the link contribution is still indexed with its available metadata (title, description, URL).

**Why this priority**: External URLs are inherently unreliable -- servers may be down, authentication may fail, documents may be corrupted or in unsupported formats. A single bad link must not disrupt the ingestion of an entire space tree containing dozens of other documents.

**Independent Test**: Ingest a space containing two link contributions -- one pointing to a valid PDF and one pointing to a non-existent URL. Verify that the valid PDF is extracted and indexed with full text, the broken link is indexed with its metadata (callout context + URL), and the overall ingestion succeeds.

**Acceptance Scenarios**:

1. **Given** a link URI that returns a non-200 HTTP status, **When** `fetch_url()` is called, **Then** it returns `None` without raising an exception, and the link is indexed with callout context and URL metadata.
2. **Given** a link URI whose response body exceeds the 10 MB size cap, **When** `fetch_url()` is called, **Then** it returns `None` and logs the skip, and the link is indexed with metadata only.
3. **Given** a link pointing to a binary file in an unsupported format (e.g., ZIP archive, video), **When** text extraction is attempted, **Then** `extract_text()` returns `None` and the link is indexed with metadata only.
4. **Given** a valid PDF that is internally corrupted or password-protected, **When** text extraction is attempted, **Then** the extraction failure is logged and `extract_text()` returns `None`, with fallback to metadata indexing.
5. **Given** authentication has not been established before a fetch, **When** `fetch_url()` is called, **Then** it attempts to authenticate first, and if authentication fails, returns `None` without raising.
6. **Given** a network timeout or connection error during fetch, **When** the exception is caught, **Then** `fetch_url()` returns `None` and logs the error.

---

## Edge Cases

| Edge Case | Expected Behavior |
|---|---|
| Unsupported binary format (ZIP, video, image) | `extract_text()` returns `None`; link indexed with metadata only |
| Response body exceeds 10 MB | `fetch_url()` returns `None` after reading; logged as "body too large" |
| Authentication failure before fetch | `fetch_url()` attempts auth, logs warning, returns `None` |
| HTTP timeout (60s limit) | Exception caught; `fetch_url()` returns `None` |
| Malformed or password-protected PDF | `pypdf` raises; exception caught in `extract_text()`, returns `None` |
| DOCX file that is actually an XLSX (ZIP magic overlap) | `_detect_kind()` returns `docx_or_xlsx`; tries DOCX first, falls back to XLSX extraction |
| Empty response body (0 bytes) | `extract_text()` returns `None` on empty input |
| Server returns no Content-Type header | Magic byte sniffing detects PDF/HTML/ZIP; unrecognized formats return `None` |
| External URL (not Alkemio internal) | URI rewriting is skipped; fetch goes to original host |
| Link contribution with no URI but has title/description | No fetch attempted; indexed with available metadata |

---

## Requirements

### Functional Requirements

- **FR-001**: The system shall fetch linked document bodies via authenticated HTTP GET requests using the session token from Kratos authentication.
- **FR-002**: The system shall rewrite link URIs whose path begins with `/api/` or `/rest/` to use the scheme and host of the configured GraphQL endpoint, preserving the original path, query, and fragment.
- **FR-003**: The system shall detect document format using a two-tier approach: first by matching MIME type tokens from the Content-Type header, then by magic byte signature sniffing when the header is absent or unrecognized.
- **FR-004**: The system shall extract plain text from PDF files using page-by-page text extraction.
- **FR-005**: The system shall extract plain text from DOCX files, including paragraph text and table cell content formatted as pipe-delimited rows.
- **FR-006**: The system shall extract plain text from XLSX files, including sheet titles and cell values formatted as pipe-delimited rows.
- **FR-007**: The system shall extract visible text from HTML content, removing script, style, and noscript elements.
- **FR-008**: The system shall decode plain text, CSV, markdown, and JSON files as UTF-8 text.
- **FR-009**: The system shall enforce a maximum response body size of 10 MB; responses exceeding this limit shall be discarded.
- **FR-010**: The `fetch_url()` method shall never raise an exception; all errors shall be caught, logged, and result in a `None` return value.
- **FR-011**: When document text is successfully extracted, the link contribution content shall consist of the document title (as a heading), the link description, and the extracted text body.
- **FR-012**: When document text extraction fails or is not attempted, the link contribution content shall consist of the callout context, the link title, the link description, and the URL.
- **FR-013**: The system shall normalize extracted text by collapsing horizontal whitespace and reducing excessive blank lines to at most two consecutive newlines.
- **FR-014**: The system shall track and log fetch statistics (successful extractions and skipped links) per space tree ingestion.
- **FR-015**: The `_process_space()` and `_process_callout()` functions shall be async to support non-blocking HTTP fetch operations within the space tree traversal.

---

## Success Criteria

- **SC-001**: Link contributions pointing to PDF, DOCX, XLSX, HTML, or plain text files produce knowledge store chunks containing the actual document text, making that content retrievable by the virtual contributor.
- **SC-002**: Link contributions pointing to unreachable URLs, unsupported formats, or oversized files are still indexed with their available metadata (title, description, URL) and do not cause ingestion failures.
- **SC-003**: URI rewriting enables document fetching on non-production deployments using seed data with production-shaped URIs.
- **SC-004**: Fetch statistics are logged at the end of each space tree ingestion, providing operators with visibility into extraction success rates.
- **SC-005**: The overall space ingestion pipeline never fails due to a single link fetch or extraction error.

---

## Assumptions

- The deployment environment has outbound network access to reach linked document URLs (both Alkemio internal storage and external hosts).
- The `pypdf`, `python-docx`, `openpyxl`, and `beautifulsoup4` libraries are declared as project dependencies and available at runtime.
- Kratos session tokens are valid for authenticating against Alkemio internal storage endpoints.
- The 60-second HTTP timeout and 10 MB size cap are appropriate defaults for the expected document sizes in Alkemio spaces.
- The existing chunking, hashing, and embedding pipeline steps handle the extracted text without modification -- extracted document bodies are standard text content.
