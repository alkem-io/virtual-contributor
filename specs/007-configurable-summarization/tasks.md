# Tasks: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Input**: Design documents from `/specs/007-configurable-summarization/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Included — required per constitution check (P4: Optimised Feedback Loops).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Config + Validation + Startup Logging)

**Purpose**: All new config fields, validation rules, and startup logging that MUST be in place before any user story work begins.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T001 Add all new config fields to BaseConfig in core/config.py: summarization LLM fields (summarize_llm_provider: LLMProvider | None = None, summarize_llm_model: str | None = None, summarize_llm_api_key: str | None = None, summarize_llm_temperature: float | None = None, summarize_llm_timeout: int | None = None), per-plugin retrieval fields (expert_n_results: int = 5, expert_min_score: float = 0.3, guidance_n_results: int = 5, guidance_min_score: float = 0.3), context budget (max_context_chars: int = 20000), and chunk threshold (summary_chunk_threshold: int = 4) with env var bindings per data-model.md
- [X] T002 Add model_validator to BaseConfig in core/config.py: validate summarize_llm_temperature range 0.0–2.0 when set, summarize_llm_timeout > 0 when set, expert_n_results and guidance_n_results > 0, expert_min_score and guidance_min_score 0.0–1.0, max_context_chars > 0 with warning if < 1000, summary_chunk_threshold > 0, and partial summarize config warning (1 or 2 of 3 required fields set) per data-model.md validation rules
- [X] T003 Add startup config logging helper in main.py: log all new config field values at INFO level after config loading, mask any field containing "api_key" (show first 3 chars + "****"), per FR-012

**Checkpoint**: Configuration foundation ready — user story implementation can now begin.

---

## Phase 2: User Story 1 — Reduce Summarization Costs with a Separate LLM (Priority: P1) MVP

**Goal**: Configure a separate, cheaper LLM for document and body-of-knowledge summarization to reduce ingestion costs by 5-10x without affecting user-facing response quality.

**Independent Test**: Deploy with `SUMMARIZE_LLM_PROVIDER=mistral`, `SUMMARIZE_LLM_MODEL=mistral-small-latest`, `SUMMARIZE_LLM_API_KEY=<key>`. Ingest a space and verify summaries use the configured summarization model while user-facing responses continue to use the main model.

### Tests for User Story 1

- [X] T004 [P] [US1] Write tests for summarization LLM config validation and fallback behavior in tests/test_config_summarize_llm.py: test all-three-set activates summarize LLM, partial-set (1 or 2 of 3) logs warning and falls back to main LLM, none-set silently falls back, invalid provider rejected at load time, temperature defaults to 0.3 when summarize LLM active but SUMMARIZE_LLM_TEMPERATURE unset, temperature validation rejects values outside 0.0–2.0

### Implementation for User Story 1

- [X] T005 [US1] Create summarization LLM adapter wiring in main.py: after main LLM adapter creation, check if all three required summarize fields (provider, model, api_key) are set; if so, build synthetic BaseConfig mapping summarize values to llm_* fields and call create_llm_adapter to create second LangChainLLMAdapter; pass to ingest plugins as summarize_llm; log INFO "Summarization LLM configured: provider={provider}, model={model}"; when partial config detected, log WARNING listing missing fields and pass None
- [X] T006 [P] [US1] Update IngestWebsitePlugin to accept optional summarize_llm in plugins/ingest_website/plugin.py: add `summarize_llm: LLMPort | None = None` to __init__, pass `summarize_llm or self._llm` as llm_port to DocumentSummaryStep and BodyOfKnowledgeSummaryStep
- [X] T007 [P] [US1] Update IngestSpacePlugin to accept optional summarize_llm in plugins/ingest_space/plugin.py: add `summarize_llm: LLMPort | None = None` to __init__, pass `summarize_llm or self._llm` as llm_port to DocumentSummaryStep and BodyOfKnowledgeSummaryStep
- [X] T008 [P] [US1] Add token-usage logging to LangChainLLMAdapter.invoke() in core/adapters/langchain_llm.py: extract usage_metadata (input_tokens, output_tokens) from AIMessage response, log at DEBUG level per call (FR-011)
- [X] T009 [US1] Add model name logging per summarization call in core/domain/pipeline/steps.py: in DocumentSummaryStep and BodyOfKnowledgeSummaryStep, log at INFO level the model name, document/BoK ID, and chunk count for each summarization invocation (FR-011)

**Checkpoint**: Summarization LLM is fully configurable, falls back correctly when unconfigured, and logs model/token usage. Cost savings are immediately realized.

---

## Phase 3: User Story 2 — Tune Retrieval Parameters Without Code Changes (Priority: P2)

