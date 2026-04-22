# Research: Link Document Extraction

**Feature**: 026-link-document-extraction | **Date**: 2026-04-22

## R1: Allowlist vs Blocklist for Supported Formats

**Decision**: Use an explicit allowlist of supported MIME types and magic byte signatures. Unsupported formats return `None` from `extract_text()`.

**Rationale**: The purpose of text extraction is to feed meaningful content to the chunker and embedder. Binary formats (ZIP archives, images, video, executables) produce no useful text and would either fail noisily or produce garbage. An allowlist ensures only formats where extraction produces genuine searchable text are processed. This is strictly safer than a blocklist, which would need to anticipate every possible binary format.

**Supported formats (allowlist)**:
- PDF (`application/pdf`, `%PDF` magic)
- DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- XLSX (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`)
- HTML (`text/html`, `text/xml`, `<!DOC`/`<html`/`<?xml` magic)
- Plain text (`text/plain`, `text/csv`, `text/markdown`, `application/json`)

**Alternatives considered**:
- *Blocklist approach*: Reject known binary types, attempt extraction on everything else. Rejected -- too many binary formats to anticipate; a missed entry produces garbage chunks.
- *Universal extraction via Apache Tika*: Would support more formats but adds a Java dependency and a separate service. Rejected -- the five supported format families cover the vast majority of linked documents in Alkemio spaces.

---

## R2: MIME Type + Magic Byte Sniffing for Format Detection

**Decision**: Two-tier detection -- first match against known MIME type tokens in the Content-Type header, then fall back to magic byte signature sniffing when the header is absent or unrecognized.

**Rationale**: HTTP servers do not always set accurate Content-Type headers. Some return `application/octet-stream` for PDFs or omit the header entirely. Magic byte sniffing provides a reliable fallback that examines the first 8 bytes of the response body.

**MIME token matching** uses substring containment (`token in content_type`) to handle Content-Type values with parameters (e.g., `application/pdf; charset=binary`).

**Magic signatures**:
- `%PDF` (4 bytes) -- PDF
- `<!DOC` (5 bytes) -- HTML doctype
- `<html` (5 bytes) -- HTML
- `<?xml` (5 bytes) -- XML/HTML
- `PK\x03\x04` (4 bytes) -- ZIP container (DOCX or XLSX)

**ZIP ambiguity handling**: Both DOCX and XLSX are ZIP-based Office Open XML formats sharing the same `PK` magic prefix. The system returns `docx_or_xlsx` and tries DOCX extraction first; if it raises (wrong internal structure), falls back to XLSX extraction.

**Alternatives considered**:
- *python-magic (libmagic bindings)*: Accurate MIME detection but adds a C library dependency. Rejected -- the limited set of target formats makes full libmagic unnecessary.
- *File extension parsing from URL*: URLs may not have extensions, or extensions may be misleading. Rejected as unreliable.

---

## R3: URI Rewriting at Fetch Time

**Decision**: Rewrite known Alkemio internal URIs (paths starting with `/api/` or `/rest/`) to use the scheme and host of the configured GraphQL endpoint. The rewriting happens inside `fetch_url()` immediately before the HTTP request.

**Rationale**: Seed data and cross-environment syncs carry URIs shaped for the production deployment (e.g., `https://alkem.io/api/private/rest/storage/document/<id>`). On dev/staging installations, the Alkemio API lives at a different host. The GraphQL endpoint URL is already configured and known -- its scheme and netloc provide the correct target for internal API calls.

**Rewriting scope**: Only URIs whose path starts with `/api/` or `/rest/` are rewritten. External URLs (e.g., `https://example.com/report.pdf`) are left untouched. This is intentionally conservative -- only paths that structurally match Alkemio internal API patterns are redirected.

**Alternatives considered**:
- *Rewrite at ingest event time*: Would require modifying the GraphQL query results or the event payload before space tree processing. Rejected -- more invasive and requires knowledge of URI patterns in a different layer.
- *Configurable rewrite rules*: A general-purpose URL rewriting engine. Rejected -- overengineered for the single known case (Alkemio internal URIs). The simple path-prefix check is sufficient and easy to extend if new patterns emerge.
- *No rewriting (require correct URIs)*: Would require all seed data to be pre-processed with correct deployment URLs. Rejected -- impractical for developers and testers.

---

## R4: Error Tolerance in fetch_url()

**Decision**: `fetch_url()` never raises an exception. All errors (network failures, HTTP errors, oversized responses, authentication failures) are caught, logged, and result in a `None` return value.

**Rationale**: The space tree may contain dozens of link contributions. A single fetch failure (server down, timeout, auth issue) must not prevent the remaining links from being processed. The caller (`_process_callout` in `space_reader.py`) checks for `None` and falls back to metadata-only indexing.

**Error handling strategy**:
1. If no session token exists, attempt authentication. If auth fails, return `None`.
2. Rewrite the URI (R3) and issue an async HTTP GET with a 60-second timeout.
3. If the response status is not 200, log and return `None`.
4. If the response body exceeds the size cap (10 MB), log and return `None`.
5. If any exception occurs during the request, log and return `None`.

**Alternatives considered**:
- *Raise exceptions and let the caller handle*: Would require try/except in every call site and risk accidental pipeline failure if a caller forgets. Rejected -- centralizing error handling in `fetch_url()` is safer.
- *Return a Result/Either type*: More expressive but adds complexity for a simple success/failure distinction. Rejected -- `None` vs `tuple[bytes, str]` is sufficient.

---

## R5: Lazy Imports for Extraction Libraries

**Decision**: Import `pypdf`, `docx` (python-docx), `openpyxl`, and `bs4` (beautifulsoup4) inside the extraction functions rather than at module level.

**Rationale**: The `link_extractor` module is imported by `space_reader.py` which is imported by the plugin. If these libraries were imported at module level, they would be loaded at process startup even for deployments that only use the `expert` or `generic` plugins. Lazy imports defer the cost until actual extraction is needed.

**Trade-off**: Slightly slower first extraction call (library initialization). Acceptable because extraction is I/O-bound (HTTP fetch dominates latency) and the import cost is one-time per process lifetime.

**Alternatives considered**:
- *Top-level imports with try/except ImportError*: Would fail at import time if a library is missing, making it harder to diagnose. The current approach with lazy imports defers the error to the point of use and produces a clearer error message.
- *Separate optional dependency group*: Would require conditional installation. Rejected -- these libraries are always needed for space ingestion and are declared as regular dependencies.

---

## R6: 10 MB Size Cap

**Decision**: Enforce a hard limit of 10 MB on response body size. Responses exceeding this limit are discarded and logged.

**Rationale**: The extraction pipeline processes document text in memory (BytesIO for pypdf, docx, openpyxl). Very large files could cause excessive memory consumption, especially when multiple link contributions are fetched concurrently within a single space tree traversal. 10 MB is generous enough to cover typical business documents (multi-hundred-page PDFs, large spreadsheets) while protecting against pathological cases (multi-GB data dumps linked by mistake).

**Implementation note**: The check is performed after the full response is read (`resp.content`), not via streaming. This is acceptable because httpx buffers the response in memory by default and the 60-second timeout provides an implicit ceiling on how much data can be received.

**Alternatives considered**:
- *Streaming with byte counting*: Would allow aborting the download before the full body is received. More efficient for very large files but adds complexity. Rejected for simplicity -- the 60s timeout provides a practical upper bound.
- *Configurable size cap via environment variable*: Would allow operators to tune the limit. Rejected for now -- 10 MB is a sensible default and no use case for customization has been identified. Easy to add later if needed.
