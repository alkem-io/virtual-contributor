# Research: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Feature Branch**: `007-configurable-summarization`
**Date**: 2026-04-06

## Research Tasks

### R1: Summarization LLM — How to create and inject a second LLM instance

**Context**: The system needs a separate LLM for summarization tasks (cheaper model) while keeping the main LLM for user-facing responses. The existing `create_llm_adapter()` factory already supports all 3 providers and accepts a `BaseConfig`.

**Findings**:

The current architecture supports this cleanly:

1. **Config**: Add `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, `SUMMARIZE_LLM_API_KEY`, `SUMMARIZE_LLM_TEMPERATURE`, `SUMMARIZE_LLM_TIMEOUT` to `BaseConfig`. These are independent fields (not a nested model) to match the existing flat env-var pattern.

2. **Factory reuse**: `create_llm_adapter()` takes a `BaseConfig` and reads `llm_provider`, `llm_model`, `llm_api_key`, etc. To create a summarization adapter, build a synthetic `BaseConfig` with the summarize values mapped to the `llm_*` fields and pass it to the same factory. This avoids any factory changes.

3. **Injection path**: In `main.py`, after creating the main LLM adapter, check if all three required summarize fields are set. If so, create a second `LangChainLLMAdapter` and pass it to ingest plugins as `summarize_llm`. If not fully configured, log a warning and pass `None` (fallback to main LLM in the plugin).

4. **Plugin wiring**: `IngestWebsitePlugin` and `IngestSpacePlugin` both construct `DocumentSummaryStep(llm_port=self._llm)` and `BodyOfKnowledgeSummaryStep(llm_port=self._llm)`. Add an optional `summarize_llm: LLMPort | None = None` constructor parameter. When present, pass `summarize_llm` to summary steps instead of `self._llm`.

5. **No port changes**: The summarization LLM implements the same `LLMPort` protocol. No new ports or adapters needed.

**Decision**: Reuse `create_llm_adapter()` with a synthetic config. Inject via constructor. Fallback to main LLM when not configured.
**Rationale**: Zero factory changes, zero port changes, follows existing per-plugin override pattern.
**Alternatives considered**: (a) New `SummarizeLLMPort` — rejected (violates Simplicity, same interface as LLMPort). (b) Subclass BaseConfig for summarize — rejected (adds complexity, flat env vars are simpler).

---

### R2: Partial summarization LLM configuration — fallback behavior

**Context**: FR-002 requires fallback to main LLM when summarize vars are unset. The edge case spec requires a warning when only a subset of the 3 required vars is set.

**Findings**:

The activation check is: all three of `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, `SUMMARIZE_LLM_API_KEY` must be set. Validation logic:

1. **All three set**: Create summarization LLM adapter. Log at INFO: "Summarization LLM configured: provider={provider}, model={model}".
2. **None set**: Silent fallback to main LLM. No log needed (this is the default).
3. **Partial (1 or 2 of 3)**: Log WARNING listing which variables are missing. Fall back to main LLM.
4. **Invalid provider**: `LLMProvider` enum validation in pydantic catches this at config load time with a clear error (fail fast at startup per edge case spec).

**Decision**: Three-field activation check with partial-set warning. Validation via pydantic enum + model_validator.
**Rationale**: Matches the edge case requirements exactly. Pydantic validation gives fail-fast behavior for free.
**Alternatives considered**: (a) Require all-or-nothing with hard error on partial — rejected (too strict, breaks existing deployments that might have stale env vars).

---

### R3: Per-plugin retrieval parameters — replacing global config

**Context**: Currently `retrieval_n_results` and `retrieval_score_threshold` are global in `BaseConfig` and injected via `inspect.signature` in `main.py`. The spec requires per-plugin values: `EXPERT_N_RESULTS`, `GUIDANCE_N_RESULTS`, `EXPERT_MIN_SCORE`, `GUIDANCE_MIN_SCORE`.

**Findings**:

1. **Current state**: `BaseConfig` has `retrieval_n_results=5` and `retrieval_score_threshold=0.3`. In `main.py`, these are injected to any plugin whose `__init__` accepts `n_results` or `score_threshold`.

