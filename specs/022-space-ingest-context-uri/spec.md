# Feature Specification: Space Ingest Context Enrichment & URI Tracking

**Feature Branch**: `022-space-ingest-context-uri`
**Created**: 2026-04-17
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Contextual Knowledge Retrieval (Priority: P1)

As a virtual contributor user, when I ask a question about a specific post or contribution within a space, the system retrieves relevant chunks that include the parent callout's context (title and description), so the LLM can provide accurate, contextually grounded answers even when the individual contribution never mentions its parent topic.

**Why this priority**: Without callout context prepended to contributions, chunked content loses its grouping hierarchy. Individual posts like "ДГ №..." never mention the parent topic "Панчарево", making retrieval miss the connection and the answer lack geographic/topical grounding.

**Independent Test**: Ingest a space where posts reference implicit parent context; query for the parent topic and verify retrieved chunks contain both parent and child content.

**Acceptance Scenarios**:

1. **Given** a space with a callout titled "Панчарево" containing posts that don't mention the callout name, **When** the space is ingested, **Then** each post's stored content is prefixed with the callout title and a truncated description (up to 400 chars).
2. **Given** a callout with a description and a whiteboard contribution, **When** ingested, **Then** the whiteboard content includes the callout context header.
3. **Given** a callout with link contributions, **When** ingested, **Then** the link content includes the callout context before the link title and description.

---

### User Story 2 - Source URI Attribution (Priority: P2)

As a virtual contributor user, when the system cites sources in its response, each source includes a clickable URI pointing to the original Alkemio entity (space, callout, post, whiteboard, or link), so I can navigate directly to the source material.

**Why this priority**: Without URIs propagated through the pipeline, the server-side "- [title](uri)" source block either shows broken links or falls back to opaque internal IDs, degrading user trust in cited sources.

**Independent Test**: Ingest a space, query the knowledge store, and verify stored chunk metadata contains `uri` fields matching the Alkemio entity URLs.

**Acceptance Scenarios**:

1. **Given** a space with a profile URL, **When** ingested, **Then** the space document's metadata contains `uri` set to the space's profile URL.
2. **Given** a post with a profile URL, **When** ingested, **Then** the post chunk metadata in the vector store contains a `uri` field.
3. **Given** a link contribution with a `uri` field, **When** ingested, **Then** the stored metadata's `uri` is the link's URI (not the profile URL).
4. **Given** a contribution without any URL, **When** ingested, **Then** the `uri` metadata field is absent from the stored entry (not null or empty).

---

### Edge Cases

- Callout with empty description: context prefix should be the callout title only, no trailing separator.
- Contribution with empty content after HTML stripping: should be skipped entirely (existing dedup logic).
- Entity with `url` field as empty string: should be stored as `None`, not empty string.
- Duplicate content across contributions: dedup by content hash should still work after context enrichment (different parents produce different hashes).

## Requirements

### Functional Requirements

- **FR-001**: System MUST prepend the parent callout's display name and truncated description (max 400 chars) to each contribution's content before storage.
- **FR-002**: System MUST fetch `url` fields from all Alkemio GraphQL profile objects (spaces, subspaces, callouts, posts, whiteboards, links).
- **FR-003**: `DocumentMetadata` MUST support an optional `uri` field that propagates through the ingest pipeline to the vector store.
- **FR-004**: `StoreStep` MUST conditionally include `uri` in stored metadata only when non-null/non-empty.
- **FR-005**: Link contributions MUST prefer the link's `uri` field over the profile `url` for the metadata URI.

### Key Entities

- **DocumentMetadata**: Extended with `uri: str | None` -- the canonical URL of the source entity in Alkemio.
- **Callout Context**: Derived at processing time from callout name + truncated description; not a persisted entity.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of ingested space documents with profile URLs have `uri` in their stored metadata.
- **SC-002**: Contribution content stored in the vector DB includes the parent callout title as a prefix.
- **SC-003**: Expert plugin RAG retrieval for parent-topic queries returns relevant child contributions.

## Assumptions

- The Alkemio GraphQL API returns `url` on profile objects (this is an existing field, not a new API addition).
- Callout descriptions over 400 characters can be safely truncated for context enrichment without losing critical meaning.
- The `_strip_html` function correctly handles all HTML variations present in callout descriptions.
