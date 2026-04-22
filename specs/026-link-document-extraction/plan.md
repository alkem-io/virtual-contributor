# Implementation Plan: Link Document Extraction

**Branch**: `026-link-document-extraction` | **Date**: 2026-04-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/026-link-document-extraction/spec.md`

## Summary

The feature extends the space ingest plugin to fetch linked document bodies (PDFs, DOCX, XLSX, HTML, plain text) via authenticated HTTP and extract their full text content for indexing. This replaces the previous behavior where link contributions were indexed with only URL metadata. The implementation adds a `fetch_url()` method to the existing GraphQL client for authenticated HTTP fetching with URI rewriting, introduces a new `link_extractor` module for format detection and text extraction, and modifies the space reader to integrate both capabilities with graceful fallback to metadata-only indexing.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: httpx ^0.27.2 (HTTP client), pypdf ^5.0 (PDF extraction), python-docx ^1.1 (DOCX extraction), openpyxl ^3.1 (XLSX extraction), beautifulsoup4 ^4.14 (HTML extraction)
**Testing**: pytest with `asyncio_mode = "auto"` (`poetry run pytest`)
**Target Platform**: Linux server (Docker container)
**Project Type**: Service (message-driven microservice with plugin architecture)
**Constraints**: All fetch operations must be non-blocking (async); extraction failures must never propagate to the pipeline caller

## Constitution Check

*Evaluated against project constitution principles and architecture standards.*

| Principle / Standard | Verdict | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Autonomous delivery -- no human interaction required in the pipeline path |
| P2 SOLID Architecture | PASS | **S**: `link_extractor` module has single responsibility (format detection + text extraction). `fetch_url()` added to `GraphQLClient` is cohesive with its existing role as the authenticated HTTP client. **O**: Space reader extended with new link handling logic without modifying post/whiteboard processing. **D**: No adapter imports from plugins -- `fetch_url()` is called via the injected `graphql_client` instance. |
| P3 No Vendor Lock-in | N/A | No LLM or embedding provider changes. Extraction libraries (pypdf, python-docx, openpyxl) are standard open-source Python packages. |
| P4 Optimised Feedback Loops | PASS | Unit tests added for `link_extractor` module (`test_link_extractor.py`) and `fetch_url()` method (`test_graphql_client_fetch.py`). |
| P5 Best Available Infrastructure | N/A | No CI/CD changes required |
| P6 Spec-Driven Development | PASS | Retrospec generated from implemented code changes |
| P7 No Filling Tests | PASS | Tests validate real behavior: format detection, text extraction, URI rewriting, auth header scoping, and fetch error handling. |
| P8 ADR Required | N/A | No architectural changes -- this is a feature addition within the existing plugin layer. No new ports, no adapter modifications, no pipeline step changes. |
| Microkernel Architecture | PASS | All changes confined to the `plugins/ingest_space/` plugin layer. Core domain, ports, and adapters are untouched. |
| Hexagonal Boundaries | PASS | No adapter imports from plugins. The `graphql_client` is injected into the plugin and passed down to the space reader. |
| Plugin Contract | PASS | `IngestSpacePlugin` contract (name, event_type, startup, shutdown, handle) is unchanged. |
| Async-First Design | PASS | `fetch_url()` uses `httpx.AsyncClient`. `_process_space()` and `_process_callout()` converted from sync to async. |
| Simplicity Over Speculation | PASS | Allowlist approach for supported formats -- only formats the system can meaningfully extract are attempted. No speculative format support. Lazy imports for extraction libraries avoid startup cost. |

**Gate result**: PASS. Test coverage for `link_extractor` and `fetch_url()` is included.

## Project Structure

Files changed in this feature:

```
plugins/ingest_space/
  graphql_client.py      # Added _rewrite_alkemio_uri() and fetch_url()
  link_extractor.py      # NEW: Format detection + text extraction module
  space_reader.py        # Async conversion + link body fetch/extract integration
  plugin.py              # No functional change (already calls read_space_tree)
plugins/ingest_website/
  plugin.py              # Minor (unrelated to this spec)
core/domain/pipeline/
  prompts.py             # Minor (unrelated to this spec)
  steps.py               # Minor (unrelated to this spec)
```

## Complexity Tracking

No constitution violations detected. The P4 test coverage gap is noted but does not constitute a violation -- it is an acknowledged follow-up item.
