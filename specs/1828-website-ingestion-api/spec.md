# Spec: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Date:** 2026-04-08
**Status:** Draft

## User Value

Website ingestion today is hardcoded to three static URLs for the GUIDANCE engine only.
This change makes website ingestion configurable, accepting per-source crawl parameters
(pageLimit, maxDepth, includePatterns, excludePatterns) and an ingestion mode
(FULL vs INCREMENTAL) through the RabbitMQ event schema. This enables the server to
publish enriched ingestion requests without the VC service needing hardcoded knowledge
of any URL or crawl strategy.

## Scope (VC Service Side Only)

1. **Extend `IngestWebsite` event schema** -- add `sources` list with per-source fields:
   `url`, `pageLimit`, `maxDepth`, `includePatterns`, `excludePatterns`. Add `mode`
   (FULL / INCREMENTAL). Maintain backward compatibility with existing `baseUrl` field.

2. **Crawler enhancements** -- respect `maxDepth` (link depth from base URL) and
   `includePatterns` / `excludePatterns` (glob-based URL filtering) in the crawl loop.

3. **Multi-source support** -- handle multiple website sources in a single ingestion event,
   crawling each source and merging documents before running the ingest pipeline.

4. **Ingestion mode** -- FULL mode wipes the collection before ingesting; INCREMENTAL (default)
   uses the existing change-detection and orphan-cleanup pipeline.

5. **Source config metadata** -- store the source configuration in collection metadata
   so that future refresh operations can re-use the same crawl parameters.

6. **Result reporting** -- extend `IngestWebsiteResult` with per-source status and page counts
   for job progress tracking.

## Out of Scope

- Server-side GraphQL mutation, DTOs, or resolver changes (alkemio/server repo)
- Authenticated crawling (cookies, API keys)
- Crawl type selection (SITEMAP, SINGLE_PAGE, CRAWL)
- Per-source chunk sizing (managed by VC service env vars)
- Storing website sources in the platform DB
- UI changes

## Acceptance Criteria

1. `IngestWebsite` event accepts a `sources` array with `url`, `pageLimit`, `maxDepth`,
   `includePatterns`, `excludePatterns` per source.
2. `IngestWebsite` event accepts a `mode` field (`FULL` | `INCREMENTAL`, default INCREMENTAL).
3. Backward compatibility: events with only `baseUrl` (no `sources`) still work.
4. Crawler respects `maxDepth` -- does not follow links deeper than configured depth.
5. Crawler respects `includePatterns` -- only crawls URLs matching at least one pattern.
6. Crawler respects `excludePatterns` -- skips URLs matching any pattern.
7. FULL mode deletes the collection before ingesting; INCREMENTAL does not.
8. Multiple sources in one event are crawled and their documents merged before pipeline.
9. `IngestWebsiteResult` reports per-source crawl statistics (pages crawled, errors).
10. Source config is stored as collection metadata for refresh support.
11. All new behavior is covered by unit tests.

## Constraints

- Python 3.12, Poetry, existing hexagonal architecture
- Pydantic models with camelCase aliases for wire compatibility
- Must not break existing ingest-website or ingest-space plugins
- Crawler must preserve existing SSRF protections and domain boundary enforcement
- Must pass existing test suite, ruff, pyright

## Clarifications (Iteration 1)

### C1: How does backward compatibility work when `sources` is absent?
**Question:** When the server sends the old format with `baseUrl` and no `sources`, how should the VC service handle it?
**Answer:** Use a Pydantic `model_validator` to synthesize a single `WebsiteSource` from the legacy `baseUrl` field when `sources` is empty/absent. The `baseUrl` field remains optional for backward compat.
**Rationale:** This keeps the event model self-normalizing. Plugin code only needs to work with `sources`.

### C2: What is the collection naming strategy for multi-source events?
**Question:** Currently collection name is derived from `netloc` of `base_url`. With multiple sources from different domains, what name is used?
**Answer:** Use the `personaId` from the event as the collection name prefix: `{personaId}-knowledge`. This decouples collection naming from URLs and supports multi-domain ingestion.
**Rationale:** `personaId` is the stable identifier for the VC's knowledge base. Using netloc would create separate collections per source domain, fragmenting the knowledge base.

