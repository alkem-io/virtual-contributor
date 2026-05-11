# Feature Specification: Ingest Space Knowledge-Base Routing

**Feature Branch**: `033-ingest-space-kb-routing`
**Created**: 2026-05-11
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Knowledge-Base-Backed VCs Successfully Ingest (Priority: P1)

As a **virtual contributor operator**, when I create or refresh a virtual contributor whose body of knowledge is an **alkemio-knowledge-base** (not a space), I MUST receive a populated knowledge collection so that downstream RAG queries are grounded in real content instead of hallucinated.

**Why this priority**: On the acceptance environment, 69 of 238 VCs (~29 %) are backed by `alkemio-knowledge-base`. Before this change, every single one of them was producing an empty Chroma collection because the ingest-space plugin issued `lookup.space()` for all bodies of knowledge regardless of type. The Alkemio server returned `ENTITY_NOT_FOUND`, the pipeline aborted before reaching the orphan-cleanup safety net, and the empty placeholder collection survived — which then served as the RAG source for every expert / guidance query against those VCs, producing confident-but-hallucinated answers. Restoring ingest for ~29 % of the platform's VCs is the highest-impact behavioural change available.

**Independent Test**: Publish an `IngestBodyOfKnowledge` event with `type: "alkemio-knowledge-base"` and a valid `bodyOfKnowledgeId` whose knowledge base contains at least one callout. Assert that (a) the ingest pipeline completes with `result: "success"`, (b) the resulting collection contains chunks derived from the knowledge base's callouts, and (c) no `Unable to find Space` error appears in the plugin logs.

**Acceptance Scenarios**:

1. **Given** an `IngestBodyOfKnowledge` event with `type="alkemio-knowledge-base"` and a `bodyOfKnowledgeId` that resolves to a knowledge base on the Alkemio server, **When** the plugin handles the event, **Then** it issues a `lookup.knowledgeBase(ID: …)` GraphQL query (not `lookup.space()`) and the resulting documents are stored under the collection name `{bok_id}-{purpose}`.
2. **Given** an `IngestBodyOfKnowledge` event with `type="alkemio-space"`, **When** the plugin handles the event, **Then** the pre-existing space-tree traversal runs unchanged and produces the same documents it did before this change.
3. **Given** an `IngestBodyOfKnowledge` event with an unrecognised `type` value (e.g. a future addition, a typo, or an empty string), **When** the plugin handles the event, **Then** the plugin defaults to the space reader, preserving today's behaviour for the dominant case (169 / 238 VCs) rather than failing fast.

---

### User Story 2 - Operator Sees the Resolved Routing Decision in Logs (Priority: P2)

As an **operator investigating an ingest run**, when I look at the ingest-space pod logs for a given BoK, I MUST be able to see which reader path was taken (`alkemio-space` vs `alkemio-knowledge-base`) so I can quickly distinguish "wrong type routed" from "right type but no content" without re-reading the source.

**Why this priority**: This is observability scaffolding, not a behavioural fix. It is P2 because without it, diagnosing a future regression in routing requires reading the plugin source against the message body — slow under incident pressure. The cost of adding a single `logger.info` line is negligible.

**Independent Test**: Trigger any ingest run and grep the pod logs for the line containing the BoK id and type — both must appear on a single line at INFO level before any further pipeline output for that BoK.

**Acceptance Scenarios**:

1. **Given** an `IngestBodyOfKnowledge` event arrives, **When** the plugin begins handling it, **Then** an INFO-level log line is emitted containing the `body_of_knowledge_id`, the `type`, and the `purpose` from the event.
2. **Given** the same event, **When** the plugin completes the run, **Then** the existing pipeline log lines (chunk counts, embedding stats, etc.) remain unchanged.

---

### User Story 3 - Knowledge-Base Documents Are Tagged as `knowledge`, Not `space` (Priority: P3)

As a **downstream consumer of the knowledge store** (expert / guidance plugins), when I filter or display documents by their `type` metadata, knowledge-base root documents MUST be tagged `knowledge` (not `space`) so the metadata accurately reflects what the document represents.

**Why this priority**: The downstream consumers currently use the `type` field mostly for display/filtering, not for routing logic — so a mis-tag does not break behaviour today. But emitting accurate metadata removes a class of subtle future bugs where a consumer adds type-sensitive logic and silently miscategorises ~29 % of root documents. The `DocumentType.KNOWLEDGE` enum value already exists for exactly this purpose.

**Independent Test**: Construct a knowledge-base GraphQL response with a populated profile description; invoke `read_knowledge_base_tree`; assert the returned root document's `metadata.type` equals `"knowledge"`.

**Acceptance Scenarios**:

1. **Given** a knowledge-base lookup returns a payload with a non-empty `profile.description`, **When** `read_knowledge_base_tree` builds documents from it, **Then** the root document's `metadata.type` equals `DocumentType.KNOWLEDGE.value` (`"knowledge"`).
2. **Given** a space lookup returns an equivalent payload, **When** `read_space_tree` builds documents from it, **Then** the root document's `metadata.type` equals `DocumentType.SPACE.value` (`"space"`) — i.e. the space path is unaffected by the new override.

---

### Edge Cases

- **Knowledge base not found**: If `lookup.knowledgeBase(ID:)` returns `null` (entity missing or unauthorised), the reader returns an empty document list. The plugin's existing empty-result handler then runs the cleanup pipeline, removing any stale chunks for that BoK — the same behaviour today's space reader exhibits for a missing space.
- **Empty knowledge base**: A knowledge base with no callouts and no profile description produces zero documents. Cleanup runs, the collection is empty, and the result is reported as `success` (no error, no orphan chunks).
- **Knowledge base with the same id as a space**: BoK ids in Alkemio are globally unique across entity types, so this collision cannot occur. The dispatcher relies entirely on `event.type` — never on probing both endpoints.
- **`event.type` is `None` or empty string**: Falls through to the space reader (the safe default for the dominant case). The space reader will then return an empty list if `lookup.space()` fails.
- **GraphQL transport error on the knowledge-base query**: Propagates the same way as for the space query — the plugin's exception handler emits an `IngestBodyOfKnowledgeResult` with `result="failure"` and the error message, without running cleanup (so previously-good chunks are preserved).

