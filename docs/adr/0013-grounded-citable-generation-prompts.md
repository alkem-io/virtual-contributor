# ADR 0013: Grounded, Citable Generation Prompts

## Status

Accepted

## Context

Retrieval-backed answers could fill gaps with plausible information and gave
readers no way to connect a claim to the passage the model received. The two
repository-owned answering prompts also needed a bounded way to encourage
complete answers to comparative or multi-part questions, without adding a
model-routing call. Operators needed an answering-specific temperature control
without silently changing the global model setting used by ingest and
summarization.

## Decision

Render every surviving retrieved passage through one shared formatter in
`core/domain/prompts_shared.py`. Each block has a dense 1-based document number,
an identity derived only from existing metadata, optional kind/origin fields,
and verbatim content. The empty case uses an explicit sentinel. The same module
owns additive grounding, decline, citation, and private-reasoning instruction
blocks so that document labels and `[Document N]` citations cannot drift.

Bound the citable set by count, not by appearance. Passage bodies are rendered
verbatim and are untrusted, so a body may itself contain header-like text such
as `[Document 99]`. "Cite only numbers that appear in the supplied context" is
therefore not a sufficient rule. Each answering prompt additionally states the
exact supplied range (`[Document 1]` through `[Document N]`, where N is the
number of blocks actually rendered), declares that a label is only the bracketed
header opening a block, and forbids citing bracketed text found inside a passage
body. With no documents, the prompt forbids citing any number at all.

Keep the platform response envelope unchanged. Inline document citations are
only part of answer text seen by the reader/model; `sources[]`, its attributes,
ordering, and expert-origin de-duplication remain intact. Consequently, a
document number identifies a supplied passage, not an index into `sources[]`.

Use a pure lexical/structural complexity classifier. Any comparative/analytical
cue, multiple-ask signal, or question longer than 24 words triggers a private
step-by-step instruction. `ANSWERING_CHAIN_OF_THOUGHT_ENABLED` defaults to true
and bypasses the classifier entirely when false.
The cue and interrogative token lists are intentionally English-only; fullwidth
`？` still contributes to the language-independent multiple-question signal.

Use an opt-in `ANSWERING_LLM_TEMPERATURE` setting, defaulting to unset and
validated from 0.0 to 2.0. Pass it only as a per-call override at the guidance
and expert simple-RAG answering calls; do not mutate the shared
`LangChainLLMAdapter` or global `LLM_TEMPERATURE`.

## Prompt ownership boundary

Platform-supplied expert PromptGraph node prompts are not edited in this
repository. The shared formatter still reaches those prompts through the
injected retrieval node, so graph answers receive labelled context, but their
faithfulness/citation/reasoning instructions remain platform-owned.

## Consequences

- Answers have a common, checkable document-citation convention without a
  platform contract change.
- The citable range is stated as a bounded count, so a citation can be
  validated against the documents actually supplied rather than against
  whatever bracketed text an indexed passage happens to contain.
- No fabricated hierarchy is emitted: labels use title, type, URI, and source
  only when the indexed metadata supplies them.
- Context budgets charge rendered label UTF-8 bytes alongside passage content,
  so labels can affect which passages survive but cannot bypass the limit.
- The guidance JSON answer contract remains additive and parse-compatible.
- The complexity heuristic may over-classify some questions, trading at most a
  longer internal answer path for fewer missed multi-part answers.
- Non-English lexical cues remain outside this heuristic's scope; only repeated
  ASCII or fullwidth question marks are recognized independently of English.
- Operators can opt into a low factual-answering temperature (recommended
  0.0–0.3) without changing summarization or ingest behavior.
