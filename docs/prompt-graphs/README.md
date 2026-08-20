# Declarative prompt-graph payloads

This directory documents the JSON shape `core/domain/prompt_graph.py`
accepts on `Input.promptGraph`, and ships one worked example:
`workshop-design.json`, which reproduces the libra-flow workshop-design flow
purely as configuration on the `generic` engine.

The `expert` engine already executed a caller-supplied `promptGraph` before
this feature existed; everything below is additive on top of that. `generic`
gains the ability to execute one too.

## Envelope

```json
{
  "state":  { "type": "object", "properties": { "...": {} } },
  "nodes":  [ { } ],
  "edges":  [ { } ],
  "start":  "START",
  "end":    "END"
}
```

**The state-schema drop rule (read this first).** `state` MUST declare every
field any node writes or any conditional edge routes on. LangGraph silently
drops any key a node returns that the state schema does not declare — a
routed field that is never declared will always read as absent (`None`) at
the router, and a value a node "writes" but never declared will vanish. This
is the single most common way to author a broken payload; there is no error
for it, because from the graph runtime's point of view, dropping an
undeclared key is correct behaviour.

`state.properties` accepts either JSON-Schema dict form or the platform's
list form (`[{"name": ..., "type": ..., "optional": ...}, ...]`) — both are
normalised identically, unchanged from before this feature.

