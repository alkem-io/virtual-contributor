# Feature Specification: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Feature Branch**: `develop`
**Created**: 2026-04-08
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Dedicated LLM for Body-of-Knowledge Summarization (Priority: P1)

As a platform operator, I want to configure a separate LLM for body-of-knowledge (BoK) summarization — distinct from both the main LLM and the document summarization LLM — so that I can use a large-context-window model for BoK summaries (which aggregate all document summaries into one) while keeping a smaller, cheaper model for per-document summarization.

**Why this priority**: BoK summarization processes the concatenation of all document summaries, which can be extremely long. A large-context model (e.g., 128K+ tokens) is needed to avoid truncation, but such models are expensive. Per-document summarization handles much shorter inputs and can use a cheaper model. Separating these allows cost optimization without sacrificing quality.

**Independent Test**: Set `BOK_LLM_PROVIDER`, `BOK_LLM_MODEL`, and `BOK_LLM_API_KEY` to a large-context model. Set `SUMMARIZE_LLM_*` to a cheaper model. Ingest a space with many documents. Verify that per-document summaries use the summarize LLM while the final BoK summary uses the BoK LLM.

**Acceptance Scenarios**:

1. **Given** `BOK_LLM_PROVIDER`, `BOK_LLM_MODEL`, and `BOK_LLM_API_KEY` are all set, **When** a space or website is ingested, **Then** the `BodyOfKnowledgeSummaryStep` uses the configured BoK LLM.
2. **Given** BoK LLM is not configured but summarize LLM is configured, **When** ingestion runs, **Then** BoK summarization falls back to the summarize LLM.
3. **Given** neither BoK LLM nor summarize LLM is configured, **When** ingestion runs, **Then** BoK summarization falls back to the main LLM.
4. **Given** `BOK_LLM_TEMPERATURE=0.2`, **When** the BoK LLM is created, **Then** it uses temperature 0.2.
5. **Given** `BOK_LLM_TEMPERATURE` is not set, **When** the BoK LLM is created, **Then** it defaults to temperature 0.3.
6. **Given** `BOK_LLM_BASE_URL=http://localhost:8000/v1`, **When** the BoK LLM is created, **Then** it connects to the specified base URL.
7. **Given** `BOK_LLM_TIMEOUT=300`, **When** the BoK LLM is created, **Then** it uses a 300-second timeout. **Given** `BOK_LLM_TIMEOUT` is not set, **Then** it falls back to the main `LLM_TIMEOUT`.

---

### User Story 2 — Summarize LLM Base URL Override (Priority: P2)

As a platform operator, I want to configure a base URL for the summarization LLM so that I can point it to a local model server (e.g., vLLM, Ollama) running a cheaper summarization model, without affecting the main LLM endpoint.

**Why this priority**: Local model servers offer cost savings and latency benefits for summarization tasks. Without base URL support, the summarization LLM inherits the main LLM's endpoint, which may be a remote API.

**Independent Test**: Set `SUMMARIZE_LLM_BASE_URL=http://localhost:8000/v1` alongside the other `SUMMARIZE_LLM_*` vars. Verify that summarization calls go to the local server while the main LLM uses its configured endpoint.

**Acceptance Scenarios**:

1. **Given** `SUMMARIZE_LLM_BASE_URL=http://localhost:8000/v1`, **When** the summarization LLM is created, **Then** it connects to the specified base URL instead of the main LLM's base URL.
2. **Given** `SUMMARIZE_LLM_BASE_URL` is not set, **When** the summarization LLM is created, **Then** it inherits the main LLM's base URL (existing behavior).
3. **Given** `SUMMARIZE_LLM_BASE_URL` is set, **When** startup logging runs, **Then** the configured base URL is logged at INFO level.

---

### User Story 3 — LLM Factory Hardening for Local Model Backends (Priority: P3)

As a platform operator running local LLM servers (e.g., Qwen3 via vLLM), I want the LLM factory to correctly handle provider-specific behaviors so that summarization and BoK models work reliably with diverse backends.

**Why this priority**: Without these fixes, local models may produce unwanted chain-of-thought output (Qwen3) or trigger errors from incorrect client patching (ChatOpenAI receiving Mistral-specific httpx modifications).

**Independent Test**: Configure a Qwen3 model via `SUMMARIZE_LLM_*` with `SUMMARIZE_LLM_BASE_URL` pointing to a vLLM server. Verify that summarization output does not contain `<think>` tags. Configure an OpenAI-compatible local model and verify no httpx client errors.

