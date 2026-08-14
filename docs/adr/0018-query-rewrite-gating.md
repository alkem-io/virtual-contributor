# 18. Gate, validate and bound the query rewrite that already runs

Date: 2026-08-14

## Status

Accepted. Gating ships off by default (`QUERY_REWRITE_GATING_ENABLED=false`); output
validation and non-fatal failure are unconditional.

## Context

[vc#24](https://github.com/alkem-io/virtual-contributor/issues/24) asks to *add* pre-retrieval
query transformation, stating the pipeline "passes the raw user query directly to embedding
similarity search with no transformation".

That is not true of this codebase. `plugins/guidance` and `plugins/generic` both already send an
LLM condense call whenever the event carries history. Only `plugins/expert` matched the story.

What was missing is everything around it:

- **Ungated** — the condense fired on *any* history. Measured with a 250 ms stub: "yes",
  "thanks!" and "ok" each cost 2 LLM calls and ~500 ms, identical to a real question. The story's
  own speed constraint was already violated.
- **Unvalidated** — whatever the model returned became the retrieval query verbatim.
- **Fatal** — one raised exception aborted the whole request.
- **Unbounded** — the prompt embedded the entire conversation. `history_length` has existed in
  config since before this feature and is read by no code at all.

## Decision

**Gate, validate and bound the existing rewrite rather than adding another; extend it to expert.**

### The gate skips conversational turns only — never "simple" ones

The story recommends skipping transformation for simple queries. Implemented literally that
silently breaks anaphoric follow-ups: measured against the shipped classifier, 9 of 12 —
"show me those", "who is he", "and after that?" — classify SIMPLE yet are meaningless without the
preceding turn. Skipping them sends an unresolved fragment to the vector store with no error.

Conversational is the safe boundary because the classifier requires the *whole* message to be
small talk. Even there, acknowledgements (`ok`, `okay`, `alright`, `will do`) are held back: after
*"Shall I list the subspaces and their leads?"*, "ok" means *do it*. The classifier already
excludes bare `yes`/`no`/`sure` on exactly this reasoning and simply does not extend it.

### Validation is length and type, not meaning

A rewrite is rejected when it is empty, not a string, or longer than
`max(8.0 × len(original), 120)`. The absolute floor exists because a pure ratio punishes the
queries that most need resolving — `"who is he?"` is 10 chars and its correct resolution is 47.

**A short refusal is not caught.** `"I cannot help with that."` passes and becomes the retrieval
query. No length rule separates it from `"Who is the lead of Space Alpha?"`; that needs semantics,
i.e. another model call — the cost this feature removes. The consequence is confined to one turn.

### No binding to the unmerged classifier

This defines its own one-method `RewritePolicy`; only `main.py` reaches for the real classifier,
inside a guarded `try/except ImportError`. The ten open PRs on this repo produce 86 conflict hunks
when merged in sequence, so binding to one would make this hostage to an order nobody controls.

## Privacy and data protection

**The expert simple-RAG path now sends conversation history to the configured LLM provider where
it previously sent none.** This is a new egress across the platform boundary and is recorded here
deliberately rather than left implicit:

- On `develop`, `_handle_simple` sent only the current message; history never left.
- On this branch it also sends the trailing turns in the condense prompt.
- Expert VCs are space-scoped, and `getLastNInteractionMessages` sets `includeEntityContents=true`
  for EXPERT, so callout and post descriptions are prepended to that history.
- The graph path is unaffected — it already built `messages`/`conversation` from history.

The provider is the same third party that already generates every answer (Mistral/Scaleway), so
this widens *what* is sent on one path, not *to whom*. **Confirm the VC data-processing basis
covers it before enabling on production personas.**

Bounded by turn count (20) *and* characters (12 000, oldest evicted first): 20 turns at the
platform's own message cap would otherwise be ~656 000 chars — ~164 000 tokens — re-sent every turn.

### What the rewrite cannot influence

The member controls both message and history, so the rewrite is untrusted by construction. It
changes *what* is searched for, never *where*: the collection derives from the event
(`f"{bok_id}-knowledge"`), never from query text. Verified by driving a fully attacker-controlled
rewrite through expert — the query changed, the collection did not. Pinned as a test.

Logs carry `error_type` only. An exception body can quote the prompt, which carries the member's
conversation, and logs reach central logging readable by log access rather than space membership.

## Consequences

- A conversational turn costs one LLM call instead of two, once gating is enabled.
- A degenerate or failed rewrite can no longer cost anyone their answer.
- Expert resolves follow-ups at all, via the dormant `rephrased_question` seam. The resolved
  question is passed through a closure rather than state alone, because the graph schema is
  caller-supplied and LangGraph drops undeclared keys — a graph omitting that key would otherwise
  pay for the rewrite and discard it.
- `QUERY_REWRITE_MAX_EXPANSION_RATIO` must be finite and in `(1.0, 100.0]`; `inf`/`nan` previously
  passed validation and silently disabled the bound.
- **AC#4 of the story is unsatisfiable.** There is no local LLM and no GPU; every provider is
  third-party HTTP. The honest claim is that this adds no new external *call* and removes some.
- **AC#5 is out of scope.** `evaluation/pipeline_invoker.py` needs a live populated ChromaDB and a
  RAGAS LLM judge, so retrieval recall cannot be measured in CI.
