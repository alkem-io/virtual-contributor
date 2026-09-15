# 19. Declarative conditional edges and typed nodes in PromptGraph

Date: 2026-08-19

## Status

Accepted.

## Context

[vc#102](https://github.com/alkem-io/virtual-contributor/issues/102) asks to
cover the libra-flow workshop-design flow (slot-filling → clarifying
question, refine-vs-generate routing, and BoK RAG) in the `generic` plugin
purely via configuration — zero flow-specific engine code.

The `expert` plugin's graph path (`plugins/expert/plugin.py::_handle_with_graph`)
already executes a caller-supplied `promptGraph` today, so a linear
retrieve → generate payload is runnable via configuration on `expert`. Two
options were considered for hosting the workshop flow:

- **Option 2 — land it on `expert`, as a linear graph.** Verified runnable,
  but lossy: `expert`'s graph path has no conditional edges, no way to
  return a value verbatim without an LLM call, and its injected `retrieve`
  special node queries the (possibly rephrased) member question — not a
  slot-filled search template. The clarifying-question loop, the
  refine-vs-generate routing, and the verbatim "ask" step are simply not
  expressible. It also lands the flow on the wrong engine (the story asks
  for *generic*) and drags in `expert`'s full retrieval pipeline (routing,
  hybrid fusion, re-ranking, hierarchy) that the workshop flow neither needs
  nor wants.
- **Option 3 — extend `PromptGraph` with declarative conditional edges and
  typed `retrieve`/`echo` nodes; wire an optional knowledge-store capability
  into `generic`.** Every construct the workshop flow needs becomes
  reusable configuration, on the engine the story names.

An unmerged local branch (`031-libra-flow-plugin`, one stale commit) had
already proven a *programmatic* `conditional_edges` compile parameter
compiles cleanly on the shared `PromptGraph`. This decision generalises that
into the JSON-declarative form the story asks for and does not depend on
that branch.

## Decision

**Option 3.** `PromptGraph` gains:

1. **Declarative conditional edges** — `{"from", "on", "map", "default"?}`
   in the edge list, parsed into a `ConditionalEdge` dataclass and compiled
   into a `StateGraph.add_conditional_edges` router closure. Routing value
   matching is a case-insensitive string form (covers booleans cleanly); a
   `None`/absent field never matches any key, including a literal `"none"`
   one, and takes the no-match path directly. A miss with no `default`
   raises `PromptGraphConfigError` naming the node, field, and a bounded
   form of the value.
2. **Type-keyed node dispatch** — `Node.type` (default `"llm"`) selects
   between the existing LLM-chain behaviour, a new `"retrieve"` node
   (single-pass, literal-value template fill against a host-injected
   retriever callback; FR-011's injection-hardening is load-bearing here),
   and a new `"echo"` node (verbatim state-field passthrough, zero LLM
   calls).
3. **An injected retriever, not a port.** `PromptGraph.compile()` gains an
   optional `retriever: Callable[[str, str, int], Awaitable[list[str]]]`
   parameter. The domain object never imports `KnowledgeStorePort` — the
   *plugin* owns the port, the factual-content filter, and the callback
   construction, exactly mirroring the seam `expert` already uses for its
   name-keyed `retrieve` special node.
4. **`generic` gains an optional `knowledge_store` dependency** and honours
   `event.prompt_graph` before its condensation step (the graph's own nodes
   consume the raw, bounded conversation — condensing it first would
   destroy multi-turn slot-filling).
5. **Name-keyed special nodes are checked before type dispatch.** This is
   the ordering choice that keeps `expert`'s existing behaviour byte-for-byte
   unchanged: a node literally named `"retrieve"` with no `type` field still
   resolves to `expert`'s special node, because the two mechanisms key on
   different fields entirely and the name check runs first.

A shipped, documented payload (`docs/prompt-graphs/workshop-design.json`,
`docs/prompt-graphs/README.md`) demonstrates the constructs by reproducing
the reference flow end to end, executed by tests loading that exact file.

## Alternatives considered

- **Option 1 (prompt-only, no engine change)** — rejected: loses the
  clarifying loop, the routing, and RAG entirely.
- **Option 2 (as above)** — rejected as the target; retained insight (the
  compile-time special-node injection is the right retrieval seam) is
  reused here.
- **Merging `031-libra-flow-plugin` directly** — rejected: that branch ships
  a standalone *plugin*, and the story asks for *configuration* on the
  existing generic engine. Its programmatic conditional-edges parameter is
  subsumed by the declarative JSON form here.

## Consequences

- Payload authors take on a real obligation: `state` must declare every
  field any node writes or any conditional edge routes on, or the value is
  silently dropped by LangGraph's own state-merge semantics. This is
  documented loudly in `docs/prompt-graphs/README.md` because there is no
  error for it — from the graph runtime's perspective, dropping an
  undeclared key is correct behaviour.
- A `generic` deployment that wants to run RAG-shaped payloads (like the
  workshop flow) now needs `VECTOR_DB_HOST`/`VECTOR_DB_PORT` and embeddings
  settings configured — the same environment `expert` already requires.
  `docker-compose.yaml`'s `generic:` service gained the same env passthrough
  block as `expert:` for local development parity.
- `expert`'s existing graph behaviour, and every pre-existing generic/expert
  test, is unaffected: the new branches in `compile()` are strictly
  additive, gated behind `Node.type` values `expert` never produces and a
  conditional-edges list that is empty unless a payload declares one.
- The `retrieve` node's factual-content metadata filter is engine-owned and
  not payload-configurable — a deliberate choice (see spec FR-002/A-005):
  exposing a raw `where` clause to payload authors would be an unnecessary
  injection surface with no story-driven need, and collections now hold
  derived summary entries the reference implementation's era did not have.

Link: workspace spec `workspace#052-libra-flow-config`.
