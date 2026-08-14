# Guidance Plugin

Multi-collection RAG that queries three Alkemio knowledge bases in parallel for platform guidance answers.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `guidance` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-guidance` |
| **Ports** | `LLMPort`, `KnowledgeStorePort` |

## How It Works

Queries three fixed knowledge collections in parallel, merges and deduplicates results, then invokes the LLM with scored context.

```
Query
  → Parallel query across 3 collections:
  │   ├── alkem.io-knowledge
  │   ├── welcome.alkem.io-knowledge
  │   └── www.alkemio.org-knowledge
  → Merge results
  → Deduplicate by source URL (keep highest score per page)
  → Filter by score threshold (default 0.3)
  → Enforce context budget (default 20,000 chars)
  → Format as 1-based labelled document blocks
  → LLM invocation (expects structured JSON response)
  → Parse JSON response → Extract answer + sources → Response
```

The LLM is prompted to respond in structured JSON format. The plugin parses JSON from the response, handling fenced code blocks, bare objects, and preamble/trailing text.

Each factual collection query uses `FACTUAL_WHERE` from
`core.domain.retrieval_filters`, so summaries do not consume retrieval slots
while unmarked legacy content remains eligible.

## Grounded, citable answers

Every surviving retrieved passage is supplied as an independently delimited
block, for example:

```text
[Document 1 · Document title · callout · origin: https://example.org/source]
<verbatim retrieved passage>
```

Document numbers are 1-based for each question. Labels use only existing
metadata: title falls back to URI, source, then `Untitled`; kind and origin are
included only when available. The plugin never fabricates a space/subspace/
callout hierarchy. The model is instructed to support substantive claims with
`[Document N]` citations and to cite only numbers in the supplied context.
Because passage bodies are verbatim and untrusted, the prompt also names the
exact citable range for that answer (`[Document 1]` through `[Document N]`) and
states that bracketed text *inside* a passage body is quoted content, not a
citable label.
Those markers are LLM-visible answer text; the structured platform `sources[]`
envelope, including its source population, is unchanged.

The answer prompt requires material-only answers, an explicit statement of any
uncovered part of a question, and a decline when no retrieved material survives.
Its existing JSON contract remains intact: responses still contain `answer` and
`sources` keys, and retrieved metadata remains the source of the returned
`sources[]` envelope.

### Conditional reasoning

`ANSWERING_CHAIN_OF_THOUGHT_ENABLED` defaults to `true`. It adds a private
step-by-step instruction only when **any** inspectable complexity signal fires:

- a comparative/analytical cue (`compare`, `versus`/`vs`, `differ`/
  `difference`, `trade-off`, `pros and cons`, `analyse`/`analyze`, `evaluate`,
  `why`, or `which is better`);
- multiple asks (more than one `?`, or two interrogatives joined by `and` or
  `or`; fullwidth `？` is also counted); or
- more than 24 words.

The finished answer never exposes intermediate reasoning. Set
`ANSWERING_CHAIN_OF_THOUGHT_ENABLED=false` to bypass classification and keep
all questions on the direct path.
The cue and interrogative-token lists are English-only; broader multilingual
cue routing is outside this plugin's scope.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GUIDANCE_N_RESULTS` | `5` | Number of chunks per collection |
| `GUIDANCE_MIN_SCORE` | `0.3` | Minimum relevance score threshold |
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |
| `ANSWERING_LLM_TEMPERATURE` | unset | Optional per-answer temperature, validated from `0.0` to `2.0` |
| `ANSWERING_CHAIN_OF_THOUGHT_ENABLED` | `true` | Enables conditional private reasoning for complex questions |

Per-plugin LLM overrides are supported via `GUIDANCE_LLM_*` prefix.

For factual answers, `ANSWERING_LLM_TEMPERATURE=0.0–0.3` is recommended.
Higher values increase wording variety but reduce determinism and can weaken
conservative source-grounded behavior. It is opt-in: leaving it unset preserves
the deployment's existing provider/default behavior and does not affect
`LLM_TEMPERATURE`, summarization, or ingest generation.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — parallel multi-collection query, dedup, JSON response parsing |
| `prompts.py` | System prompt with JSON response format instructions |

## Testing

```bash
poetry run pytest tests/plugins/test_guidance.py
```
