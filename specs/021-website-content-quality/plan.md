# Implementation Plan: Website Content Quality Improvements

**Branch**: `story/021-website-content-quality` | **Date**: 2026-04-15 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/021-website-content-quality/spec.md`

## Summary

Improve crawled website content quality through two complementary cleanup layers in `html_parser.py`: (1) expanded HTML element stripping with regex-based boilerplate detection by class/ID, and (2) cross-page paragraph frequency analysis that removes text appearing on >50% of pages. Also fix URL tracking in `crawler.py` to use the final URL after HTTP redirects.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: beautifulsoup4 (existing), httpx (existing), re (stdlib)
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service -- ingest-website plugin
**Performance Goals**: N/A (content filtering adds negligible processing time relative to crawl and embedding steps)
**Constraints**: All changes confined to `plugins/ingest_website/`. No port interface changes. No new dependencies.
**Scale/Scope**: 3 files modified, ~80 lines added, ~5 lines changed

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Content filtering logic, no interactive steps |
| P2 | SOLID Architecture | PASS | Changes confined to ingest-website plugin (Single Responsibility). html_parser gains filtering functions without changing its extraction interface (Open/Closed). No port changes (Dependency Inversion) |
| P3 | No Vendor Lock-in | PASS | Uses stdlib `re` and existing BeautifulSoup. No new provider dependencies |
| P4 | Optimised Feedback Loops | PASS | Cleaner content improves RAG retrieval accuracy. Boilerplate removal is deterministic and testable |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts in specs/021-website-content-quality/ |
| P7 | No Filling Tests | PASS | Tests validate actual content filtering behavior with realistic HTML |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | All changes inside single plugin boundary |
| AS:Hexagonal | Hexagonal Boundaries | PASS | No adapter or port changes |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged. No new lifecycle methods |
| AS:Domain | Domain Logic Isolation | PASS | Pipeline engine, step protocol unchanged. Changes are pre-pipeline content processing |
| AS:Simplicity | Simplicity Over Speculation | PASS | Regex covers common boilerplate naming conventions. Cross-page dedup is language-agnostic with simple frequency counting. No ML, no external libraries |
| AS:Async | Async-First Design | PASS | No new sync calls. Cross-page dedup is CPU-bound but fast (string operations on already-extracted text) |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/021-website-content-quality/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
plugins/ingest_website/
├── html_parser.py    # Expanded _STRIP_TAGS, _BOILERPLATE_RE, _has_boilerplate_attr(), remove_cross_page_boilerplate()
├── crawler.py        # Use response.url (final URL after redirects) instead of pre-redirect URL
└── plugin.py         # Wire cross-page dedup after text extraction, filter empty documents
```

## Complexity Tracking

No constitution violations to justify.
