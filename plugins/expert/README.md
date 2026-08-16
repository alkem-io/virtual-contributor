# Expert Plugin

PromptGraph-based plugin with single-collection RAG retrieval for knowledge-grounded Q&A.

Hierarchy is opt-in. Only a nonempty scoped Stage-2 result supplies PromptGraph
sources; feature-off and all flat fallbacks retain empty graph sources. Legacy
metadata retains its frozen rendering behavior, while hierarchy display names
alone are UTF-8/control-character hardened. Compatible Chroma stores open one
request-local embedding scope around Stage 1 and Stage 2/fallback. Provider
tasks own successful cache publication and terminal eviction, so waiter
cancellation cannot evict live work or create a duplicate. Typed embedding errors bypass flat
fallback and RabbitMQ redelivery; external error delivery is generic and safe.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `expert` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-expert` |
| **Ports** | `LLMPort`, `KnowledgeStorePort` |

## How It Works

The expert plugin supports two execution modes:

### PromptGraph mode (primary)
When the incoming event includes a `prompt_graph` definition, the plugin compiles a LangGraph workflow from JSON. Graph nodes have prompt templates, input variables, and optional Pydantic output schemas. A special **retrieve** node is injected that queries the knowledge store and formats results as labelled document blocks.

### Simple RAG mode (fallback)
When no graph is defined, falls back to direct knowledge retrieval + LLM invocation with the same score filtering and context budget enforcement.

## Retrieval Pipeline

```
Query → KnowledgeStore.query(collection, message, n_results, where=FACTUAL_WHERE)
  → Filter by score threshold (default 0.3)
  → Sort by score descending
  → Enforce context budget (default 20,000 chars, drop lowest-scoring first)
  → Format as 1-based labelled document blocks
  → LLM invocation with context
  → Extract sources from metadata → Response
