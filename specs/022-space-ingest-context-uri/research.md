# Research: Space Ingest Context Enrichment & URI Tracking

**Feature Branch**: `022-space-ingest-context-uri`
**Date**: 2026-04-17

## Decision Summary

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Prepend callout context to contributions | Preserve hierarchy lost during chunking |
| D2 | Truncate callout description to 400 chars | Balance context value vs. chunk budget |
| D3 | Optional `uri` field on DocumentMetadata | Backward-compatible extension |
| D4 | Conditional `uri` in StoreStep metadata | Avoid storing null/empty values in ChromaDB |
| D5 | Prefer link `uri` over profile `url` | Links have explicit target URIs that differ from profile URLs |

## Decisions

### D1: Prepend callout context to contributions

**Decision**: Each contribution's content is prefixed with `{callout_name}\n\n{callout_desc_truncated}\n\n# {contribution_title}\n\n{content}`.

**Rationale**: In Alkemio's 3-level space hierarchy (space -> subspace -> callout -> contribution), the callout provides the topical grouping. When contributions are chunked independently, the semantic connection to the parent topic is lost. For example, posts under a callout named "Панчарево" never mention the neighborhood name themselves -- prepending the callout context ensures the vector embedding captures this relationship.

**Alternatives considered**:
- Store callout context as separate metadata field: Rejected because vector similarity search operates on document content, not metadata. The context must be in the embedded text.
- Store callout as a separate document and rely on multi-hop retrieval: Rejected as over-engineered for the current single-collection RAG architecture.

### D2: Truncate callout description to 400 characters

**Decision**: `_strip_html(callout_desc)[:400]` is used for the context prefix.

**Rationale**: Callout descriptions can be lengthy HTML. The prefix serves as a semantic anchor, not a full reproduction. 400 characters capture enough context (typically 1-2 sentences) without significantly inflating chunk sizes. The HTML is stripped before truncation.

**Alternatives considered**:
- No truncation: Rejected because some callout descriptions are multiple paragraphs, which would dominate the contribution's own content in the embedding.
- LLM-based summarization: Rejected as unnecessarily expensive for a prefix hint.

### D3: Optional `uri` field on DocumentMetadata

**Decision**: Added `uri: str | None = None` as a dataclass field.

**Rationale**: Backward-compatible -- existing code that doesn't set `uri` gets `None` by default. The field flows through the existing pipeline (Chunk inherits metadata from Document) without requiring changes to intermediate steps.

**Alternatives considered**:
- Store URI in a separate lookup table: Rejected as it would require a new storage mechanism outside the vector store.
- Encode URI in the `source` field: Rejected because `source` uses the `type:id` format (e.g., `post:abc123`) for internal identification, not user-facing URLs.

### D4: Conditional `uri` in StoreStep metadata

**Decision**: Only include `uri` key in stored metadata when `c.metadata.uri` is truthy.

**Rationale**: ChromaDB stores metadata as flat dicts. Including `null` or empty string values wastes space and complicates downstream queries that check for URI presence. Conditional inclusion keeps metadata clean.

### D5: Prefer link `uri` over profile `url`

**Decision**: For link contributions, `uri=uri or link_profile.get("url") or None`.

**Rationale**: A link's `uri` field is the actual target URL (e.g., an external website), while `profile.url` is the Alkemio platform URL for the link entity itself. Users want to navigate to the linked resource, not the link's profile page.