**Goal**: Adjust retrieval parameters (number of results, score thresholds, context budget) via environment variables for production tuning without deploying code changes.

**Independent Test**: Set `EXPERT_N_RESULTS=8` and `GUIDANCE_N_RESULTS=3` and verify per-plugin chunk counts. Set `EXPERT_MIN_SCORE=0.3` and `GUIDANCE_MIN_SCORE=0.2` and verify score filtering. Set `MAX_CONTEXT_CHARS=5000` and verify lowest-scoring chunks are dropped when budget exceeded.

### Tests for User Story 2

- [X] T010 [P] [US2] Write tests for per-plugin retrieval config validation in tests/test_config_retrieval.py: test expert_n_results and guidance_n_results reject 0 and negative values, expert_min_score and guidance_min_score reject values > 1.0 and < 0.0, defaults match spec (n_results=5, min_score=0.3, max_context_chars=20000)
- [X] T011 [P] [US2] Write tests for MAX_CONTEXT_CHARS enforcement in tests/test_context_budget.py: test context budget enforcement drops lowest-scoring chunks first until under budget, all chunks kept when under budget, warning logged with dropped count and char count when chunks dropped, empty result when budget is very small

### Implementation for User Story 2

- [X] T012 [US2] Update GuidancePlugin to accept n_results parameter in plugins/guidance/plugin.py: add `n_results: int = 5` to __init__, store as self._n_results, replace hardcoded `n_results=5` in _query_collection call (line ~75) and `deduped[:5]` result limit (line ~119) with self._n_results
- [X] T013 [P] [US2] Add MAX_CONTEXT_CHARS enforcement to ExpertPlugin in plugins/expert/plugin.py: accept `max_context_chars: int = 20000` in __init__, after score filtering measure total char count of remaining chunks, if over budget sort by score descending and accumulate until next chunk would exceed budget, drop remaining lowest-scoring chunks, log WARNING "Context budget exceeded: dropped {N} chunks ({chars_dropped} chars)"
- [X] T014 [P] [US2] Add MAX_CONTEXT_CHARS enforcement to GuidancePlugin in plugins/guidance/plugin.py: accept `max_context_chars: int = 20000` in __init__, after dedup and score filtering apply same budget enforcement logic as expert plugin (sort by score descending, accumulate, drop lowest), log WARNING when chunks dropped
- [X] T015 [US2] Update main.py to inject per-plugin retrieval config: pass expert_n_results and expert_min_score from config to ExpertPlugin constructor, pass guidance_n_results and guidance_min_score to GuidancePlugin constructor, pass max_context_chars to both plugin constructors

**Checkpoint**: Per-plugin retrieval parameters are fully externalized and context budget enforcement is active in both retrieval plugins.

---

## Phase 4: User Story 3 — Configure Summarization Chunk Threshold (Priority: P3)

**Goal**: Control the minimum number of chunks a document must have before summarization is triggered, so short documents are not unnecessarily summarized.

**Independent Test**: Set `SUMMARY_CHUNK_THRESHOLD=5`, ingest a 4-chunk document (summarization skipped), then ingest a 6-chunk document (summarization runs).

### Tests for User Story 3

- [X] T016 [P] [US3] Write tests for SUMMARY_CHUNK_THRESHOLD behavior in tests/test_summarize_threshold.py: test docs below threshold are not summarized, docs at threshold are summarized, docs above threshold are summarized, default 4 preserves current behavior (>= 4 is equivalent to > 3), threshold rejects 0 and negative values

### Implementation for User Story 3

- [X] T017 [US3] Add chunk_threshold parameter to DocumentSummaryStep in core/domain/pipeline/steps.py: add `chunk_threshold: int = 4` to __init__, store as self._chunk_threshold, change filter from `if len(doc_chunks) > 3` to `if len(doc_chunks) >= self._chunk_threshold`
- [X] T018 [US3] Wire chunk_threshold from config through ingest plugins to DocumentSummaryStep: in plugins/ingest_website/plugin.py and plugins/ingest_space/plugin.py, accept `chunk_threshold: int = 4` in __init__ and pass to DocumentSummaryStep constructor; in main.py, pass config.summary_chunk_threshold to both ingest plugin constructors

**Checkpoint**: Summarization chunk threshold is externalized and backward compatible (default 4 with >= preserves current > 3 behavior).

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and end-to-end validation across all user stories.

