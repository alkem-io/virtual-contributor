# Clarifications: Story #1828 -- Website Ingestion API (VC Service Side)

## Iteration 1

### C1: Backward compatibility shape for legacy `baseUrl` payloads

**Question:** When the server sends the old-format `IngestWebsite` message with just `baseUrl`, should the VC service auto-convert it to a single-element `sources` array?

**Decision:** Yes. The event model will accept both formats: if `sources` is absent but `baseUrl` is present, it will be normalized to a single `WebsiteSource` with that URL and default parameters. This is implemented as a Pydantic model_validator.

**Rationale:** This maintains backward compatibility with existing server code while the server-side changes land separately. Zero coordination required between repos.

### C2: Collection metadata storage mechanism

**Question:** The KnowledgeStorePort does not currently have methods for reading/writing collection-level metadata (only chunk-level). How should source config be persisted?

**Decision:** Add `get_collection_metadata` and `set_collection_metadata` methods to the KnowledgeStorePort protocol and implement them in ChromaDBAdapter using ChromaDB's native `collection.modify(metadata=...)` and `collection.metadata` API. The MockKnowledgeStorePort in tests will also be updated.

**Rationale:** ChromaDB natively supports collection-level metadata. Extending the port keeps the hexagonal architecture clean. This is the minimal surface area needed.

### C3: Progress reporting mechanism

**Question:** How should progress updates be reported? The story mentions "Report progress back via result queue for job status updates" but doesn't define the message format.

**Decision:** The plugin will emit structured `IngestWebsiteProgress` events to the result queue at key milestones (per-source crawl start, crawl complete, pipeline complete, job complete). The progress model includes: source URL, status enum (CRAWLING, SUMMARIZING, EMBEDDING, STORING, COMPLETED, FAILED), pages_crawled count, chunks_processed count. The plugin's handle method will accept an optional `transport` port kwarg for publishing progress.

**Rationale:** This aligns with the `IngestionJobStatus` enum defined in the story's GraphQL schema. The platform server can use these to update job status.

### C4: maxDepth semantics

**Question:** What does `maxDepth=0` mean exactly? The story says "0 = base page only" -- does that mean only the URL provided, with no link following?

**Decision:** Yes. `maxDepth=0` means only the base URL itself is crawled, no links are followed. `maxDepth=1` means the base URL plus any pages linked from it. `maxDepth=-1` means unlimited depth (current behavior).

**Rationale:** This matches standard crawling conventions and the story's explicit definition.

### C5: Glob pattern matching library

**Question:** Which library should be used for URL glob pattern matching (includePatterns/excludePatterns)?

**Decision:** Use Python's built-in `fnmatch.fnmatch` against the URL path component. This is zero-dependency and supports standard glob syntax (*, ?, [...]).

**Rationale:** fnmatch is in the stdlib, handles the documented patterns like "/docs/*" and "*.pdf", and avoids adding new dependencies.

### C6: Multi-source collection naming

**Question:** When multiple sources are provided, should they all go into the same collection? Currently the collection name is derived from the netloc of the single baseUrl.

**Decision:** All sources for a given VC go into the same collection. The collection name will be derived from the `personaId` (which uniquely identifies the VC's knowledge base), not from the URL netloc. Format: `{personaId}-knowledge`. For backward compat, if no sources are provided and only baseUrl is given, the legacy netloc-based naming is used.

**Rationale:** When a VC has multiple website sources, they need to end up in the same knowledge collection. The persona_id is the stable identifier for the VC. However, changing the naming for legacy requests would break existing data, so the legacy path is preserved.

### C7: FULL mode scope -- per-source or per-request?

**Question:** When mode=FULL, does it wipe the entire collection (all sources) or only chunks from the specific source URLs?

**Decision:** FULL mode wipes the entire collection before ingesting. This is a per-request operation. If callers want to only refresh one source, they should use INCREMENTAL mode.

**Rationale:** "FULL: wipe collection first" is explicitly stated in the story. Partial wipes would require per-source chunk tracking which adds complexity not in the story scope.

### C8: Source config serialization for collection metadata

**Question:** ChromaDB collection metadata only supports flat key-value pairs with string/int/float values. How should the structured source config be stored?

**Decision:** Serialize the source config list as a JSON string stored under the key `_source_config` in collection metadata. Deserialize on read for refresh operations.

**Rationale:** This is the simplest approach that works within ChromaDB's metadata constraints. JSON round-trips cleanly for the source config structure.

### C9: Transport port availability in plugin handle

**Question:** The current plugin handle signature is `handle(event, **ports)`. How does the plugin access the transport port for progress reporting?

**Decision:** The transport port will be passed via the `**ports` kwargs as `transport=<TransportPort>`. The plugin will extract it with `ports.get("transport")`. If not provided, progress reporting is silently skipped (graceful degradation).

**Rationale:** This follows the existing plugin contract pattern where extra ports come via kwargs. The container/runner already passes ports this way.

### C10: Error handling for individual source failures

**Question:** If one source in a multi-source request fails, does the entire request fail?

**Decision:** Individual source failures are logged and included in the result but do not abort the remaining sources. The overall result is FAILURE only if all sources fail; otherwise it's SUCCESS with partial errors noted.

**Rationale:** Partial success is more useful than all-or-nothing for multi-source ingestion. The caller can inspect per-source errors in the result.

## Iteration 2

(No new ambiguities found -- all questions resolved in iteration 1.)