### C3: How should `maxDepth` be defined -- link hops or URL path depth?
**Question:** "Max link depth from base URL" -- does depth 0 mean only the base page, depth 1 means pages directly linked from base, etc.?
**Answer:** Yes. Depth is measured in link hops from the base URL. Depth 0 = base page only. Depth 1 = base page + pages linked from it. -1 = unlimited (current behavior).
**Rationale:** Link-hop depth is the standard crawler semantics and matches the GraphQL schema description.

### C4: What glob syntax should `includePatterns` / `excludePatterns` use?
**Question:** The story says "glob patterns" -- which library or syntax?
**Answer:** Use Python's `fnmatch.fnmatch` on the URL path component. Patterns like `/docs/*` match URL paths. This is simple, stdlib-based, and matches the examples in the story.
**Rationale:** `fnmatch` is stdlib, well-understood, and sufficient for the documented use cases (`/docs/*`, `/admin/*`, `*.pdf`).

### C5: What happens when both `includePatterns` and `excludePatterns` match a URL?
**Question:** Precedence when both include and exclude patterns match the same URL.
**Answer:** Exclude takes precedence over include. A URL matching any exclude pattern is skipped regardless of include patterns.
**Rationale:** This is the safer default -- explicit exclusions should always win to prevent accidental crawling of restricted paths.

### C6: How should source config be stored in collection metadata?
**Question:** ChromaDB collections have metadata. What format?
**Answer:** Store as JSON-serialized string under key `source_config` in the collection metadata. The KnowledgeStorePort does not currently expose collection-level metadata APIs, so store it as chunk-level metadata on a synthetic `__config__` document instead.
**Answer (revised):** Actually, since ChromaDB collection metadata is limited and the KnowledgeStorePort has no `set_collection_metadata` method, store the source config as metadata on a sentinel chunk with id `__source_config__` in the collection. This keeps it within the existing port interface.
**Rationale:** Avoids extending the KnowledgeStorePort protocol, which would be a cross-cutting change beyond this story's scope.

### C7: Should multi-source crawling run sequentially or in parallel?
**Question:** Multiple sources in one event -- sequential or concurrent crawling?
**Answer:** Sequential. Crawling is I/O-heavy and already async. Running multiple crawls concurrently within one event risks overwhelming the target servers and complicating error handling. Sequential is simpler and safer.
**Rationale:** Simplicity. The primary use case is 1-3 sources per event. Parallelism can be added later if needed.

### C8: What does `IngestWebsiteResult` per-source reporting look like?
**Question:** What fields should per-source status include?
**Answer:** A list of `SourceResult` objects, each with: `url` (base URL of source), `pagesProcessed` (int), `error` (optional string). The top-level `result` remains SUCCESS/FAILURE based on whether any source had errors.
**Rationale:** Provides enough detail for the server to report job status without over-engineering the schema.

### C9: Does FULL mode affect all sources or per-source?
**Question:** Should FULL mode delete the entire collection once, or per-source?
**Answer:** FULL mode deletes the entire collection once before processing any sources. It is a collection-level operation.
**Rationale:** The collection is the VC's knowledge base. FULL mode means "rebuild from scratch," which requires wiping everything first.

## Clarifications (Iteration 2)

### C10: Should `includePatterns` apply to the base URL itself?
**Question:** If `includePatterns` is set to `["/docs/*"]` and the base URL is `https://example.com`, should the base URL be skipped because it doesn't match?
**Answer:** No. The base URL is always crawled regardless of `includePatterns`. Patterns only apply to discovered links. The base URL is the entry point.
**Rationale:** Skipping the base URL when it doesn't match include patterns would be confusing. The user explicitly provided the base URL.

### C11: How should `pageLimit` interact between event-level config and env-level `PROCESS_PAGES_LIMIT`?
**Question:** The existing `IngestWebsiteConfig.process_pages_limit` sets a default. Per-source `pageLimit` may override it. Which wins?
**Answer:** Per-source `pageLimit` from the event takes precedence. If not provided (None), fall back to the env-level `PROCESS_PAGES_LIMIT` (default 20). The event field default of 20 in the GraphQL schema is enforced on the server side; the VC service treats None as "use env config."
**Rationale:** Event-level config should override env-level defaults. This gives the API caller control while preserving the operator's ability to set system defaults.

No further ambiguities found. Clarify loop complete.
