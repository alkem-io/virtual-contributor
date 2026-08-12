# Expert Plugin

PromptGraph-based plugin with single-collection RAG retrieval for knowledge-grounded Q&A.

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
Query → KnowledgeStore.query(collection, message, n_results)
  → Filter by score threshold (default 0.3)
  → Sort by score descending
  → Enforce context budget (default 20,000 chars, drop lowest-scoring first)
  → Format as 1-based labelled document blocks
  → LLM invocation with context
  → Extract sources from metadata → Response
```


## Grounded, citable answers

Every surviving retrieved passage is presented to the model as a separate block:

```
[Document 1 · Document title · callout · origin: https://example.org/source]
<verbatim retrieved passage>
```

Numbers are 1-based and apply only to the documents supplied for that answer.
Labels use existing metadata only: title falls back to URI, source, then
`Untitled`; kind and origin are included when present. No space/subspace/callout
hierarchy is invented. The model is instructed to cite substantive claims as
`[Document N]` and never cite a number it did not receive. These inline
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
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |
| `ANSWERING_LLM_TEMPERATURE` | unset | Optional per-answer temperature, validated from `0.0` to `2.0` |
| `ANSWERING_CHAIN_OF_THOUGHT_ENABLED` | `true` | Enables conditional private reasoning for complex simple-RAG questions |

Per-plugin LLM overrides are supported via `EXPERT_LLM_*` prefix.

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
