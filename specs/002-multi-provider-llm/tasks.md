# Tasks: Multi-Provider LLM Support

**Input**: Design documents from `/specs/002-multi-provider-llm/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — mandated by constitution principles P4 (Optimised Feedback Loops) and P7 (No Filling Tests).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add new dependency and create required ADR before implementation begins.

- [X] T001 Add `langchain-anthropic` package as dependency in `pyproject.toml` and run `poetry lock`
- [X] T002 [P] Create ADR "0005 — Unified LangChain adapter with provider factory for multi-provider LLM support" in `docs/adr/0005-unified-langchain-adapter.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extend configuration model with provider-agnostic fields. MUST complete before any user story work.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `LLMProvider` enum (`mistral`, `openai`, `anthropic`) and provider config fields (`llm_provider`, `llm_api_key`, `llm_model`, `llm_base_url`, `llm_temperature`, `llm_max_tokens`, `llm_top_p`, `llm_timeout`) with backward-compatibility aliases for `MISTRAL_API_KEY` → `llm_api_key` and `MISTRAL_SMALL_MODEL_NAME` → `llm_model` to `core/config.py`
- [X] T004 Add Pydantic validators for provider config: unsupported provider fail-fast (FR-008), API key required unless `base_url` is set, temperature in [0.0, 2.0], max_tokens > 0, top_p in [0.0, 1.0], timeout > 0 in `core/config.py`

**Checkpoint**: Configuration model ready — provider selection and validation available for all stories.

---

## Phase 3: User Story 1 — Switch LLM Provider via Configuration (Priority: P1) 🎯 MVP

**Goal**: Make the engine provider-agnostic — switch between Mistral, OpenAI, and Anthropic by changing environment variables only.

**Independent Test**: Start the engine with `LLM_PROVIDER=openai` (or `anthropic`), send a message via RabbitMQ, and verify a valid response is returned in the same envelope format as the current Mistral-based engine.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T005 [P] [US1] Write tests for provider factory: resolution of each provider, default model names (FR-013), fail-fast on unsupported provider, generation param passthrough, timeout passthrough in `tests/core/test_provider_factory.py`
- [X] T006 [P] [US1] Write tests for `LangChainLLMAdapter`: invoke returns string, stream yields chunks, retry logic (3 attempts with exponential backoff), message role conversion (system→SystemMessage, human→HumanMessage, assistant→AIMessage) in `tests/core/test_langchain_llm.py`
- [X] T007 [P] [US1] Write tests for config validation: backward-compat alias resolution (`MISTRAL_API_KEY` fallback), missing API key error, invalid temperature/max_tokens/top_p ranges, default provider is `mistral` in `tests/core/test_config_validation.py`

### Implementation for User Story 1

- [X] T008 [P] [US1] Create unified `LangChainLLMAdapter` implementing `LLMPort` with invoke (retry 3× exponential backoff), stream, and message conversion (dict → LangChain `SystemMessage`/`AIMessage`/`HumanMessage`) in `core/adapters/langchain_llm.py`
- [X] T009 [P] [US1] Create `create_llm_adapter(config)` factory function mapping `LLMProvider` enum to LangChain model classes (`ChatMistralAI`, `ChatOpenAI`, `ChatAnthropic`) with default models per provider (FR-013), generation params, base_url, and timeout passthrough in `core/provider_factory.py`
- [X] T010 [US1] Replace direct `MistralAdapter` instantiation with `create_llm_adapter(config)` call in `_create_adapters()` in `main.py`
- [X] T011 [US1] Add startup INFO log of active provider name, model, and base_url after successful provider resolution in `main.py` (FR-010)
- [X] T012 [P] [US1] Remove legacy adapter `core/adapters/mistral.py`
- [X] T013 [P] [US1] Remove legacy adapter `core/adapters/openai_llm.py`

**Checkpoint**: Engine starts with any of 3 providers via `LLM_PROVIDER` env var. Existing Mistral deployments work unchanged (FR-009). All tests pass.

---

## Phase 4: User Story 2 — Consistent Structured Output Across Providers (Priority: P1)

