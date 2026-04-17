# Data Model: Website Content Quality Improvements

**Feature Branch**: `story/021-website-content-quality`
**Date**: 2026-04-15

## Overview

This feature does not introduce any data model changes. No new database tables, event schemas, domain entities, or configuration fields are added. All changes are in content processing logic within the `plugins/ingest_website/` module.

## What Changed (and Why No Data Model Impact)

### HTML Parser (`html_parser.py`)

New module-level constants and functions were added, but these are internal implementation details, not data model entities:

- **`_STRIP_TAGS`**: Extended from 5 to 9 tags. This is a static list used during HTML parsing, not a configurable or stored value.
- **`_BOILERPLATE_RE`**: Compiled regex pattern. Internal to the parser.
- **`_has_boilerplate_attr()`**: Internal helper function.
- **`remove_cross_page_boilerplate()`**: Pure function that takes a list of strings and returns a filtered list of strings. No new data structures.

### Crawler (`crawler.py`)

The `url` field in the returned `{"url": str, "html": str}` dict now contains the post-redirect URL instead of the pre-redirect URL. The dict structure is unchanged -- only the value source changed (from `normalized` to `_normalize_url(str(response.url))`).

### Plugin (`plugin.py`)

The plugin wires the new `remove_cross_page_boilerplate()` function between text extraction and pipeline execution. The `Document` and `DocumentMetadata` models are used exactly as before. Empty documents are filtered out with a list comprehension -- no new model fields or types.

## Existing Entities (unchanged)

| Entity | File | Status |
|--------|------|--------|
| `Document` | `core/domain/ingest_pipeline.py` | Unchanged |
| `DocumentMetadata` | `core/domain/ingest_pipeline.py` | Unchanged |
| `IngestWebsite` | `core/events/ingest_website.py` | Unchanged |
| `IngestWebsiteResult` | `core/events/ingest_website.py` | Unchanged |
| `BaseConfig` | `core/config.py` | Unchanged |
| Pipeline steps | `core/domain/pipeline/steps.py` | Unchanged |
| Port interfaces | `core/ports/` | Unchanged |

## Conclusion

All changes are in pre-pipeline content processing. Data flows through the same `Document` -> `Chunk` -> embedding -> storage path as before, with cleaner content entering the pipeline.
