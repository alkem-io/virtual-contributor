# Tasks: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Input**: Design documents from `specs/010-bok-llm-factory-hardening/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Config Fields)

**Purpose**: All new config fields that MUST be in place before user story work begins.

- [X] T001 Add `bok_llm_provider: LLMProvider | None = None`, `bok_llm_model: str | None = None`, `bok_llm_api_key: str | None = None`, `bok_llm_base_url: str | None = None`, `bok_llm_temperature: float | None = None`, `bok_llm_timeout: int | None = None` fields to BaseConfig in core/config.py
- [X] T002 Add `summarize_llm_base_url: str | None = None` field to BaseConfig in core/config.py
- [X] T003 [P] Add `bok_llm_provider`, `bok_llm_model`, `bok_llm_api_key`, `bok_llm_base_url` to the `_log_config()` fields list in main.py

**Checkpoint**: Config fields and startup logging in place.

---

## Phase 2: User Story 1 — Dedicated BoK LLM (Priority: P1) MVP

**Goal**: Configure a separate large-context LLM for body-of-knowledge summarization, with fallback to summarize LLM then main LLM.

**Independent Test**: Set `BOK_LLM_*` variables to a large-context model. Ingest a space and verify BoK summary uses the configured model while per-document summaries use the summarize LLM.

### Implementation for User Story 1

- [X] T004 [US1] Create BoK LLM adapter wiring in main.py: check if all three required bok fields are set, build synthetic BaseConfig mapping bok values to llm_* fields, call create_llm_adapter with disable_thinking=True, log BoK LLM config at INFO
- [X] T005 [P] [US1] Update IngestSpacePlugin to accept optional `bok_llm: LLMPort | None = None` in plugins/ingest_space/plugin.py, store as self._bok_llm, pass `self._bok_llm or summary_llm` to BodyOfKnowledgeSummaryStep
- [X] T006 [P] [US1] Update IngestWebsitePlugin to accept optional `bok_llm: LLMPort | None = None` in plugins/ingest_website/plugin.py, store as self._bok_llm, pass `self._bok_llm or summary_llm` to BodyOfKnowledgeSummaryStep
- [X] T007 [US1] Add bok_llm injection in main.py: if "bok_llm" in sig.parameters, inject the bok_llm adapter into plugin deps

**Checkpoint**: BoK LLM is fully configurable with 3-tier fallback chain.

---

## Phase 3: User Story 2 — Summarize LLM Base URL (Priority: P2)

**Goal**: Support base URL override for the summarization LLM to enable local model backends.

**Independent Test**: Set `SUMMARIZE_LLM_BASE_URL=http://localhost:8000/v1` and verify summarization calls route to the local server.

### Implementation for User Story 2

- [X] T008 [US2] Wire summarize_llm_base_url in main.py: in the summarize LLM synthetic config block, map `summarize_llm_base_url` to `llm_base_url` when set; include base_url in INFO log message
- [X] T009 [P] [US2] Add `summarize_llm_base_url` to the `_log_config()` fields list in main.py (already done in T003 for bok fields — this covers summarize base_url)

**Checkpoint**: Summarization LLM can target a separate endpoint.

---

## Phase 4: User Story 3 — LLM Factory Hardening (Priority: P3)

**Goal**: Harden the LLM factory for correct behavior with diverse model backends.

**Independent Test**: Configure a Qwen3 model and verify no `<think>` tags in output. Configure an OpenAI-compatible local model and verify no httpx errors.

### Implementation for User Story 3

- [X] T010 [US3] Add `disable_thinking: bool = False` parameter to `create_llm_adapter()` in core/provider_factory.py; when True, add `extra_body: {"chat_template_kwargs": {"enable_thinking": False}}` to kwargs
- [X] T011 [US3] Restrict httpx keep-alive disabling to Mistral provider in core/provider_factory.py: add `provider == LLMProvider.mistral` guard to the if condition
- [X] T012 [US3] Tighten async_client check in core/provider_factory.py: change from `hasattr(llm, "async_client") and llm.async_client` to `hasattr(llm, "async_client") and hasattr(llm.async_client, "headers")`
- [X] T013 [US3] Pass `disable_thinking=True` to both summarize and BoK LLM creation calls in main.py

**Checkpoint**: Factory correctly handles Qwen3 thinking suppression and Mistral-specific client patching.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T014 [P] Update .env.example with BOK_LLM_PROVIDER, BOK_LLM_MODEL, BOK_LLM_API_KEY, BOK_LLM_BASE_URL, BOK_LLM_TEMPERATURE, BOK_LLM_TIMEOUT, and SUMMARIZE_LLM_BASE_URL with descriptions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately
- **User Story 1 (Phase 2)**: Depends on Phase 1 (config fields) and Phase 4 T010 (disable_thinking param)
- **User Story 2 (Phase 3)**: Depends on Phase 1 T002 (base_url config field)
- **User Story 3 (Phase 4)**: No dependencies on other user stories (factory changes)
- **Polish (Phase 5)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends on US3 T010 (needs disable_thinking param in factory)
- **User Story 2 (P2)**: Independent of US1 and US3
- **User Story 3 (P3)**: Independent of US1 and US2

### Parallel Opportunities

**Phase 1**: T001, T002 sequential (same file). T003 parallel (different file).
**Phase 2**: T005, T006 parallel (different plugin files). T004 after T005/T006 (main.py wires to updated plugins). T007 after T004.
**Phase 3**: T008 sequential with Phase 2 main.py work. T009 parallel.
**Phase 4**: T010, T011, T012 sequential (same file). T013 after T010.
**Phase 5**: T014 parallel with any phase.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Config fields
2. Complete Phase 4 T010: disable_thinking param (prerequisite)
3. Complete Phase 2: BoK LLM creation + plugin wiring
4. **STOP and VALIDATE**: Test 3-tier LLM fallback independently
5. Deploy — BoK summarization can now use a dedicated large-context model

### Incremental Delivery

1. Phase 1 + Phase 4 -> Foundation + factory hardened
2. Add US1 -> Test independently -> Deploy (3-tier LLM, MVP!)
3. Add US2 -> Test independently -> Deploy (local model support for summarization)
4. Phase 5 -> Final polish
