# Data Model: Ingest Space Knowledge-Base Routing

**Feature Branch**: `033-ingest-space-kb-routing`
**Date**: 2026-05-11

This feature does not change the persisted data model or the wire schema of
any RabbitMQ event. It introduces two module-level constants, one new
GraphQL query document, two new module-level functions, and one new
optional parameter on an existing internal function. The only metadata
change observable to downstream consumers is the value of the `type` field
on root documents emitted from knowledge-base traversals.

## New / Modified Entities

### Module-level constants (new)

In `plugins/ingest_space/space_reader.py`:

| Name | Type | Value | Purpose |
|---|---|---|---|
| `BOK_TYPE_SPACE` | `str` | `"alkemio-space"` | Wire-format value of `IngestBodyOfKnowledge.type` for space-backed BoKs |
| `BOK_TYPE_KNOWLEDGE_BASE` | `str` | `"alkemio-knowledge-base"` | Wire-format value of `IngestBodyOfKnowledge.type` for knowledge-base-backed BoKs |

Single source of truth so tests and the dispatcher agree on the vocabulary
without sprinkling string literals through the module.

### GraphQL document (new)

`KNOWLEDGE_BASE_QUERY`: module-level constant containing the query string

```graphql
query KnowledgeBaseTree($kbId: UUID!) {
  lookup {
    knowledgeBase(ID: $kbId) {
      id
      profile { displayName description url }
      calloutsSet {
        callouts { … _CALLOUT_FIELDS … }
      }
    }
  }
}
```

`_CALLOUT_FIELDS` is the same fragment the space-tree query uses, so post /
whiteboard / link selections stay in lockstep between both readers.

### `read_knowledge_base_tree` (new function)

```python
async def read_knowledge_base_tree(
    graphql_client, kb_id: str,
) -> list[Document]:
    ...
```

| Field | Type | Notes |
|---|---|---|
| `graphql_client` | `Any` (duck-typed) | Must expose an awaitable `query(query_str, variables) -> dict` and `fetch_url(url) -> tuple[bytes, str] \| None` (the latter is consumed by callout link extraction inside `_process_space`). |
| `kb_id` | `str` | UUID of the knowledge base to ingest. |
| **returns** | `list[Document]` | Documents extracted from the KB's callouts; empty list if the KB does not resolve. |

Internal flow:

1. Issue `KNOWLEDGE_BASE_QUERY` with `{"kbId": kb_id}`.
2. Read `data["lookup"]["knowledgeBase"]`; return `[]` if `None`.
3. Reshape to `{**kb, "collaboration": {"calloutsSet": kb["calloutsSet"]}, "subspaces": []}`.
4. Call `_process_space(...)` with `depth=0` and `top_doc_type=DocumentType.KNOWLEDGE.value`.
5. Log doc count and link-fetch stats at INFO.

### `read_body_of_knowledge` (new function)

```python
async def read_body_of_knowledge(
    graphql_client, bok_id: str, bok_type: str,
) -> list[Document]:
    ...
```

| Field | Type | Notes |
|---|---|---|
| `bok_type` | `str` | The `type` field from `IngestBodyOfKnowledge`. |
| **returns** | `list[Document]` | Result of the selected reader; semantically identical to whichever underlying reader runs. |

Branching:

| `bok_type` value | Reader invoked |
|---|---|
| `BOK_TYPE_KNOWLEDGE_BASE` | `read_knowledge_base_tree` |
| anything else (incl. `BOK_TYPE_SPACE`, empty string, unknown) | `read_space_tree` |

### `_process_space.top_doc_type` (new parameter)

| Field | Type | Default | Purpose |
|---|---|---|---|
| `top_doc_type` | `str \| None` (kw-only) | `None` | If set, the depth-0 document is tagged with this value instead of `DocumentType.SPACE` / `DocumentType.SUBSPACE`. |

Behaviour rules:

- When `top_doc_type is None`: depth-0 → `DocumentType.SPACE`, depth>0 → `DocumentType.SUBSPACE`. Identical to the prior behaviour.
- When `top_doc_type is not None` and `depth == 0`: doc type is `top_doc_type`.
- When `top_doc_type is not None` and `depth > 0`: ignored — recursion still uses `SUBSPACE`. (Knowledge bases have no subspaces, so this branch is unreachable today but defined for safety.)

## Document Metadata Changes Observable Downstream

| Path | Pre-change `metadata.type` of root document | Post-change `metadata.type` of root document |
|---|---|---|
| `lookup.space(ID:)` → `read_space_tree` | `"space"` | `"space"` (unchanged) |
| `lookup.knowledgeBase(ID:)` → `read_knowledge_base_tree` | (path did not exist; an empty collection was produced) | `"knowledge"` |

All other document types (`callout`, `post`, `whiteboard`, `link`,
`subspace`) are unchanged.

## Unchanged

- Event schemas: `IngestBodyOfKnowledge` and `IngestBodyOfKnowledgeResult`.
- Pipeline steps: chunking, content hashing, change detection, summarisation, embedding, store, orphan cleanup.
- Collection naming: still `{bok_id}-{purpose}`.
- All adapters (`KnowledgeStorePort`, `EmbeddingsPort`, `LLMPort`).