**Size limits.** `nodes` is capped at 50 entries and `edges` at 100 —
exceeding either is a `PromptGraphConfigError` at parse time, before any
node is compiled or any LLM/retrieve call is possible. Each node can be an
LLM or knowledge-store invocation, and a single LangGraph superstep can run
many nodes at once, so an unbounded payload would otherwise let one inbound
message trigger an unbounded burst of provider calls. Every existing
payload (the shipped `workshop-design.json`, expert's own graphs) is a
handful of nodes, well under the cap.

**Every node name must be unique.** A second node declaring an
already-used `name` is a `PromptGraphConfigError` at parse time, naming
the duplicate — it is never silently accepted as a replacement of the
earlier node (edges targeting that name would otherwise resolve to
whichever node happened to be declared last, with no report).

## Node types

Every node has a `type` field. It defaults to `"llm"` and may be omitted for
existing-shape LLM nodes — this is what makes every pre-existing payload
still valid.

### `llm` (default)

```json
{
  "name": "check_input",
  "input_variables": ["conversation"],
  "prompt": "…{conversation}…{format_instructions}",
  "output": { "type": "object", "properties": { "complete": {"type": "boolean"} }, "required": ["complete"] }
}
```

Unchanged behaviour: the prompt is filled from `input_variables` read out of
state, then piped through the LLM. With an `output` schema, the response is
parsed as structured JSON (with the repo's existing best-effort recovery on
parse failure) and the parsed fields are merged into state. Without
`output`, the node writes its raw text to `result`.

### `retrieve` (new)

```json
{
  "name": "load_bok",
  "type": "retrieve",
  "collection_template": "{bok_id}-knowledge",
  "query_template": "info about {topic}",
  "n_results": 10,
  "max_context_chars": 20000,
  "output_key": "knowledge_docs"
}
```

| Field | Required | Notes |
|---|---|---|
| `collection_template` | yes | may reference **only** `{bok_id}`, unmodified — the engine-seeded body-of-knowledge id; any other variable, or a format spec/conversion on `{bok_id}` itself (e.g. `{bok_id:.0}`, `{bok_id!r}`), is a configuration error at parse time (tenancy boundary, not a formatting concern). An auto-numbered positional field — a bare `{}` — is likewise rejected at parse time; only named `{variable}` references are supported. |
| `query_template` | yes | filled with state values, single pass. An auto-numbered positional field — a bare `{}` — is rejected at parse time, same as `collection_template`. |
| `n_results` | no (default `10`) | integer, **must be in `[1, 50]`** — out of range is a configuration error at parse time, never silently clamped |
| `max_context_chars` | no (default `20000`) | integer, **must be in `[1000, 120000]`** — out of range or wrong type is a configuration error at parse time, never silently clamped. Per-node override of the join budget below; the range keeps it a real budget (floor) and a real security control (ceiling), not an unbounded escape hatch. |
| `output_key` | no (default `"knowledge_docs"`) | where the joined document text is written |
| `input_variables` | no | accepted for documentation only — **not load-bearing**. Template variables are discovered by parsing `collection_template`/`query_template` themselves. |

Behaviour:

- Every `{variable}` in either template is resolved from the current flow
  state. A variable with no state value is a configuration error naming it.
- Both templates are filled in **one single pass** over literal state
  values. A state value's own content — including a member-typed `{brace}`
  or `%format%` sequence — is inserted as data and is never re-interpreted
  as template syntax. This matters: slot values in the workshop flow come
  from member chat, and a member typing `{bok_id}` in the conversation must
  retrieve the literal string `{bok_id}`, never the identifier's real value.
- Exactly one knowledge-store query runs per node execution. The engine
  applies its own factual-content metadata filter (excludes derived
  summaries) — this filter is **not** payload-configurable.
- Results are combined as a plain `"\n\n"` join of the returned document
  texts, in store order — no numbered blocks, no source labels, no
  score-threshold filtering. The join is budgeted at `max_context_chars`
  (default 20,000 characters, payload-settable per node in `[1000, 120000]`
  — see the field table above): trailing documents are dropped once the
  budget is spent, mirroring every other retrieval path in the repo
  (expert, guidance). A single document that alone exceeds the budget is
  still returned rather than dropped to empty. A truncation still drops
  the warning log line (node name + kept/dropped chunk counts) so it stays
  observable; widen `max_context_chars` on that node if the full result
  set should survive — e.g. the shipped `workshop-design.json` sets
  `max_context_chars: 95000` on both `retrieve_refine`/`retrieve_generate`
  so their `n_results: 10` result set fits whole at the **deployed** ingest
  chunk size (9,000 characters — `CHUNK_SIZE` in the infra-ops configMap,
  also `core/domain/routing.py` and `docs/adr/0016`), matching FR-002's
  "documents are used as returned".
- The collection actually queried is always derived server-side from
  `Input.bodyOfKnowledgeID` — never the payload's rendered
  `collection_template` value — closing the gap where a payload's own
  upstream nodes could otherwise overwrite the `bok_id` state value before
  the retrieve node runs.
- **An empty `Input.bodyOfKnowledgeID` with a `retrieve` node present is a
  configuration error**, raised before any node runs and before a
  collection name is even constructed. There is no shared/default
  collection fallback — a BoK-less persona whose payload contains a
  `retrieve` node cannot silently read a collection pooled across tenants.
  A payload with no `retrieve` node is unaffected.
- No matching documents → `output_key` is set to `""` and the flow
  continues; this is not an error.
- A store/embedding error propagates to the caller's standard error
  response — no answer is fabricated from a failed retrieval.
- **If the engine instance has no knowledge store configured at all**, a
  graph containing a `retrieve` node fails at compile time with a
  configuration error naming the requirement — it is never silently
  skipped.

### `echo` (new)

```json
{ "name": "ask", "type": "echo", "source": "question" }
```

Writes `{"result": str(state[source])}` verbatim. No LLM call is made.
Absent/`None` source values write `""`. Other falsy values (`0`, `False`,
`""`) write their exact string form — there is no falsy-collapse.

### Unknown `type`

A parse-time configuration error naming the node and the unrecognised value.

## Edge forms

### Plain (existing)

```json
{ "from": "extract", "to": "refine" }
```

### Conditional (new)

```json
{
  "from": "check_input",
  "on": "complete",
  "map": { "true": "analyse_last_message", "false": "ask" },
  "default": "ask"
}
```

| Field | Required | Notes |
|---|---|---|
| `from` | yes | source node name |
| `on` | yes | state field read at runtime |
| `map` | yes | `{value-string: target-node-or-"END"}`; keys are lower-cased at parse time |
| `default` | no | taken when the runtime value matches no key |

Behaviour:

- The runtime value of `on` is converted to a **case-insensitive string**
  and matched against `map`'s (already lower-cased) keys. A Python `True`
  matches the `"true"` key.
- A value that is `None` (field absent, or never written by an earlier
  node) never matches any key — including a literal `"none"` key — and goes
  straight to the no-match path.
- No match + `default` declared → routes to `default`.
- No match + no `default` → the request fails with a configuration error
  naming the source node, the field, and (a bounded form of) the value.
- `"END"` is a valid target in both `map` and `default`.
- A node that is the source of a conditional edge **never also follows a
  plain edge from that same source** — the conditional wins, and any plain
  edge with the same `from` is ignored. Author one or the other per source
  node, not both.
- Every source/target — conditional or plain — must name a declared node
  (or `START`/`END`). An unknown name is rejected when the graph is built,
  before any LLM call runs.

## Engine-seeded initial state (generic engine graph path)

When the `generic` engine executes a graph payload, it seeds:

| Key | Content |
|---|---|
| `messages` | the bounded trailing conversation turns (role/content) + the current message |
| `conversation` | the same turns joined as `"role:\ncontent"` blocks |
| `current_question` | the member's current message |
| `bok_id` | `Input.bodyOfKnowledgeID` (empty string if absent) |
| `description` | `Input.description` |
| `display_name` | `Input.displayName` |

History is bounded exactly as elsewhere in the engine — **it is not
condensed** before the graph runs. The flow's own nodes (an input-completion
check, a message-intent analysis, a design extractor in the workshop
payload) analyse the raw, bounded conversation themselves; condensing it
first would destroy the multi-turn slot-filling the workshop flow depends
on.

## Answer contract

The flow's final answer is read as `final_state["final_answer"]`, falling
back to `final_state["result"]`. Nodes without an `output` schema already
write `result`; the echo node writes `result` directly.

