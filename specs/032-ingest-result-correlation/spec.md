# Feature Specification: Ingest Website Result Correlation Fields

**Feature Branch**: `032-ingest-result-correlation`
**Created**: 2026-04-30
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Correlate Website Ingest Result to Owning Persona (Priority: P1)

As an **alkemio-server result handler**, when I receive an `IngestWebsiteResult` event from the virtual-contributor over RabbitMQ, I MUST be able to identify which persona, body of knowledge, and content type the result belongs to — without keeping correlation state on my side.

**Why this priority**: This is the core value of the change. The alkemio-server is the only consumer of the result envelope, and a result with no identification fields is effectively orphaned: the server cannot mark a body of knowledge as "ingested" or surface ingestion status to the persona's owner. Without these fields the entire end-to-end ingestion feedback loop is broken.

**Independent Test**: Send an `IngestWebsite` event with a populated `personaId`, `type`, and `purpose`, then assert the resulting `IngestWebsiteResult` payload (camelCase, `by_alias=True`) contains the same `personaId`, `type`, `purpose`, and a `bodyOfKnowledgeId` field (defaulting to empty string for URL-keyed websites).

**Acceptance Scenarios**:

1. **Given** an `IngestWebsite` event with `personaId="p-1"`, `type="website"`, `purpose="knowledge"`, **When** the plugin completes a successful crawl-and-ingest run, **Then** the emitted `IngestWebsiteResult` JSON contains `personaId: "p-1"`, `type: "website"`, `purpose: "knowledge"`, and `bodyOfKnowledgeId: ""`.
2. **Given** the same input event, **When** the crawl returns zero documents and the plugin runs the cleanup-only path, **Then** the emitted result still carries the same identification fields.
3. **Given** the same input event, **When** the plugin raises an exception during ingest, **Then** the emitted failure result still carries the same identification fields so the server can mark the correct persona's ingest as failed.

---

### User Story 2 - Backward-Compatible Wire Format (Priority: P1)

As an **alkemio-server operator**, I MUST be able to deploy the new virtual-contributor image without simultaneously deploying a server change. Existing servers that don't yet read the new fields MUST keep working.

**Why this priority**: The two services release independently. Any change to the result envelope that breaks existing consumers blocks the release.

**Independent Test**: Deserialize a result payload produced by the new code with a Pydantic model that lacks the new fields — it must succeed. Conversely, serialize a result with no identification fields set — it must produce a payload where the new fields default to empty strings (not omitted, not `null`).

**Acceptance Scenarios**:

1. **Given** the new `IngestWebsiteResult` model, **When** instantiated with no identification arguments, **Then** `model_dump(by_alias=True)` includes `bodyOfKnowledgeId: ""`, `personaId: ""`, `type: ""`, `purpose: ""`.
2. **Given** a server that ignores unknown JSON fields, **When** it receives the new payload, **Then** existing fields (`result`, `error`, `timestamp`) are unchanged in name and type.

---

### Edge Cases

- **Empty `IngestWebsite` request**: If the inbound event has empty strings for `type`, `purpose`, or `personaId`, the result simply echoes those empty strings — no validation is added because the wire contract does not require non-empty values.
- **Cleanup-only path with no documents**: The result still carries identification fields so the server can record the empty-but-valid ingest run against the correct persona.
- **Exception path**: A crash inside the ingest pipeline must not strip identification fields. The exception handler constructs a failure result with the same fields populated from the inbound event.
- **`bodyOfKnowledgeId` for websites**: Websites are URL-identified, not UUID-keyed, so the field is reserved for future use but defaults to empty string for the website plugin. The field is present so the schema is consistent with other ingest result envelopes.

## Requirements

### Functional Requirements

- **FR-001**: `IngestWebsiteResult` MUST expose four identification fields — `body_of_knowledge_id`, `type`, `purpose`, `persona_id` — and serialize them with the camelCase aliases `bodyOfKnowledgeId`, `type`, `purpose`, `personaId`.
- **FR-002**: Each identification field MUST default to an empty string so the model is constructible with no arguments and existing call sites need no migration.
- **FR-003**: The `IngestWebsitePlugin.handle` method MUST copy `type`, `purpose`, and `persona_id` from the inbound `IngestWebsite` event to every `IngestWebsiteResult` it returns, on every code path: cleanup-only, successful ingest, failed ingest, and exception.
- **FR-004**: The result envelope MUST remain backward-compatible: no existing field is renamed, retyped, or removed, and the new fields are additive.
- **FR-005**: Identification fields MUST round-trip via `model_dump(by_alias=True)` and `model_validate(...)` without loss.
- **FR-006**: Test coverage MUST include: default-value serialization (FR-002), explicit-value round-trip (FR-005), propagation from request to result on the normal-ingest path (FR-003), and propagation on the empty-crawl cleanup path (FR-003).

### Key Entities

- **IngestWebsiteResult**: The Pydantic event model emitted by the website ingest plugin. Now carries `body_of_knowledge_id`, `type`, `purpose`, `persona_id` alongside the pre-existing `result`, `error`, `timestamp` fields.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of `IngestWebsiteResult` envelopes emitted by the plugin carry non-default identification fields when the inbound request specifies them.
- **SC-002**: Existing `IngestWebsiteResult` consumers (alkemio-server) continue to deserialize result payloads with no error after this change.
- **SC-003**: The alkemio-server can correlate every received `IngestWebsiteResult` to its originating persona without consulting any local state — the result envelope is self-describing.
- **SC-004**: Test suite asserts identification-field propagation on at least the normal-ingest path and the cleanup-only path; both pass.

## Assumptions

- The alkemio-server result handler treats unknown JSON fields as ignorable (the standard JSON-deserialization contract on its side).
- Empty-string defaults are acceptable substitutes for "not specified" — neither side treats them as semantically distinct from missing fields.
- The `bodyOfKnowledgeId` field is reserved for parity with other ingest result schemas; the website plugin does not yet need to populate it because websites are keyed by URL, not UUID. A future change may begin populating it without further schema work.
- No coordinated server release is required — the change is additive on the wire.
