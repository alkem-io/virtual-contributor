# Quickstart: Website Content Quality Improvements

**Feature Branch**: `story/021-website-content-quality`
**Date**: 2026-04-15

## What This Feature Does

Improves the quality of content extracted from crawled websites through three changes:

1. **HTML boilerplate filtering** -- removes cookie banners, consent dialogs, newsletter popups, and other boilerplate elements by stripping additional HTML tags (`aside`, `form`, `dialog`, `noscript`) and removing elements whose class/ID matches common boilerplate naming patterns.
2. **Cross-page paragraph dedup** -- after extracting text from all pages, removes paragraphs that appear on more than 50% of pages (boilerplate that survived HTML filtering). Only activates with 4+ pages.
3. **Post-redirect URL tracking** -- stores the final URL after HTTP redirects instead of the pre-redirect URL, so source citations in RAG answers point to the correct page location.

No new configuration is required. All changes take effect automatically on the next website ingestion.

## Quick Verification

### 1. Verify boilerplate removal from HTML

Ingest a website known to have cookie consent banners:

```bash
export PLUGIN_TYPE=ingest-website
poetry run python main.py
```

Send an ingest request for a website with visible cookie/consent UI. After ingestion, query the knowledge store and confirm no chunks contain cookie/consent/GDPR text.

### 2. Verify cross-page dedup

Ingest a website with 5+ pages. Check that boilerplate paragraphs appearing on most pages (e.g., footer text, repeated CTAs) are not present in the stored chunks. Unique page content should be preserved.

### 3. Verify redirect URL tracking

Ingest a website where pages redirect (e.g., `/docs` redirects to `/docs/en-US`). Check that the stored document URLs reflect the final destination, not the pre-redirect URL.

### 4. Run tests

```bash
# Run all ingest-website tests
poetry run pytest tests/plugins/test_ingest_website.py -v

# Run with coverage for the changed module
poetry run pytest tests/plugins/test_ingest_website.py --cov=plugins/ingest_website --cov-report=term-missing
```

## Files Changed

| File | Change |
|------|--------|
| `plugins/ingest_website/html_parser.py` | Extended `_STRIP_TAGS` (added `aside`, `form`, `dialog`, `noscript`). Added `_BOILERPLATE_RE` regex and `_has_boilerplate_attr()` to detect boilerplate elements by class/ID. `extract_text()` now removes boilerplate elements before semantic extraction. Added `remove_cross_page_boilerplate()` for paragraph-level frequency dedup |
| `plugins/ingest_website/crawler.py` | Changed URL recording from pre-redirect `normalized` to post-redirect `_normalize_url(str(response.url))` |
| `plugins/ingest_website/plugin.py` | Imported `remove_cross_page_boilerplate`. After text extraction, runs cross-page dedup on documents with 4+ pages. Filters out documents that became empty after cleanup |

## Contracts

No external interface changes:

- **LLMPort**: Unchanged
- **EmbeddingsPort**: Unchanged
- **KnowledgeStorePort**: Unchanged
- **PluginContract**: Unchanged (no new lifecycle methods)
- **Event schemas**: Unchanged
- **IngestEngine / PipelineStep**: Unchanged
- **BaseConfig**: Unchanged
