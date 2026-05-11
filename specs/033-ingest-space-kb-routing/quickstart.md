# Quickstart: Ingest Space Knowledge-Base Routing

**Feature Branch**: `033-ingest-space-kb-routing`
**Date**: 2026-05-11

## What this feature does

Routes `IngestBodyOfKnowledge` events to the correct GraphQL lookup
endpoint based on the body-of-knowledge type:

- `type: "alkemio-space"` → `lookup.space(ID:)`
- `type: "alkemio-knowledge-base"` → `lookup.knowledgeBase(ID:)`
- anything else → falls back to `lookup.space(ID:)`

Before this change the plugin only knew about spaces, so the ~29 % of VCs
backed by knowledge bases were producing empty Chroma collections, which
RAG queries then consumed as if they were real grounding.

## Configuration

No new environment variables. No new configuration. The change is gated
entirely by the `type` field on inbound RabbitMQ messages, which the
Alkemio server already populates.

## How to verify it works

### 1. Unit / integration tests (local)

```bash
poetry run pytest tests/plugins/test_ingest_space.py -q
```

Expect 37+ tests, all green. The new classes added by this feature:

- `TestKnowledgeBaseReader` — four tests covering the KB GraphQL query, root document type tagging, and empty-result handling.
- `TestBodyOfKnowledgeDispatcher` — three tests asserting the dispatcher routes each known type and the unknown-type fallback.
- `TestIngestSpacePluginDispatchesOnType` — two end-to-end tests that the plugin propagates `event.type` into the dispatcher and the correct reader is awaited.

### 2. Acceptance environment (post-deploy)

After a release containing this fix is deployed to acceptance:

1. Pick a VC whose body of knowledge is an `alkemio-knowledge-base` — the
   acceptance database has 69 of them at the time of writing. The
   reference case from the bug report is `test-vc-flow-003`, BoK id
   `e2cf604d-8ef0-43d5-8220-9324f43ce4ca`.
2. Trigger a refresh of that body of knowledge (UI: "UPDATE KNOWLEDGE";
   or publish an `IngestBodyOfKnowledge` event directly to the
   `virtual-contributor-ingest-body-of-knowledge` queue).
3. Tail the `ingest-space` pod logs. Confirm:
   - A line of the form `Ingesting BoK <id> (type=alkemio-knowledge-base, purpose=knowledge)`.
   - No `Unable to find Space using options 'undefined'` error follows.
   - The pipeline reaches `Knowledge base tree: emitted N unique documents` with `N > 0` if the KB has content, or `N = 0` if it does not.
4. Query the resulting Chroma collection (`{bok_id}-knowledge`) and confirm
   chunks are present (or the collection is empty after cleanup, if the KB
   itself was empty).
5. Ask a question of the VC that previously hallucinated; confirm the
   answer is grounded and cites sources.

### 3. Regression check for space-backed VCs

Pick any VC whose body of knowledge is an `alkemio-space` (169 of them on
acceptance — most VCs). Trigger a refresh; confirm:

- A line of the form `Ingesting BoK <id> (type=alkemio-space, …)`.
- Existing `Space tree: emitted N unique documents` log line still appears with the same shape.
- The resulting collection contains the same documents it did before this change (chunk count, dedup behaviour identical).

## Files changed

| Path | Change |
|---|---|
| `plugins/ingest_space/space_reader.py` | + `BOK_TYPE_*` constants, `KNOWLEDGE_BASE_QUERY`, `read_knowledge_base_tree()`, `read_body_of_knowledge()` dispatcher, `top_doc_type` kwarg on `_process_space` |
| `plugins/ingest_space/plugin.py` | Route through `read_body_of_knowledge(event.type)`; log resolved type at the start of `handle()` |
| `tests/plugins/test_ingest_space.py` | New `TestKnowledgeBaseReader`, `TestBodyOfKnowledgeDispatcher`, `TestIngestSpacePluginDispatchesOnType` |

## Rollback

The change is additive on the client side. To roll back:

1. Revert the commit on `fix/ingest-space-knowledge-base` (PR #98).
2. Redeploy the previous image.

No data migration, no schema rollback, no coordinated server change.
Existing collections produced under the new code remain valid input for
RAG queries; the only difference is the `type` metadata on root documents,
which downstream consumers do not branch on today.