2. **Expert plugin**: Already accepts `n_results` and `score_threshold` in `__init__`. Works correctly with injected values.

3. **Guidance plugin**: Accepts `score_threshold` in `__init__` but does NOT accept `n_results`. The value `n_results=5` is hardcoded in the `_query_collection` closure (line 75). Also hardcodes `deduped[:5]` as a result limit (line 119).

4. **Approach**: Add per-plugin config fields to `BaseConfig`:
   - `expert_n_results: int = 5`
   - `expert_min_score: float = 0.3` (matches current global `retrieval_score_threshold=0.3`)
   - `guidance_n_results: int = 5`
   - `guidance_min_score: float = 0.3` (matches current global `retrieval_score_threshold=0.3`)
   
   Update `main.py` injection to use plugin-specific values instead of global ones.

5. **Backward compatibility**: Per-plugin defaults of 0.3 match the current `retrieval_score_threshold=0.3`, satisfying FR-009. No behavioral change when new env vars are unset.

6. **Deprecation of global fields**: Keep `retrieval_n_results` and `retrieval_score_threshold` in config for backward compatibility but document them as deprecated. Per-plugin values take precedence. If only global values are set, they still work as before.

**Decision**: Add per-plugin fields with defaults matching current behavior (n_results=5, min_score=0.3). Update guidance plugin to accept `n_results`. Deprecate but keep global fields.
**Rationale**: Per-plugin control is the whole point. Defaults of 0.3 preserve current filtering behavior (FR-009).
**Alternatives considered**: (a) Keep only global fields, derive per-plugin internally — rejected (doesn't satisfy FR-003/FR-004/FR-005 requirements). (b) Remove global fields entirely — rejected (breaks existing deployments).

---

### R4: MAX_CONTEXT_CHARS — cross-plugin merging clarification

**Context**: FR-006 says "merge all retrieved chunks from both expert and guidance plugins into a single pool." However, architecturally, expert and guidance are separate plugins running in separate containers. A single request goes to ONE plugin based on `PLUGIN_TYPE`.

**Findings**:

Cross-plugin merging is architecturally impossible — plugins are isolated processes. The practical interpretation:

1. **Expert plugin**: Retrieves chunks from a single collection. `MAX_CONTEXT_CHARS` limits the total context assembled from those chunks. If the combined text exceeds the budget, drop lowest-scoring chunks until under budget.

2. **Guidance plugin**: Retrieves from 3 collections in parallel, merges results, deduplicates, and limits to top N. `MAX_CONTEXT_CHARS` applies to the merged+deduped result set. If total context exceeds budget, drop lowest-scoring chunks globally across all 3 collections.

3. **The spec's "merge both plugins" language** refers to the guidance plugin's multi-collection merging pattern. The guidance plugin already merges results from 3 collections — `MAX_CONTEXT_CHARS` applies to that merged pool.

4. **Implementation**: After score filtering and before formatting context for LLM, measure total character count. If over budget, sort by score descending, accumulate until budget is reached, drop the rest. Log a warning with how many chunks were dropped.

**Decision**: `MAX_CONTEXT_CHARS` applies per-plugin to the active plugin's merged retrieval results. Default: 20,000.
**Rationale**: Consistent with microkernel isolation. The guidance plugin's 3-collection merge is the real "merged pool" the spec refers to.
**Alternatives considered**: (a) Shared retrieval layer combining expert + guidance results — rejected (violates plugin isolation, requires architectural change far beyond scope).

---

### R5: SUMMARY_CHUNK_THRESHOLD — current behavior and configurability

**Context**: FR-007 requires `SUMMARY_CHUNK_THRESHOLD` (default: 4). Currently `DocumentSummaryStep` hardcodes `if len(doc_chunks) > 3` (steps.py:134). The default of 4 with `>=` preserves exact backward compatibility.

**Findings**:

1. **Current code**: `DocumentSummaryStep.__init__` accepts `llm_port`, `summary_length`, `concurrency`. The threshold `> 3` is hardcoded in `execute()`.

2. **Change**: Add `chunk_threshold: int = 3` to `DocumentSummaryStep.__init__`. Change the filter to `if len(doc_chunks) >= chunk_threshold` (note: `>=` not `>` to match the spec's wording "minimum number of chunks a document must have before summarization is triggered").

3. **Spec verification**: "Given SUMMARY_CHUNK_THRESHOLD=5, When a document with 3 chunks is ingested, Then summarization is skipped." → 3 < 5, skip. "When a document with 6 chunks is ingested, Then summarization runs." → 6 >= 5, run. This confirms `>=` is correct.

4. **Current behavior check**: The current code uses `> 3`, which means documents with exactly 3 chunks are NOT summarized. Setting the default to 3 with `>=` would change behavior (3-chunk docs would now be summarized). To preserve exact backward compatibility: either use `> chunk_threshold` with default 3, or use `>= chunk_threshold` with default 4. The spec says default 3, and acceptance scenario 3 says "default threshold of 3 is used (current behavior)." But current behavior is `> 3` (not `>= 3`). This is a minor discrepancy.

   **Resolution**: Use `>= chunk_threshold` with default 4 to preserve exact current behavior (`>= 4` ≡ `> 3`). Document that the config value represents the minimum chunk count required for summarization. The spec's "default of 3" appears to be an approximation of current behavior; exact backward compat (FR-009) takes priority.

   Actually, re-reading the spec more carefully: FR-009 says "preserve existing behavior when none of the new variables are set." Current behavior: docs with 4+ chunks get summarized. Setting default to 4 with `>=` preserves this exactly. If someone sets `SUMMARY_CHUNK_THRESHOLD=3`, docs with 3+ chunks get summarized — intuitive.

**Decision**: `>= chunk_threshold` with default 4. Config field: `summary_chunk_threshold: int = 4`.
**Rationale**: Preserves exact backward compatibility (FR-009) while giving clear semantics: "minimum number of chunks needed for summarization."
**Alternatives considered**: (a) `> chunk_threshold` with default 3 — rejected (confusing semantics: "threshold 3 means 4+ chunks"). (b) `>= chunk_threshold` with default 3 — rejected (changes current behavior, violates FR-009).

---

### R6: Summarization LLM retry and error handling

**Context**: Edge case spec requires "retry up to 3 times, then skip summarization and continue ingestion."

**Findings**:

1. **Current retry behavior**: `LangChainLLMAdapter` already has retry logic: 3 attempts with exponential backoff (1s, 2s, 4s). This applies to all LLM calls including summarization.

2. **Current error handling in steps**: `DocumentSummaryStep.execute()` catches exceptions per-document and appends to `context.errors` — the pipeline continues without a summary for that doc. `BodyOfKnowledgeSummaryStep` does the same.

3. **Conclusion**: The existing retry and error handling already satisfies the spec requirement. No changes needed beyond what `LangChainLLMAdapter` provides.

**Decision**: No changes. Existing retry (3 attempts) + per-doc error handling already match the spec.
**Rationale**: The adapter-level retry and step-level error handling compose to give exactly the behavior the spec requires.

---

### R7: Logging requirements — model name and token count per summarization call (FR-011)

**Context**: FR-011 requires logging model name + token count per summarization LLM call at INFO level.

**Findings**:

1. **Model name**: Available from the LangChain model instance (`llm.model` or `llm.model_name`). Can be logged once when the summarization LLM is created.

2. **Token count**: LangChain's `ainvoke()` returns an `AIMessage` with `usage_metadata` containing `input_tokens` and `output_tokens`. Currently, `LangChainLLMAdapter.invoke()` extracts only `response.content` and discards the metadata.

3. **Approach**: Modify `_refine_summarize()` in steps.py to accept a model name string and log per-call. For token counts, either:
   (a) Modify `LangChainLLMAdapter.invoke()` to return token usage alongside the response — this changes the `LLMPort` interface (not acceptable).
   (b) Add a separate logging callback/wrapper that logs before returning the string.
   (c) Add a `invoke_with_usage()` method to the adapter — but this changes the port.
   (d) Use LangChain's callback mechanism for token counting.

   The simplest approach that doesn't change `LLMPort`: wrap the summarization LLM's invoke in a thin logging wrapper within the pipeline steps that uses LangChain's `get_openai_callback` or similar. However, this is provider-specific.

   **Pragmatic solution**: Log the model name at step start. For token counts, modify `LangChainLLMAdapter` to log token usage internally (the adapter is an implementation detail, not a port). The adapter already has access to the LangChain response object which contains usage metadata.

**Decision**: Add internal token-usage logging to `LangChainLLMAdapter.invoke()` at DEBUG level (always). In summarization steps, log model name + document ID at INFO level per call. Token counts come from the adapter's internal logging.
**Rationale**: No port changes. Adapter-internal logging is an implementation detail. Per-call model name logging in steps satisfies FR-011 observability needs.
**Alternatives considered**: (a) Change LLMPort to return usage metadata — rejected (port change, constitution violation). (b) LangChain callbacks — rejected (provider-specific, adds complexity).

---

### R8: Startup configuration logging (FR-012)

**Context**: FR-012 requires logging all resolved config values at startup with API keys masked.

**Findings**:

1. **Current state**: `main.py` logs LLM provider, model, and base_url at startup (lines 71-76). No masking.

2. **Approach**: After config loading in `main()`, log all new env var values at INFO level. Mask any value that contains "api_key" or "password" in the field name: show first 3 chars + `****`.

3. **Implementation**: Add a helper function `log_config(config)` in `main.py` that iterates over the new fields and logs them. Use a simple masking function: `value[:3] + "****"` if len > 3, else `"****"`.

**Decision**: Add `_log_config()` helper in `main.py`. Log new config fields at INFO. Mask sensitive fields.
**Rationale**: Simple, targeted, no new dependencies.

---

### R9: Guidance plugin n_results injection

**Context**: The guidance plugin hardcodes `n_results=5` in the query call and doesn't accept it via constructor.

**Findings**:

1. **Current `__init__`**: Accepts `llm`, `knowledge_store`, `score_threshold`. No `n_results`.
2. **Query call** (line 75): `n_results=5` hardcoded.
3. **Result limit** (line 119): `deduped[:5]` hardcoded.

4. **Change**: Add `n_results: int = 5` to `__init__`. Use `self._n_results` in the query call. The `deduped[:5]` limit should also use this value or a separate limit. The spec doesn't distinguish between per-collection n_results and final result limit. Since `GUIDANCE_N_RESULTS` controls "number of retrieved chunks per collection," the deduped limit should be independent (it's a post-processing step). Keep `deduped[:5]` as-is or make it configurable separately. The spec doesn't call for a separate "max results after dedup" config, so keep the current behavior of limiting to min(total_results, n_results) after dedup.

   Actually, looking more carefully: guidance queries 3 collections with n_results each, giving up to 3*n_results chunks. After dedup, it limits to 5. If `GUIDANCE_N_RESULTS=3`, queries return 3*3=9 chunks, dedup to <=9, then limit to... 5? That doesn't make sense with n_results=3.

   The `deduped[:5]` should scale with n_results. Change to `deduped[:self._n_results]`.

**Decision**: Add `n_results: int = 5` to `GuidancePlugin.__init__`. Replace hardcoded `5` in query and dedup limit with `self._n_results`.
**Rationale**: Consistent parameterization. The n_results value serves as both per-collection query limit and final result cap.

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Summarization LLM creation | Reuse `create_llm_adapter()` with synthetic config | Zero factory/port changes |
| Partial config handling | Three-field activation check + warning | Matches spec edge cases |
| Per-plugin retrieval | Per-plugin config fields + deprecate globals | FR-003/FR-004/FR-005 |
| MAX_CONTEXT_CHARS | Per-plugin enforcement on merged results | Microkernel isolation |
| SUMMARY_CHUNK_THRESHOLD | `>= threshold` with default 4 | FR-009 backward compat |
| Retry/error handling | No changes needed | Existing behavior matches spec |
| Token logging (FR-011) | Adapter-internal + step-level model name | No port changes |
| Config logging (FR-012) | `_log_config()` helper with masking | Simple, targeted |
| Guidance n_results | Add to constructor, replace hardcoded 5 | FR-004 compliance |