The response returned to the caller carries:

- `result` — the answer above
- `humanLanguage` — echoed from `Input.language`
- `resultLanguage` / `knowledgeLanguage` / `originalResult` — passed through
  from final state when the flow's own nodes wrote them (optional)
- `sources` — always `[]` on the generic graph path (no per-chunk source
  attribution; that remains an `expert`-engine concern)

## Invocation

Send an `Input` message to the deployment's generic-engine queue with:

| Field | Value |
|---|---|
| `engine` | the deployment's generic engine id |
| `userID` | required, no default — the platform always supplies this ahead of any configurator-authored payload; it is never something a configurator constructs by hand |
| `message` / `history` | the member conversation |
| `promptGraph` | the JSON payload (e.g. the contents of `workshop-design.json`) |
| `bodyOfKnowledgeID` | required for any payload using a `retrieve` node — an empty value with a `retrieve` node present is a configuration error raised before any node runs and before any collection name is constructed; there is no fallback shared collection. A payload with no `retrieve` node is unaffected by an absent `bodyOfKnowledgeID`. |
| `prompt` | unused on the graph path |

**Deployment prerequisite for `retrieve` nodes**: the generic engine
instance must have `VECTOR_DB_HOST`/`VECTOR_DB_PORT` (and embeddings
settings) configured — otherwise any payload with a `retrieve` node fails
loudly at compile time, per the table above. See `docker-compose.yaml`'s
`generic:` service for a local example.

## Authoring guide

- **Design each turn as acyclic.** A payload is compiled and run fresh for
  every member message; a multi-turn "loop" (e.g. asking for missing facts
  across several messages) happens naturally because the member's next
  message re-enters the graph at the start, not because the graph itself
  cycles. A graph that *is* accidentally cyclic (a conditional edge that can
  route back to an already-visited node under some condition) is not
  detected at parse or compile time — cycle detection would require
  analyzing routing values that only exist at run time. It is bounded, but
  by a deliberately small recursion ceiling this engine sets on every run
  (`_GRAPH_RECURSION_LIMIT` in `core/domain/prompt_graph.py`, currently 50),
  not by LangGraph's own default of 10007 — so a mis-authored cyclic graph
  fails in well under a second as a standard pipeline error instead of
  running for hours. Author acyclic graphs on purpose regardless.
- **Declare every state key you touch.** See the drop rule above; this is
  the single most common authoring mistake.
- **Prefer `default` on conditional edges whenever a structured-output
  model might emit a value outside your map.** Small models sometimes drop
  or mis-fill an auxiliary field; a `default` keeps the flow moving in a
  safe direction instead of failing the whole request.
- **`retrieve` node templates only ever see literal data.** Do not attempt
  to build a template *value* dynamically from another template — every
  template variable resolves to a plain state value, filled once.

## Workshop flow walkthrough

`workshop-design.json` reproduces libra-flow's behaviour:

```text
START → check_input ──(complete=false)──→ ask [echo question] → END
                    └─(complete=true)───→ analyse_last_message
                                            ├─(action=refine)──→ extract → retrieve_refine → refine → END
                                            └─(action=generate, or unmatched action)→ retrieve_generate → generate → END
```

1. **`check_input`** — an `llm` node with a structured `output` schema
   extracting the five workshop facts (`role`, `duration`, `workshop_type`,
   `purpose`, `audience_size`) plus a `question` and the required `complete`
   flag, from the whole bounded conversation.
2. **Conditional edge on `complete`** — `false` routes to `ask`; `true`
   routes to `analyse_last_message`.
3. **`ask`** — an `echo` node returning `question` verbatim. No knowledge is
   retrieved and no further LLM call is made on this path (US2-AS1).
4. **`analyse_last_message`** — an `llm` node classifying the member's last
   message as `refine` or `generate`. The conditional edge's `default`
   targets `retrieve_generate` — the entry to the generate path — so a
   model that emits neither value still produces a fresh, grounded design
   rather than dead-ending a complete conversation (a deliberate,
   documented deviation from the reference implementation, which crashed on
   an out-of-set action).
5. **Refine path**: `extract` (an `llm` node pulling the existing design out
   of the conversation) → `retrieve_refine` (a `retrieve` node querying
   `{bok_id}-knowledge` with the slot-filled Liberating-Structures search
   text) → `refine` (an `llm` node revising the design per the member's
   request, grounded in the retrieved knowledge).
6. **Generate path**: `retrieve_generate` (the same retrieve shape) →
   `generate` (an `llm` node producing a brand-new design grounded only in
   the retrieved knowledge).

Every node type, edge form, and behaviour in this walkthrough is backed by a
named passing test in `tests/core/domain/test_prompt_graph_conditional.py`,
`tests/core/domain/test_prompt_graph_typed_nodes.py`, and
`tests/plugins/test_workshop_payload.py`.