- [X] T019 [P] Update .env.example with all new environment variables, sensible defaults, and descriptions per FR-010: SUMMARIZE_LLM_PROVIDER, SUMMARIZE_LLM_MODEL, SUMMARIZE_LLM_API_KEY, SUMMARIZE_LLM_TEMPERATURE, SUMMARIZE_LLM_TIMEOUT, EXPERT_N_RESULTS, EXPERT_MIN_SCORE, GUIDANCE_N_RESULTS, GUIDANCE_MIN_SCORE, MAX_CONTEXT_CHARS, SUMMARY_CHUNK_THRESHOLD
- [X] T020 Run quickstart.md validation scenarios to verify end-to-end behavior: summarization model usage, retrieval parameter tuning, context budget enforcement
- [X] T021 Verify backward compatibility (FR-009): run with NO new env vars set and confirm all existing behavior unchanged — summarization uses main LLM, retrieval uses current defaults, context is unlimited (20k default), chunk threshold matches current > 3 logic

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately. BLOCKS all user stories.
- **User Story 1 (Phase 2)**: Depends on Phase 1 completion
- **User Story 2 (Phase 3)**: Depends on Phase 1 completion
- **User Story 3 (Phase 4)**: Depends on Phase 1 completion
- **Polish (Phase 5)**: Depends on all user story phases being complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent of US2 and US3
- **User Story 2 (P2)**: Independent of US1 and US3
- **User Story 3 (P3)**: Independent of US1 and US2

### Within Each User Story

- Tests FIRST — write tests, verify they fail before implementation
- Plugin parameter additions can proceed in parallel (different files)
- main.py wiring after plugin constructors are updated
- Core logic changes (steps.py, adapter) can proceed in parallel with plugin changes

### Parallel Opportunities

**Phase 1**: T001 then T002 (sequential — same file). T003 parallel with T002 (different file).
**Phase 2**: T004 parallel with T006, T007, T008 (all different files). T005 after T006/T007 (main.py wires to updated plugins). T009 after T008 or in parallel (different file).
**Phase 3**: T010 and T011 parallel (different test files). T012, T013, T014 parallel (different plugin files). T015 after T012 (main.py wires to updated plugins).
**Phase 4**: T016 parallel with T017 (different files). T018 after T017 (depends on step change).
**Phase 5**: T019 parallel with T020 and T021.

---

## Parallel Example: User Story 1

```text
# Launch tests and independent plugin changes together:
Task T004: "Write tests for summarization LLM config in tests/test_config_summarize_llm.py"
Task T006: "Update IngestWebsitePlugin in plugins/ingest_website/plugin.py"
Task T007: "Update IngestSpacePlugin in plugins/ingest_space/plugin.py"
Task T008: "Add token-usage logging in core/adapters/langchain_llm.py"

# Then sequential:
Task T005: "Wire summarization LLM adapter in main.py" (needs T006, T007)
Task T009: "Add model name logging in core/domain/pipeline/steps.py"
```

## Parallel Example: User Story 2

```text
# Launch tests together:
Task T010: "Write retrieval config tests in tests/test_config_retrieval.py"
Task T011: "Write context budget tests in tests/test_context_budget.py"

# Launch plugin changes together:
Task T012: "Update GuidancePlugin n_results in plugins/guidance/plugin.py"
Task T013: "Add MAX_CONTEXT_CHARS to ExpertPlugin in plugins/expert/plugin.py"
Task T014: "Add MAX_CONTEXT_CHARS to GuidancePlugin in plugins/guidance/plugin.py"

# Then:
Task T015: "Inject per-plugin config in main.py" (needs T012)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (config + validation + logging)
2. Complete Phase 2: User Story 1 (separate summarization LLM)
3. **STOP and VALIDATE**: Test US1 independently — verify cheap model used for summarization, main model for responses
4. Deploy if ready — cost savings are immediately realized (5-10x reduction)

### Incremental Delivery

1. Phase 1 -> Foundation ready
2. Add US1 -> Test independently -> Deploy (5-10x summarization cost reduction - MVP!)
3. Add US2 -> Test independently -> Deploy (production retrieval tuning without code changes)
4. Add US3 -> Test independently -> Deploy (summarization threshold control)
5. Phase 5 -> Final polish and validation

---

## Notes

- All changes are additive to existing files — no new modules or directories needed (except test files)
- No port, adapter, or contract interface changes required
- Summarization LLM reuses existing `create_llm_adapter()` factory with a synthetic config (R1)
- Existing retry (3 attempts with exponential backoff) + per-doc error handling already satisfies retry spec — no changes needed (R6)
- The `deduped[:5]` limit in guidance plugin changes to `deduped[:self._n_results]` (R9)
- Default `summary_chunk_threshold=4` with `>=` preserves exact backward compatibility: `>= 4` is equivalent to `> 3` (R5)
- Global `retrieval_n_results` and `retrieval_score_threshold` fields are deprecated but preserved for backward compat (R3)
- `MAX_CONTEXT_CHARS` applies per-plugin to the active plugin's merged retrieval results, consistent with microkernel isolation (R4)
