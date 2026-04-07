# Feature Specification: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Feature Branch**: `007-configurable-summarization`  
**Created**: 2026-04-06  
**Status**: Draft  
**Input**: User description: "implement https://github.com/orgs/alkem-io/projects/50/views/8?pane=issue&itemId=172797577&issue=alkem-io%7Cvirtual-contributor%7C21"  
**Source**: [alkem-io/virtual-contributor#21](https://github.com/alkem-io/virtual-contributor/issues/21)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Reduce Summarization Costs with a Separate LLM (Priority: P1)

As a platform operator, I want to configure a separate, cheaper LLM for document and body-of-knowledge summarization so that ingestion costs are reduced by 5-10x without affecting the quality of user-facing responses.

**Why this priority**: Summarization is a simpler task than answering user questions. Using the same high-capability (and expensive) model for both is wasteful. The original TypeScript pipeline already used a dedicated Mistral model for this purpose. This is the highest-impact cost optimization available.

**Independent Test**: Deploy the system with `SUMMARIZE_LLM_*` environment variables pointing to a cheaper model (e.g., Mistral Small). Ingest a space and verify that summaries are generated using the configured summarization model while user-facing responses continue to use the main model.

**Acceptance Scenarios**:

1. **Given** `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, and `SUMMARIZE_LLM_API_KEY` are set, **When** a space is ingested, **Then** all summarization tasks (document summaries and body-of-knowledge summaries) use the configured summarization LLM instead of the main LLM.
2. **Given** no `SUMMARIZE_LLM_*` variables are set, **When** a space is ingested, **Then** summarization steps fall back to using the main LLM (backward-compatible behavior).
3. **Given** `SUMMARIZE_LLM_TEMPERATURE` is set to 0.2, **When** summarization runs, **Then** the summarization LLM uses the specified temperature value.
4. **Given** `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, and `SUMMARIZE_LLM_API_KEY` are set but `SUMMARIZE_LLM_TEMPERATURE` is not, **When** summarization runs, **Then** the summarization LLM uses a temperature of 0.3.

---

### User Story 2 — Tune Retrieval Parameters Without Code Changes (Priority: P2)

As a platform operator, I want to adjust retrieval parameters (number of results, score thresholds, context budget) via environment variables so that I can iteratively tune retrieval quality in production without deploying code changes.

**Why this priority**: Retrieval quality directly affects user-facing answer quality. Being able to tune `n_results`, score thresholds, and context budgets in production enables rapid experimentation and optimization based on observed retrieval performance.

**Independent Test**: Set `EXPERT_N_RESULTS=8` and `GUIDANCE_N_RESULTS=3` and verify that the expert plugin retrieves 8 chunks and the guidance plugin retrieves 3 chunks per collection. Set `EXPERT_MIN_SCORE=0.3` and `GUIDANCE_MIN_SCORE=0.2` and verify low-scoring results are filtered out per-plugin.

**Acceptance Scenarios**:

1. **Given** `EXPERT_N_RESULTS=8`, **When** the expert plugin retrieves chunks, **Then** it requests 8 results from the vector store instead of the current hardcoded value.
2. **Given** `GUIDANCE_N_RESULTS=3`, **When** the guidance plugin retrieves chunks, **Then** it requests 3 results per collection instead of the current hardcoded value.
3. **Given** `EXPERT_MIN_SCORE=0.3`, **When** the expert plugin retrieves chunks, **Then** results with a score below 0.3 are excluded. **Given** `GUIDANCE_MIN_SCORE=0.2`, **When** the guidance plugin retrieves chunks, **Then** results with a score below 0.2 are excluded.
4. **Given** `MAX_CONTEXT_CHARS=15000`, **When** building context for the LLM call, **Then** the total context is limited to 15,000 characters by dropping lowest-scoring chunks first until the budget is met.
5. **Given** none of these variables are set, **When** plugins retrieve chunks, **Then** they use their current default values (expert: 5, guidance: 5, expert min score: 0.3, guidance min score: 0.3, max context: 20,000).

---

### User Story 3 — Configure Summarization Chunk Threshold (Priority: P3)

As a platform operator, I want to control the minimum number of chunks a document must have before summarization is triggered so that short documents are not unnecessarily summarized.

**Why this priority**: This is a lower-impact tuning knob compared to LLM selection and retrieval parameters, but it still enables meaningful control over ingestion behavior without code changes.

**Independent Test**: Set `SUMMARY_CHUNK_THRESHOLD=5` and ingest a document with 4 chunks. Verify that summarization is skipped. Then ingest a document with 5+ chunks and verify summarization runs.

**Acceptance Scenarios**:

1. **Given** `SUMMARY_CHUNK_THRESHOLD=5`, **When** a document with 3 chunks is ingested, **Then** summarization is skipped for that document.
2. **Given** `SUMMARY_CHUNK_THRESHOLD=5`, **When** a document with 6 chunks is ingested, **Then** summarization runs normally.
3. **Given** `SUMMARY_CHUNK_THRESHOLD` is not set, **When** a document is ingested, **Then** the default threshold of 4 is used — documents with 4 or more chunks are summarized, preserving the current `> 3` behavior.

---

### Edge Cases

- What happens when any subset of `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, `SUMMARIZE_LLM_API_KEY` is set but not all three? The system should fall back to the main LLM and log a warning indicating which variables are missing.
- What happens when `SUMMARIZE_LLM_PROVIDER` specifies an unsupported provider? The system should fail fast at startup with a clear error message.
- What happens when `EXPERT_N_RESULTS` is set to 0 or a negative number? The system should reject invalid values at configuration load time.
- What happens when `EXPERT_MIN_SCORE` or `GUIDANCE_MIN_SCORE` is set to a value greater than 1.0? The system should reject it as invalid (scores range from 0.0 to 1.0).
- What happens when `MAX_CONTEXT_CHARS` is set extremely low (e.g., 100)? The system should still function, though answer quality will degrade. A minimum floor is not required but a warning log is desirable.
- When `MAX_CONTEXT_CHARS` is exceeded, the system drops the lowest-scoring chunks first until the total context fits within the budget.
- When a summarization LLM call fails (API timeout, rate limit, etc.), the system retries up to 3 times, then skips summarization for that document and continues ingestion without a summary. A warning is logged.

## Out of Scope

- **Per-space / per-knowledge-base configuration**: All configuration in this feature is global via environment variables. Per-space LLM or retrieval parameter overrides (requiring database storage, API changes, or UI) are not part of this feature.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support a separate LLM configuration for summarization tasks via `SUMMARIZE_LLM_PROVIDER`, `SUMMARIZE_LLM_MODEL`, `SUMMARIZE_LLM_API_KEY`, `SUMMARIZE_LLM_TEMPERATURE`, and `SUMMARIZE_LLM_TIMEOUT` environment variables. The summarization LLM MUST support all providers already supported by the main LLM factory (OpenAI, Mistral, Anthropic). When `SUMMARIZE_LLM_TEMPERATURE` is not set, the summarization LLM MUST default to temperature 0.3. When `SUMMARIZE_LLM_TIMEOUT` is not set, the summarization LLM MUST fall back to the main LLM timeout value.
- **FR-002**: System MUST fall back to the main LLM configuration when summarization-specific environment variables are not set.
- **FR-003**: System MUST allow the number of retrieved chunks for the expert plugin to be configured via `EXPERT_N_RESULTS` (default: 5).
- **FR-004**: System MUST allow the number of retrieved chunks per collection for the guidance plugin to be configured via `GUIDANCE_N_RESULTS` (default: 5).
- **FR-005**: System MUST allow per-plugin minimum retrieval score thresholds via `EXPERT_MIN_SCORE` (default: 0.3) and `GUIDANCE_MIN_SCORE` (default: 0.3). These defaults match the current `retrieval_score_threshold=0.3` behavior (FR-009). A score of 0.0 means no filtering.
- **FR-006**: System MUST allow a maximum context character budget to be configured via `MAX_CONTEXT_CHARS` (default: 20,000). When the budget is exceeded, the active plugin MUST apply the budget within its own merged retrieval set and drop the lowest-scoring chunks until the total context fits within the budget. Each plugin enforces the budget independently (plugins run in isolated containers).
- **FR-007**: System MUST allow the minimum chunk count for triggering summarization to be configured via `SUMMARY_CHUNK_THRESHOLD` (default: 4). Documents with chunk count `>= SUMMARY_CHUNK_THRESHOLD` are summarized. The default of 4 preserves the current `> 3` behavior exactly (FR-009).
- **FR-008**: System MUST validate all configuration values at load time and reject invalid values with clear error messages.
- **FR-009**: System MUST preserve existing behavior when none of the new environment variables are set (full backward compatibility).
- **FR-010**: The `.env.example` file MUST be updated to document all new variables with sensible defaults and descriptions.
- **FR-011**: System MUST log the model name and document/BoK ID for each summarization LLM call at INFO level. Token usage (input/output tokens) MUST be logged at DEBUG level in the LLM adapter to avoid excessive log noise while remaining available for cost analysis.
- **FR-012**: System MUST log all resolved configuration values for new environment variables at startup (INFO level), with API keys masked (e.g., `sk-****`), to support operational debugging.

### Key Entities

- **Summarization LLM Configuration**: A set of provider, model, API key, and temperature settings that define which LLM is used for ingestion summarization tasks. Falls back to the main LLM configuration when not explicitly set.
- **Retrieval Parameters**: A set of tunable values (result count, score threshold, context budget) that control how chunks are retrieved and filtered before being passed to the LLM for response generation.
- **Summarization Threshold**: A numeric parameter that determines the minimum number of chunks a document must contain before summarization is triggered during ingestion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can switch the summarization model without affecting user-facing response quality — summaries are produced by the configured cheaper model while answers remain powered by the primary model.
- **SC-002**: Retrieval result counts for both expert and guidance plugins can be changed via environment variables and take effect without code changes or redeployment.
- **SC-003**: All new configuration parameters have documented defaults that reproduce the current system behavior exactly when the variables are unset.
- **SC-004**: Configuration validation catches 100% of invalid values (wrong types, out-of-range numbers) at startup rather than at runtime.
- **SC-005**: The `.env.example` file documents every new variable with its default value and a brief description.

## Assumptions

- The existing LLM abstraction and provider factory can create multiple LLM instances with different configurations within the same process.
- The summarization LLM does not need different prompt templates — only the underlying model/provider changes.
- The `EXPERT_MIN_SCORE` and `GUIDANCE_MIN_SCORE` thresholds use the same `1.0 - distance` score formula but are configured independently per plugin.
- Environment variables are the appropriate configuration mechanism for this project (consistent with existing configuration patterns).
- The defaults chosen (expert n_results: 5, guidance n_results: 5, expert min score: 0.3, guidance min score: 0.3, max context: 20,000, chunk threshold: 4) match the current hardcoded behavior exactly (FR-009).

## Clarifications

### Session 2026-04-06

- Q: EXPERT_N_RESULTS default is 5 (FR-003) or 10 (User Story 2 scenario 5)? → A: Default is 5 (FR-003 is authoritative; User Story 2 scenario 5 corrected).
- Q: When MAX_CONTEXT_CHARS is exceeded, how should the system truncate? → A: Drop lowest-scoring chunks first until under budget.
- Q: Which providers must the summarization LLM support? → A: All providers the main LLM already supports (OpenAI, Mistral, Anthropic).
- Q: Should the system log which model was used for each summarization call? → A: Yes, log model name + document ID per call at INFO level. Token usage (input/output tokens) logged at DEBUG level per FR-011.
- Q: When the summarization LLM call fails, what should the system do? → A: Retry up to 3 times, then skip summarization and continue ingestion without a summary for that document.
- Q: When SUMMARIZE_LLM_TEMPERATURE is not set but the summarization LLM is otherwise configured, what temperature to use? → A: Default to 0.3 (low temperature suited for summarization), overridable via SUMMARIZE_LLM_TEMPERATURE.
- Q: Should MIN_RETRIEVAL_SCORE be a single global threshold or per-plugin? → A: Per-plugin: EXPERT_MIN_SCORE and GUIDANCE_MIN_SCORE (no global).
- Q: Should per-space/per-knowledge-base configuration be explicitly out of scope? → A: Yes, explicitly out of scope — this feature uses global env vars only.
- Q: When MAX_CONTEXT_CHARS is exceeded and chunks come from both expert and guidance plugins, how does the dropping strategy operate? → A: Budget is enforced per-plugin within the active plugin's merged retrieval set (plugins run in isolated containers). Each plugin drops its lowest-scoring chunks until under budget.
- Q: Should the summarization LLM have its own timeout configuration? → A: Yes, separate `SUMMARIZE_LLM_TIMEOUT` env var, falls back to the main LLM timeout if unset.
- Q: What is the minimum set of SUMMARIZE_LLM_* variables required to activate the separate summarization LLM? → A: All three required: SUMMARIZE_LLM_PROVIDER + SUMMARIZE_LLM_MODEL + SUMMARIZE_LLM_API_KEY. Any subset triggers fallback to the main LLM with a warning.
- Q: Should the system log all resolved configuration values at startup? → A: Yes, log all new env var values at INFO level with API keys masked (e.g., `sk-****`).
