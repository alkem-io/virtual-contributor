# Research: Ingest Space Knowledge-Base Routing

**Feature Branch**: `033-ingest-space-kb-routing`
**Date**: 2026-05-11

## Background

The ingest-space plugin runs against every `IngestBodyOfKnowledge` event the
RabbitMQ queue delivers, regardless of the body-of-knowledge type. The event
carries a `type` field (`alkemio-space` or `alkemio-knowledge-base`) but the
plugin previously ignored it and always issued `lookup.space(ID:)` via GraphQL.
Knowledge-base BoKs live in a different table on the Alkemio server, so the
query returns `ENTITY_NOT_FOUND` and the pipeline aborts after creating the
empty `{bok_id}-{purpose}` collection upfront — leaving an empty Chroma
collection that downstream RAG queries silently consume, producing
hallucinated answers.

Postgres survey on acceptance at the time of the fix:

| `bodyOfKnowledgeType` | count |
|---|---|
| `alkemio-space` | 169 |
| `alkemio-knowledge-base` | 69 |

i.e. ~29 % of the platform's VCs were affected.

## Decisions

### Decision 1: Branch on `event.type` in a small dispatcher

**Decision**: Add `read_body_of_knowledge(graphql_client, bok_id, bok_type)`
that selects between `read_space_tree` and `read_knowledge_base_tree` based
on the type.

**Rationale**: The branching point is at the GraphQL boundary — different
queries returning different shapes. A six-line `if/else` is the right level
of abstraction: it reads naturally, it is trivial to test, and it keeps the
two readers' implementations free of type-checking conditionals. The
plugin's `handle()` stays a one-liner against the dispatcher, so future
types can be added by extending the dispatcher without touching the plugin.

**Alternatives considered**:

- *Push the branching into `_process_space`*: rejected — it would mix
  GraphQL transport with the document-tree walker. They are orthogonal
  responsibilities.
- *Have the plugin issue both queries and merge results*: rejected —
  doubles GraphQL load, introduces ambiguity when both succeed (cannot
  happen today but is the kind of speculative complexity Principle 10
  forbids), and obscures the intent in logs.
- *Read the BoK type from the server before deciding*: rejected — adds a
  round trip and re-implements information the server already includes in
  the event envelope. The server is authoritative on the type field.

### Decision 2: Reshape the KB response to reuse `_process_space`

**Decision**: `read_knowledge_base_tree` wraps the GraphQL response into the
dict layout `_process_space` already understands, by inserting a synthetic
`collaboration.calloutsSet` and an empty `subspaces` list:

```python
space_shaped = {
    **kb,
    "collaboration": {"calloutsSet": kb.get("calloutsSet")},
    "subspaces": [],
}
```

**Rationale**: The callout / contribution traversal is identical between
spaces and knowledge bases. Duplicating ~150 lines of post / whiteboard /
link extraction in a parallel KB walker is exactly the kind of code that
silently drifts out of sync. By adapting the response shape at one place,
all future callout-handling improvements automatically apply to both code
paths.

**Alternatives considered**:

- *Parameterise `_process_space` with extractor callbacks*: rejected —
  over-engineered for a single new caller. Adding a callback API to a
  recursive walker invites further callback explosions when the next new
  caller arrives.
- *Refactor `_process_space` into two halves (root vs. callouts)*: rejected
  — current single-function design is small enough to keep; splitting it
  introduces a coordination contract between the two halves with no
  near-term benefit.

### Decision 3: Override the root document type via a kw-only `top_doc_type`

**Decision**: Add `top_doc_type: str | None = None` to `_process_space`.
When set and `depth == 0`, the root document is tagged with that value
instead of `DocumentType.SPACE`. Knowledge-base callers pass
`DocumentType.KNOWLEDGE.value`.

**Rationale**: The existing `SPACE` / `SUBSPACE` branching is semantically
correct for spaces. Knowledge bases are not spaces — `DocumentType.KNOWLEDGE`
already exists for exactly this purpose. Tagging root documents accurately
removes a future class of bugs where a downstream consumer adds
type-sensitive logic (filtering, display) and silently miscategorises ~29 %
of VCs.

**Alternatives considered**:

- *Always tag the root as `SPACE`*: rejected — accurate today only because
  no consumer differentiates. Inaccurate metadata is technical debt.
- *Always tag the root as `KNOWLEDGE` regardless of source*: rejected —
  would change the type tag for the 169 / 238 space-backed VCs, which is a
  larger behavioural change than this PR justifies.
- *Detect the type from the dict shape inside `_process_space`*: rejected —
  binds the walker to the response wire format, which the caller already
  knows. The override parameter is opt-in and explicit.

### Decision 4: Unknown `type` defaults to the space reader

**Decision**: Any `bok_type` value the dispatcher does not recognise routes
to `read_space_tree`.

**Rationale**: Space is the dominant case (169 / 238). The space reader's
existing failure mode for an id that does not resolve is benign — it
returns an empty list, the plugin's empty-result handler runs cleanup, and
the run is reported as success. By contrast, failing fast on unknown types
would surface as a new wave of `result: failure` envelopes for any future
server-introduced BoK type before this plugin is updated. The "soft" default
keeps the platform working during such a transition window.

**Alternatives considered**:

- *Raise on unknown types*: rejected for the reasons above. We can revisit
  if the server begins frequently introducing new types; today the BoK
  vocabulary is stable.
- *Log a warning but continue*: deferred — the plugin already logs the
  resolved type at INFO (US-2). A warning can be added in the future once
  we have a list of "known" types to validate against, rather than relying
  on the hard-coded string match in this PR.

### Decision 5: Keep `read_space_tree` exported with its existing signature

**Decision**: The new dispatcher does not replace `read_space_tree`.
`read_space_tree(graphql_client, space_id)` keeps the same name, parameters,
and return type.

**Rationale**: The existing test suite imports `read_space_tree` directly
and the plugin previously called it as a top-level function. Breaking the
import surface for a routing improvement would be pure churn. The
dispatcher is an additional entry point, not a replacement.

**Alternatives considered**:

- *Rename `read_space_tree` to `_read_space_tree` (private)*: rejected —
  forces unnecessary test rewrites and external import breakage for no
  behavioural gain.

## Decision Summary

| # | Decision | One-line rationale |
|---|---|---|
| 1 | Dispatch on `event.type` via a small `read_body_of_knowledge` function | Single branching point, naturally testable, keeps the plugin a one-liner |
| 2 | Reshape the KB response and reuse `_process_space` | Avoids duplicating ~150 lines of callout/post/whiteboard/link extraction |
| 3 | Override root document type via `top_doc_type` kwarg | Knowledge bases are tagged `knowledge`, not `space`; existing callers unaffected |
| 4 | Unknown `bok_type` defaults to the space reader | Preserves today's behaviour for the dominant case during any future server-side type expansion |
| 5 | Keep `read_space_tree` public with its existing signature | Avoids churn for existing callers and tests |