```

Factual retrieval uses the shared legacy-safe `FACTUAL_WHERE` predicate from
`core.domain.retrieval_filters`, excluding summaries while retaining unmarked
legacy content. `SUMMARIES_WHERE` remains available for explicit overview retrieval.

### Optional two-stage hierarchy retrieval

With `EXPERT_HIERARCHICAL_RETRIEVAL_ENABLED=false` (the default), Expert makes
the current single flat retrieval call. When enabled, every eligible request
runs one dense Stage-1 routing query over overview/summary entries; there is no
permanent collection capability cache. Specific subspace routes dominate root
routes, and root-only routing is deliberately unscopable, so it uses flat
retrieval rather than widening to a root scope.

Stage 2 applies the current hybrid/rerank/threshold/top-K/budget path to detail
in the selected specific branches. A nonempty scoped result is retained even if
short: there is no unscoped sibling backfill. No usable route, an empty scoped
result, or a hierarchy-stage failure leaves the hierarchy handler before exactly
one flat attempt. A flat-path error is not hidden or retried by hierarchy logic.

`EXPERT_HIERARCHY_DISPLAY_NAMES_ENABLED=false` by default and is independent
of retrieval. When allowed, labels use only sanitized display names; they are
rendered before context-budget eviction, and their model-visible bytes plus the
exact shared inter-block separator are charged before rows are dropped. With disclosure disabled or names unavailable,
the hierarchy segment is omitted. Setting hierarchy retrieval to `false`
restores flat retrieval; setting display names to `false` independently omits
model-visible names while scoped retrieval remains available.

Provider processing/minimization approval is a human `RG-05P` gate before
display names may be enabled; this code does not grant or imply that approval.
`RG-05` is the representative paired flat/on RAGAS gate. Its production and
evaluation runs use the same deeply immutable resolved v7 composition and an invariant plus
mode-bound full non-secret fingerprint. Comparison fails closed unless invariant
fingerprints are equal and both full fingerprints are present, recomputable from
the invariant plus mode, and different for flat versus hierarchical runs.
Evaluation case/dataset identity is `evaluation-case-identity/v1` and every
case/aggregate metric must be a finite value in inclusive `[0,1]`; successful
cases have exactly faithfulness, answer relevancy, context precision, and
context recall, and persist `evaluation-case-identity/v1`. The public Expert
identity is validated before provider/scorer/file work. `SC-009`
remains the full-suite regression gate, not an evaluation substitute. RG-05P,
RG-05, and RG-06 remain human gates; hierarchy and display names remain off by
default.

`published-unacked` forbids application-managed raw republish and same-callback
rerun; ambiguous ACK may still broker-redeliver and does not promise exactly
once. Reject settlement faults log type only. All hierarchy controls remain
default-off and RG-05P/RG-05/RG-06 stay human gates.

The remediation is evidence for the pending review sequence only: round 05 is
gated independently and rounds 06–07 are contingent human reviews. It does not
authorize approval, enablement, deployment, or corpus mutation.

## Grounded, citable answers

Every surviving retrieved passage is presented to the model as a separate block:

```text
[Document 1 · Document title · callout · origin: https://example.org/source]
<verbatim retrieved passage>
```

Numbers are 1-based and apply only to the documents supplied for that answer.
Labels use existing metadata only: title falls back to URI, source, then
`Untitled`; kind and origin are included when present. No space/subspace/callout
hierarchy is invented. The model is instructed to cite substantive claims as
`[Document N]` and never cite a number it did not receive. Because passage
bodies are verbatim and untrusted, the prompt also names the exact citable
range for that answer (`[Document 1]` through `[Document N]`) and states that
bracketed text *inside* a passage body is quoted content, not a citable label.
These inline
citations are LLM-visible answer text only: they are not positions in, and do
not change, the platform's structured `sources[]` list. Two expert passages
from one origin may therefore have two document numbers but one source entry.

The formatter applies to both simple RAG and PromptGraph retrieval. PromptGraph
node prompts themselves are platform-supplied and are deliberately not changed
here; only their retrieved context gains these labels.

The simple-RAG prompt also requires answers to use only the supplied context,
flag uncovered parts of a question, and decline when no material is retrieved.

### Conditional reasoning

`ANSWERING_CHAIN_OF_THOUGHT_ENABLED` defaults to `true`. When enabled, the
simple-RAG prompt asks the model to work privately through complex questions,
then return the finished answer without scratch work. A question is complex
when **any** of these inspectable signals applies:

- it includes a comparative or analytical cue: `compare`, `versus`/`vs`,
  `differ`/`difference`, `trade-off`, `pros and cons`, `analyse`/`analyze`,
  `evaluate`, `why`, or `which is better`;
- it has multiple asks (more than one `?`, or two interrogatives joined by
  `and` or `or`; fullwidth `？` is also counted); or
- it has more than 24 words.

Set `ANSWERING_CHAIN_OF_THOUGHT_ENABLED=false` to bypass the classifier and
use the straightforward path for every question.
The cue and interrogative-token lists are English-only; broader multilingual
cue routing is outside this plugin's scope.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERT_N_RESULTS` | `5` | Number of chunks to retrieve |
| `EXPERT_MIN_SCORE` | `0.3` | Minimum relevance score threshold |
| `EXPERT_HIERARCHICAL_RETRIEVAL_ENABLED` | `false` | Enable the opt-in overview/summary route and scoped detail stage |
| `EXPERT_HIERARCHY_MAX_BRANCHES` | `3` | Route cap; only `2` or `3` are valid settings |
| `EXPERT_HIERARCHY_DISPLAY_NAMES_ENABLED` | `false` | Separately enable sanitized display-name labels after RG-05P |
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |
| `EMBEDDINGS_QUERY_MAX_UTF8_BYTES` | `32768` | Startup-logged query byte cap |
| `QUERY_REWRITE_MAX_UTF8_BYTES` | `4096` | Startup-logged rewrite byte cap |
| `EMBEDDINGS_MAX_ATTEMPTS` | `3` | Startup-logged outer query attempts |
| `EMBEDDINGS_ATTEMPT_TIMEOUT_SECONDS` | `20` | Startup-logged query attempt timeout |
| `EMBEDDINGS_TOTAL_DEADLINE_SECONDS` | `45` | Startup-logged query total deadline |
| `ANSWERING_LLM_TEMPERATURE` | unset | Optional per-answer temperature, validated from `0.0` to `2.0` |
| `ANSWERING_CHAIN_OF_THOUGHT_ENABLED` | `true` | Enables conditional private reasoning for complex simple-RAG questions |

Per-plugin LLM overrides are supported via `EXPERT_LLM_*` prefix.

Before enabling this option in an environment, deploy it false, re-ingest the
target spaces so their entries carry overview and hierarchy metadata, then run
the paired flat/on RAGAS evaluation on one reviewed query set. The unit suite's
deterministic precision proxy is structural evidence only; it is not a live
context-precision result. `SUMMARIZE_ENABLED` is not changed by this feature.

For factual knowledge-base answering, use `ANSWERING_LLM_TEMPERATURE` in the
**0.0–0.3** range. Raising it can make wording more varied, but trades away
determinism and conservative, source-faithful answers. The setting is opt-in:
when unset, calls use the deployment's existing provider/default behavior.
It does not change `LLM_TEMPERATURE`, summarization, or ingest calls.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — graph and simple RAG execution, retrieval, source extraction |
| `prompts.py` | System prompt templates for RAG context formatting |

## Testing

```bash
poetry run pytest tests/plugins/test_expert.py
```

## Adaptive routing

When `ROUTING_ENABLED=true`, each question is classified before retrieval and
this plugin's retrieval width, score threshold and context budget come from the
matching profile instead of the configured constants.

| Route | Behaviour here |
|---|---|
| conversational | **no retrieval at all** — the store is not queried |
| simple | narrower retrieval than today |
| moderate | exactly today's behaviour (the fallback for unrecognised input) |
| complex | wider retrieval **and** a wider context budget |

**Off by default.** With routing disabled no classifier is injected and this
plugin takes its existing code path with its existing constants — that is the
rollback, and it is a config change rather than a deploy.

Classification is rule-based and in-process: no model, no network call,
sub-millisecond. See `docs/adr/0016-adaptive-query-routing.md` for why an LLM
classifier was rejected on arithmetic, and `README.md` for the settings.

Both retrieval sites route: `_handle_simple` and the `retrieve_node` closure
inside `_handle_with_graph`. The closure captures its settings from the
enclosing scope, so a change touching only one would leave graph-driven queries
on today's behaviour — covered by `tests/plugins/test_expert_routing.py`.
## Faithfulness validation

When `FAITHFULNESS_VALIDATION_ENABLED=true`, each generated answer is checked
against the context it was produced from, and a warning is logged when the
answer **asserts** something after retrieval returned **nothing**.

**Observation only** — the answer a member receives is never changed, delayed,
or withheld. Off by default; disabled, no validator is constructed at all.

See `docs/adr/0017-post-generation-faithfulness-validation.md` for why
word-overlap scoring was rejected (it cannot separate a fabrication from a
faithful paraphrase, and would flag every non-English answer).

Both generation paths are covered: `_handle_simple` and the graph path. The
graph path returns no sources by design, which is why the check keys off the
context string rather than `Response.sources` — a sources-keyed check would
flag every graph answer.
