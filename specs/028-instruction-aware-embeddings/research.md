# Technical Research: Instruction-Aware Embeddings

**Branch**: `028-instruction-aware-embeddings` | **Date**: 2026-04-23

---

## Decision 1: Separate `embed()` vs `embed_query()` methods (not a flag parameter)

**Context**: Instruction-aware embedding models require different treatment for documents (plain embedding) versus queries (instruction-wrapped embedding). The question is how to expose this distinction in the port interface.

**Alternatives considered**:
- A) Single `embed(texts, is_query=False)` method with a boolean flag.
- B) Two separate methods: `embed(texts)` and `embed_query(texts)`.

**Decision**: Option B -- two separate methods on the `EmbeddingsPort` protocol.

**Rationale**:
- Clearer semantic intent at the call site: `embed_query()` makes it explicit that this is a retrieval operation.
- Avoids boolean-flag anti-pattern -- callers cannot accidentally forget the flag.
- Backward compatible: existing `embed()` callers (all ingest pipeline code) continue to work unchanged.
- Follows ISP (Interface Segregation): each method has a single, well-defined purpose.
- ChromaDB's `query()` is the only caller that needs `embed_query()`; all ingest code continues to use `embed()`.

**Trade-off**: Two methods instead of one increases the protocol surface, but the semantic clarity justifies it.

---

## Decision 2: Auto-detect by model name (not by provider)

**Context**: We need to determine when to apply instruction wrapping. Options include detecting by provider name, by model name, or requiring explicit configuration for every deployment.

**Decision**: Auto-detect based on model name prefix (`qwen3-embedding*`, case-insensitive).

**Rationale**:
- Model name is the most reliable signal: the instruction format is a property of the model, not the hosting provider. Qwen3-Embedding behaves the same whether served by Scaleway, vLLM, Ollama, or Together AI.
- Provider-based detection would be incorrect: Scaleway could host models that are not instruction-aware.
- Requiring explicit configuration for every deployment adds friction and configuration errors.
- Case-insensitive matching handles naming variations across providers (e.g., `qwen3-embedding-8b` vs `Qwen3-Embedding-0.6B`).

---

## Decision 3: Qwen3 retrieval instruction as a module-level constant

**Context**: The instruction prefix for Qwen3-Embedding retrieval queries is:
```text
Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:
```

**Decision**: Define `QWEN3_RETRIEVAL_INSTRUCTION` as a module-level constant in `openai_compatible_embeddings.py`.

**Rationale**:
- The instruction is stable across Qwen3-Embedding model variants (confirmed in model documentation).
- A constant is importable for testing (tests verify the exact prefix is applied).
- Keeping it in the adapter module (not in config or prompts) follows the principle that provider-specific behavior lives in adapters.
- If future Qwen3 variants need a different instruction, the constant can be updated in one place.

---

## Decision 4: Explicit override including empty string

**Context**: Operators may want to override the auto-detected instruction with a custom one, or disable wrapping entirely even for Qwen3 models.

**Decision**: The `query_instruction` parameter (and `EMBEDDINGS_QUERY_INSTRUCTION` env var) supports three states:
- `None` (not set): auto-detection applies.
- Non-empty string: used verbatim as the prefix.
- Empty string `""`: explicitly disables wrapping.

**Rationale**:
- `None` vs `""` distinction is deliberate: `None` means "I did not configure this, use defaults," while `""` means "I explicitly want no wrapping."
- This prevents operators from being locked into auto-detection when they know their Qwen3 deployment does not need wrapping (e.g., a fine-tuned variant with built-in instruction handling).
- The env var maps naturally: unset = `None`, set to empty = `""`, set to value = that value.

---

## Decision 5: `_call()` refactor in OpenAICompatibleEmbeddingsAdapter

**Context**: Before this change, `embed()` contained the full HTTP call logic (retry loop, httpx client, response parsing). Adding `embed_query()` would duplicate this code.

**Decision**: Extract the HTTP call logic into a private `_call(texts)` method. Both `embed()` and `embed_query()` delegate to `_call()`, with `embed_query()` prepending the instruction prefix before delegation.

**Rationale**:
- DRY: eliminates code duplication between `embed()` and `embed_query()`.
- `embed()` becomes a one-liner: `return await self._call(texts)`.
- `embed_query()` is a two-liner: prepend prefix, then `return await self._call(texts)`.
- The retry logic, HTTP configuration, and response parsing remain in one place.
- Future changes to the API call mechanism only need to be made in `_call()`.
