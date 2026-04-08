# Spec: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Epic:** alkem-io/alkemio#1820
**Date:** 2026-04-08
**Status:** Draft

---

## 1. User Value

Enable the virtual-contributor service to accept enriched website ingestion requests that specify per-source crawl parameters (pageLimit, maxDepth, includePatterns, excludePatterns), support multi-source ingestion in a single request, distinguish between FULL and INCREMENTAL ingestion modes, and remember source configurations for future refresh operations. This replaces the current single-URL, hardcoded-limit crawl behavior with a flexible, configurable pipeline.

## 2. Scope

### In Scope (VC service side only)

1. **Extended IngestWebsite event schema** -- accept new fields from the enriched RabbitMQ message:
   - `sources`: list of `WebsiteSource` objects (each with url, pageLimit, maxDepth, includePatterns, excludePatterns)
   - `mode`: FULL or INCREMENTAL (default INCREMENTAL)
   - Backward compatibility with the existing `baseUrl` single-URL format

2. **Crawler enhancements** -- respect per-source parameters:
   - `maxDepth`: limit link-follow depth from the base URL (0 = base page only, -1 = unlimited)
   - `includePatterns`: only crawl URLs matching these glob patterns
   - `excludePatterns`: skip URLs matching these glob patterns
   - `pageLimit`: per-source page limit (already exists, needs to be per-source)

3. **FULL vs INCREMENTAL mode** -- FULL mode wipes the collection before ingesting; INCREMENTAL (default) uses existing change-detection/dedup pipeline

4. **Source config persistence** -- store the source configuration in ChromaDB collection metadata so that refresh requests can re-use the last-ingested source config

5. **Progress model definition** -- define IngestWebsiteProgress event model for future progress reporting (actual emission deferred: requires main.py message handler changes to pass transport port to plugin handle)

6. **Multi-source handling** -- process multiple sources in a single ingestion request, aggregating results

### Out of Scope

- Server-side (alkemio/server) GraphQL mutation, DTOs, authorization
- Authenticated crawling (cookies, API keys)
- Crawl type selection (SITEMAP, SINGLE_PAGE, CRAWL)
- Per-source chunk sizing (managed by VC service env vars)
- Storing website sources in the platform DB
- Job status query endpoint (platform server responsibility)

## 3. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC1 | IngestWebsite event model accepts `sources` array with per-source `url`, `pageLimit`, `maxDepth`, `includePatterns`, `excludePatterns` | Unit test: deserialize enriched JSON payload |
| AC2 | IngestWebsite event model accepts `mode` field (FULL/INCREMENTAL) | Unit test: deserialize with mode field |
| AC3 | Backward compatible: existing `baseUrl`-only payloads still parse correctly | Unit test: deserialize legacy payload |
| AC4 | Crawler respects `maxDepth` parameter, limiting link-follow depth | Unit test: verify depth-limited crawl |
| AC5 | Crawler respects `includePatterns` glob filtering | Unit test: only matching URLs are crawled |
| AC6 | Crawler respects `excludePatterns` glob filtering | Unit test: matching URLs are skipped |
| AC7 | FULL mode deletes existing collection before ingesting | Unit test: verify delete_collection is called |
| AC8 | INCREMENTAL mode uses change-detection pipeline without wiping | Unit test: verify no delete_collection call |
| AC9 | Multiple sources in a single request are each crawled and aggregated | Unit test: multi-source ingestion |
| AC10 | Source config is stored in KnowledgeStorePort collection metadata | Unit test: verify metadata persistence |
| AC11 | IngestWebsiteProgress model is defined with sourceUrl, status, pagesCrawled, chunksProcessed fields | Unit test: model serialization |
| AC12 | Per-source pageLimit defaults to 20, maxDepth to -1 (unlimited) | Unit test: verify defaults |

## 4. Constraints

- Python 3.12, async throughout
- Must not break existing `ingest-website` plugin contract or RabbitMQ message format
- ChromaDB collection metadata is the storage mechanism for source configs (no new DB)
- All new code must pass ruff, pyright, and pytest
- Convention: `-1` means unlimited for pageLimit and maxDepth