**Goal**: Plugins that expect structured JSON responses (e.g., guidance plugin's `result` + `source_scores` format) receive reliably parsed, schema-validated output regardless of provider — even with markdown fences, preamble, or inconsistent formatting.

**Independent Test**: Send the same guidance query through each supported provider. Verify that all produce a response where the `result` field is a non-empty string and `source_scores` is a valid mapping or absent.

### Tests for User Story 2

- [X] T014 [P] [US2] Write tests for structured output parsing edge cases: fenced JSON (```json...```), preamble text before JSON, malformed JSON fallback to raw text, empty response fallback, nested JSON extraction in `tests/plugins/test_guidance_structured_output.py`

### Implementation for User Story 2

- [X] T015 [US2] Review and harden JSON extraction in `_parse_json_sources()` to handle markdown fences, preamble text, trailing text, and provider-specific formatting differences in `plugins/guidance/plugin.py`
- [X] T016 [US2] Implement fallback-to-raw-text behavior: when structured parsing fails, return raw LLM text as `result` field with empty `source_scores` and log a warning — never crash or return error response (FR-005) in `plugins/guidance/plugin.py`

**Checkpoint**: Guidance plugin returns valid structured responses across all providers. Malformed output gracefully degrades to raw text.

---

## Phase 5: User Story 3 — Use a Local/Self-Hosted Model (Priority: P2)

**Goal**: Support self-hosted models (vLLM, sglang, Ollama) by pointing the engine at a local OpenAI-compatible endpoint via `LLM_BASE_URL`, without requiring a cloud API key.

**Independent Test**: Start the engine with `LLM_PROVIDER=openai`, `LLM_BASE_URL=http://localhost:8000/v1`, and a local model name. Send a query and verify a valid response.

### Implementation for User Story 3

- [X] T017 [US3] Add test verifying factory passes `base_url` to `ChatOpenAI` constructor and config validation skips API key requirement when `LLM_BASE_URL` is set in `tests/core/test_provider_factory.py`
- [X] T018 [US3] Add connection error handling for unreachable local endpoints — return meaningful error message with endpoint URL instead of raw exception, do not hang beyond `LLM_TIMEOUT` in `core/adapters/langchain_llm.py`

**Checkpoint**: Engine connects to local OpenAI-compatible endpoints. Unreachable endpoints produce clear error messages.

---

## Phase 6: User Story 4 — Per-Plugin Provider Override (Priority: P3)

**Goal**: Support different providers for different plugins via `{PLUGIN_NAME}_LLM_PROVIDER` and `{PLUGIN_NAME}_LLM_API_KEY` environment variables that override global `LLM_*` defaults.

**Independent Test**: Set `GUIDANCE_LLM_PROVIDER=mistral` and `EXPERT_LLM_PROVIDER=anthropic` with respective API keys. Start each plugin and verify they use their configured providers.

### Implementation for User Story 4

- [X] T019 [US4] Add per-plugin env var resolution in `_create_adapters()`: check `{PLUGIN_NAME}_LLM_PROVIDER`, `{PLUGIN_NAME}_LLM_API_KEY`, `{PLUGIN_NAME}_LLM_MODEL`, `{PLUGIN_NAME}_LLM_BASE_URL`, `{PLUGIN_NAME}_LLM_TEMPERATURE`, `{PLUGIN_NAME}_LLM_MAX_TOKENS`, `{PLUGIN_NAME}_LLM_TOP_P` before falling back to global `LLM_*` values in `main.py`
- [X] T020 [P] [US4] Write test for per-plugin provider override: plugin-specific vars take precedence over global (including generation params: temperature, max_tokens, top_p), missing plugin vars fall back to global in `tests/core/test_config_validation.py`

**Checkpoint**: Different plugins can use different providers in the same deployment. Global config is the fallback.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup and validation across all stories.

- [X] T021 [P] Create or update `.env.example` with all `LLM_*` environment variables and usage comments at repository root
- [X] T022 [P] Clean up any remaining import references to removed adapters (`mistral.py`, `openai_llm.py`) across the codebase
- [X] T023 Run quickstart.md validation scenarios: verify Mistral, OpenAI, Anthropic, and local model configurations all produce valid responses

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on T001 (langchain-anthropic installed) — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 completion — core MVP
- **US2 (Phase 4)**: Depends on Phase 2 completion — can run in parallel with US1 (different files)
- **US3 (Phase 5)**: Depends on US1 completion (factory must exist)
- **US4 (Phase 6)**: Depends on US1 completion (factory must exist)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **US2 (P1)**: Can start after Phase 2 — independent of US1 (different files: `plugins/guidance/` vs `core/adapters/`)
- **US3 (P2)**: Depends on US1 (extends factory and adapter in same files)
- **US4 (P3)**: Depends on US1 (extends `main.py` wiring from US1)

### Within Each User Story

- Tests written FIRST and verified to FAIL before implementation
- Adapter/model before factory
- Factory before wiring (main.py)
- Core implementation before cleanup (removing old files)

### Parallel Opportunities

- T001 and T002 can run in parallel (Phase 1)
- T005, T006, T007 can run in parallel (US1 tests — different files)
- T008 and T009 can run in parallel (US1 implementation — different files)
- T012 and T013 can run in parallel (removing old adapters — different files)
- US1 and US2 can run in parallel (different file groups)
- T021 and T022 can run in parallel (Polish — different files)

---

## Parallel Example: User Story 1

```bash
# Launch all tests together (TDD — write first, verify they fail):
Task T005: "tests/core/test_provider_factory.py"
Task T006: "tests/core/test_langchain_llm.py"
Task T007: "tests/core/test_config_validation.py"

# Launch adapter and factory together:
Task T008: "core/adapters/langchain_llm.py"
Task T009: "core/provider_factory.py"

# Then wire sequentially:
Task T010: "main.py" (use factory)
Task T011: "main.py" (add logging)

# Then remove old adapters together:
Task T012: "core/adapters/mistral.py" (delete)
Task T013: "core/adapters/openai_llm.py" (delete)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (add dependency, create ADR)
2. Complete Phase 2: Foundational (config model with provider fields + validation)
3. Complete Phase 3: User Story 1 (unified adapter + factory + wiring)
4. **STOP and VALIDATE**: Switch between providers via env vars. Verify identical response envelopes. Verify existing Mistral config still works.
5. Deploy/demo if ready — this is the core value proposition.

### Incremental Delivery

1. Setup + Foundational → Config model ready
2. US1 → Provider switching works → **Deploy MVP**
3. US2 → Structured output robust across providers → Deploy
4. US3 → Local/self-hosted models supported → Deploy
5. US4 → Per-plugin provider overrides → Deploy
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (core adapter + factory + wiring)
   - Developer B: User Story 2 (structured output hardening in guidance plugin)
3. After US1 merges:
   - Developer A: User Story 3 (local models)
   - Developer B: User Story 4 (per-plugin overrides)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Verify tests fail before implementing (TDD)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Existing Mistral deployments must continue working unchanged throughout (FR-009)