## Requirements

### Functional Requirements

- **FR-001**: The ingest-space plugin MUST route `IngestBodyOfKnowledge` events to the GraphQL query that matches the event's `type` field — `lookup.space(ID:)` for `alkemio-space`, `lookup.knowledgeBase(ID:)` for `alkemio-knowledge-base`.
- **FR-002**: An unrecognised `type` value MUST fall back to the space reader. The plugin MUST NOT raise an error, and MUST NOT attempt to probe both endpoints.
- **FR-003**: `read_knowledge_base_tree` MUST issue a GraphQL query that selects, at minimum: `id`, `profile { displayName description url }`, and `calloutsSet { callouts { … } }` — using the same `_CALLOUT_FIELDS` fragment that the space reader uses.
- **FR-004**: Documents emitted by the knowledge-base reader MUST go through the same `_process_space` callout/contribution traversal as the space reader, so post / whiteboard / link extraction behaves identically.
- **FR-005**: The root document of a knowledge-base traversal MUST be tagged with `DocumentType.KNOWLEDGE` (wire value `"knowledge"`); callouts, posts, whiteboards, and links retain their existing types.
- **FR-006**: The plugin MUST emit an INFO-level log line at the start of each `handle()` call containing the BoK id, type, and purpose.
- **FR-007**: The wire contract of `IngestBodyOfKnowledge` and `IngestBodyOfKnowledgeResult` MUST NOT change — no new fields, no renames, no removals.
- **FR-008**: The legacy entrypoint `read_space_tree` MUST remain available with its existing signature so external imports and existing tests continue to work.
- **FR-009**: Test coverage MUST include: (a) the knowledge-base reader walks callouts correctly, (b) the knowledge-base reader emits `KNOWLEDGE`-typed root documents, (c) the knowledge-base reader returns an empty list on a `null` GraphQL response, (d) the dispatcher routes each known type to the matching reader, (e) the dispatcher falls back to the space reader on unknown types, and (f) the plugin propagates `event.type` into the dispatcher.

### Key Entities

- **`read_body_of_knowledge` (dispatcher)**: Module-level async function in `plugins/ingest_space/space_reader.py`. Takes a GraphQL client, a BoK id, and a BoK type string; returns a list of `Document`. Selects between `read_space_tree` and `read_knowledge_base_tree` based on the type.
- **`read_knowledge_base_tree`**: Module-level async function that issues `KNOWLEDGE_BASE_QUERY`, reshapes the response into the same dict layout `_process_space` already understands, and delegates the traversal — passing `top_doc_type=DocumentType.KNOWLEDGE.value` so the root tag differs from the space path.
- **`BOK_TYPE_SPACE` / `BOK_TYPE_KNOWLEDGE_BASE` constants**: Single source of truth for the wire-format `type` values used by `IngestBodyOfKnowledge`. Match the Alkemio server's published vocabulary.
- **`_process_space.top_doc_type`**: New optional kw-only parameter that overrides the depth-0 document type. Default `None` preserves today's `SPACE` / `SUBSPACE` branching.
- **`KNOWLEDGE_BASE_QUERY`**: Module-level GraphQL document string; same callout fragment as `SPACE_TREE_QUERY` but no `subspaces` and no `collaboration` wrapper.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100 % of `IngestBodyOfKnowledge` events with `type="alkemio-knowledge-base"` are routed to `lookup.knowledgeBase()`. None are routed to `lookup.space()`.
- **SC-002**: Zero `IngestBodyOfKnowledgeResult` envelopes are emitted with `result="failure"` and an `error.message` containing `Unable to find Space` for events whose `type="alkemio-knowledge-base"`. This is observable directly from the VC's own published RabbitMQ result stream — no server-side log access required.
- **SC-003**: The empty-`{bok_id}-knowledge` collections that the bulk refresh previously created for the ~69 knowledge-base-backed VCs are populated (or cleanly cleaned up, if the KB itself contains no callouts) on the next refresh wave.
- **SC-004**: Test suite gates the routing decision: tests fail if a future change causes an `alkemio-knowledge-base` event to call `lookup.space()`, or vice versa.

## Assumptions

- The Alkemio server's `lookup.knowledgeBase(ID:)` resolver returns the shape captured in `KNOWLEDGE_BASE_QUERY`: `{ id, profile, calloutsSet { callouts { … } } }`. Verified against the server's `KnowledgeBase` entity definition at the time of writing.
- BoK type values on the wire are stable strings — `alkemio-space` and `alkemio-knowledge-base`. The server controls this vocabulary; new types will be added by the server team and routed here in a subsequent change.
- Knowledge bases are flat (no nested subspaces). If the server adds a hierarchy in the future, `read_knowledge_base_tree` will need to be extended.
- Falling back to the space reader on unknown types is preferable to failing fast, because (a) the dominant case is space (169 / 238), so unknown-type messages from older servers are most plausibly mis-tagged spaces, and (b) the existing failure mode of an unknown-space-id (returns empty + cleans up) is already safe.
- The new `top_doc_type` parameter on `_process_space` is opt-in — existing call sites pass nothing and observe identical behaviour.
- No coordinated alkemio-server release is required: the GraphQL endpoints used by the new reader (`lookup.knowledgeBase`) already exist on every server version capable of holding a knowledge-base-typed BoK.
