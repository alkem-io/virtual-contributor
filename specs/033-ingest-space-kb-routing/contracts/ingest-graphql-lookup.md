# Contract: Ingest GraphQL Lookup Routing

**Feature**: [spec.md](../spec.md)
**Date**: 2026-05-11

## Scope

This contract describes the client-side GraphQL queries the ingest-space
plugin issues against the Alkemio server's private API, and how the choice
between them is governed by the inbound `IngestBodyOfKnowledge` event's
`type` field.

No change is made to any RabbitMQ event schema; the contract here is the
plugin's expectations of the Alkemio GraphQL schema. The server endpoints
referenced (`lookup.space`, `lookup.knowledgeBase`) already exist —
this PR begins exercising the second one rather than introducing either.

## Before / After

### Before

For every `IngestBodyOfKnowledge` event, regardless of `type`:

```graphql
query SpaceTree($spaceId: UUID!) {
  lookup {
    space(ID: $spaceId) { id, profile { … }, collaboration { … }, subspaces [...] }
  }
}
```

The server returns `ENTITY_NOT_FOUND` when `$spaceId` resolves to a
knowledge-base entity (which lives in a different table), and the
ingest pipeline aborts.

### After

The plugin selects one of two queries based on `event.type`:

| `event.type` | GraphQL operation | Variables |
|---|---|---|
| `"alkemio-space"` (or unknown) | `query SpaceTree($spaceId: UUID!) { lookup { space(ID: $spaceId) { … } } }` | `{ spaceId: <bok_id> }` |
| `"alkemio-knowledge-base"` | `query KnowledgeBaseTree($kbId: UUID!) { lookup { knowledgeBase(ID: $kbId) { id, profile { displayName description url }, calloutsSet { callouts { … _CALLOUT_FIELDS … } } } } }` | `{ kbId: <bok_id> }` |

## GraphQL Schema Expectations

The plugin assumes the server exposes the following resolver field on the
`Lookup` type:

```graphql
type LookupQueryResults {
  knowledgeBase(ID: UUID!): KnowledgeBase!
}

type KnowledgeBase {
  id: UUID!
  profile: Profile!
  calloutsSet: CalloutsSet!
}
```

Selected fields used by the client:

- `KnowledgeBase.id` (UUID)
- `KnowledgeBase.profile { displayName, description, url }`
- `KnowledgeBase.calloutsSet.callouts` — each member with the same shape the
  space query already selects: `id, framing { profile { … } }, contributions { post {…}, whiteboard {…}, link {…} }`.

The client never selects `KnowledgeBase.virtualContributor` or
`KnowledgeBase.authorization`. The server's existing READ_ABOUT
authorisation check on `lookup.knowledgeBase` is sufficient — the same
session token that authorised `lookup.space` previously authorises
`lookup.knowledgeBase` for the ingest service identity.

## Wire Compatibility

| Event | Pre-change | Post-change |
|---|---|---|
| `IngestBodyOfKnowledge` (consumed) | fields read: all except `type` | fields read: all incl. `type` |
| `IngestBodyOfKnowledgeResult` (produced) | unchanged shape | unchanged shape |

Reading the `type` field is **not** a wire change — the field was already
defined on the event model. Consumers that emit the event are unaffected.

## Error Paths

| Condition | Server response | Plugin behaviour | Reported result |
|---|---|---|---|
| KB id resolves to a real knowledge base with callouts | 200 OK with KB payload | Walk the tree, ingest documents, run pipeline | `result: "success"` |
| KB id resolves to a real knowledge base with no callouts and no description | 200 OK with KB payload, empty `calloutsSet.callouts` | Cleanup pipeline runs against the empty collection | `result: "success"` |
| KB id does not resolve (deleted, never existed, unauthorised) | 200 OK with `data.lookup.knowledgeBase: null` (or a GraphQL error) | Reader returns `[]`; cleanup pipeline runs | `result: "success"` if the GraphQL call did not raise; `result: "failure"` if it did |
| Network / transport error during the lookup | `httpx`/transport exception | Caught by plugin's exception handler; no cleanup runs | `result: "failure"`, `error.message` populated |
| `event.type` is unknown / empty / missing | n/a (client-side) | Falls back to `lookup.space(ID:)` — same behaviour as today | Same as the corresponding space-path outcome |

## Backward Compatibility

- No GraphQL query the plugin previously issued is removed; `lookup.space(ID:)` keeps its exact shape and variable name (`$spaceId`).
- No new field is added to any RabbitMQ message.
- No change to the collection naming convention (`{bok_id}-{purpose}`).
- The legacy entrypoint `read_space_tree(graphql_client, space_id)` is exported with its existing signature, so any external caller (and the existing test suite) continues to work.