**Acceptance Scenarios**:

1. **Given** the summarization or BoK LLM is created, **When** the factory builds the adapter, **Then** `enable_thinking: false` is sent via `extra_body` to suppress Qwen3-style chain-of-thought reasoning.
2. **Given** the LLM provider is Mistral with a custom `base_url`, **When** the factory builds the adapter, **Then** the httpx keep-alive disabling logic is applied.
3. **Given** the LLM provider is OpenAI with a custom `base_url`, **When** the factory builds the adapter, **Then** the httpx keep-alive disabling logic is NOT applied (ChatOpenAI uses a different client).
4. **Given** the LLM provider is Mistral, **When** the factory checks for `async_client`, **Then** it verifies both that `async_client` exists AND that it has a `headers` attribute before attempting to replace it.

---

### Edge Cases

- When only 1 or 2 of the 3 required `BOK_LLM_*` variables are set, the system silently falls back to the summarize LLM (or main LLM). No warning is logged for partial BoK config (unlike summarize LLM, which does warn).
- When `BOK_LLM_PROVIDER` specifies an unsupported provider, the `LLMProvider` enum validation catches it at config load time.
- When `disable_thinking` is `True` but the model does not support the `extra_body` parameter, the model backend should ignore the unknown parameter (standard OpenAI-compatible behavior).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support a separate LLM configuration for BoK summarization via `BOK_LLM_PROVIDER`, `BOK_LLM_MODEL`, `BOK_LLM_API_KEY`, `BOK_LLM_BASE_URL`, `BOK_LLM_TEMPERATURE`, and `BOK_LLM_TIMEOUT` environment variables.
- **FR-002**: System MUST fall back from BoK LLM to summarize LLM, then to main LLM, when BoK-specific variables are not set.
- **FR-003**: System MUST support `SUMMARIZE_LLM_BASE_URL` to override the base URL for the summarization LLM independently of the main LLM.
- **FR-004**: The LLM factory MUST accept a `disable_thinking` parameter that sends `enable_thinking: false` via `extra_body` when creating an adapter, suppressing chain-of-thought reasoning for models like Qwen3.
- **FR-005**: The LLM factory MUST restrict httpx keep-alive disabling to the Mistral provider only, not applying it to OpenAI or Anthropic providers.
- **FR-006**: The LLM factory MUST verify that the LangChain model's `async_client` has a `headers` attribute before attempting to replace it.
- **FR-007**: System MUST log the BoK LLM configuration (provider, model, base URL) at startup when configured.
- **FR-008**: System MUST log `summarize_llm_base_url` and `bok_llm_*` fields in the startup config log.
- **FR-009**: The `.env.example` file MUST document all new variables (`BOK_LLM_*`, `SUMMARIZE_LLM_BASE_URL`).
- **FR-010**: System MUST pass `disable_thinking=True` when creating both the summarization LLM and BoK LLM adapters.

### Key Entities

- **BoK LLM Configuration**: A set of provider, model, API key, base URL, temperature, and timeout settings for the body-of-knowledge summarization model. Falls back to summarize LLM config, then to main LLM config.
- **Summarize LLM Base URL**: An optional URL override allowing the summarization LLM to connect to a different endpoint than the main LLM.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can configure three independent LLM tiers — main (user-facing), summarize (per-document), and BoK (aggregated summaries) — each with its own provider, model, and endpoint.
- **SC-002**: Local model backends (vLLM, Ollama) work correctly for summarization and BoK models without chain-of-thought leakage or client errors.
- **SC-003**: The fallback chain (BoK LLM -> summarize LLM -> main LLM) activates transparently when optional tiers are not configured.
- **SC-004**: All new environment variables have documented defaults that reproduce current behavior when unset.

## Assumptions

- The existing LLM adapter creation pattern (synthetic `BaseConfig` + `create_llm_adapter`) supports creating multiple independent adapters in the same process.
- Qwen3 models support the `extra_body.chat_template_kwargs.enable_thinking` parameter via OpenAI-compatible API.
- The `disable_thinking` parameter is harmless for models that do not support it (standard behavior for unknown extra_body fields).
- BoK summarization is only relevant for ingest plugins (`ingest-space`, `ingest-website`); non-ingest plugins do not need the BoK LLM.
