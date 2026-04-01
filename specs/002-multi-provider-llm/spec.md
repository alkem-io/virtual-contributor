# Feature Specification: Multi-Provider LLM Support

**Feature Branch**: `002-multi-provider-llm`  
**Created**: 2026-04-01  
**Status**: Draft  
**Input**: User description: "Multi-provider LLM support for the unified virtual-contributor engine. Make the engine provider-agnostic so any LLM provider can be used by changing configuration, without code changes."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Switch LLM Provider via Configuration (Priority: P1)

A platform operator wants to switch the LLM provider for a virtual contributor engine (e.g., from Mistral to OpenAI) by changing environment variables only — no code changes, no image rebuilds, no redeployment beyond a container restart.

**Why this priority**: This is the core value proposition. Without configuration-driven provider selection, none of the other stories matter.

**Independent Test**: Can be tested by starting the engine with a different provider setting and valid credentials, sending a message via RabbitMQ, and verifying a valid response is returned in the same envelope format as the current Mistral-based engine.

**Acceptance Scenarios**:

1. **Given** the engine is configured with Mistral as the provider and valid credentials, **When** a query message arrives on the RabbitMQ queue, **Then** the engine invokes the Mistral API and returns a valid response envelope.
2. **Given** the engine is configured with OpenAI as the provider and valid credentials, **When** the same query message arrives, **Then** the engine invokes the OpenAI API and returns a response in the identical envelope format.
3. **Given** the engine is configured with Anthropic as the provider and valid credentials, **When** a query message arrives, **Then** the engine returns a valid response envelope.
4. **Given** an unsupported provider value is set, **When** the engine starts, **Then** it fails fast with a clear error message naming the unsupported provider and listing supported options.

---

### User Story 2 - Consistent Structured Output Across Providers (Priority: P1)

Plugins that expect structured JSON responses from the LLM (e.g., the guidance plugin expects a JSON object with an `answer` field that is extracted as the response text) must receive reliably parsed output regardless of which provider is used — even if the raw LLM response contains markdown fences, preamble text, or inconsistent formatting. Source relevance scores are computed separately from ChromaDB query distances, not extracted from the LLM response.

**Why this priority**: Without structured output normalization, provider switching breaks plugin logic. This is a prerequisite for Story 1 to work end-to-end.

**Independent Test**: Send the same guidance query through each supported provider. Verify that all produce a response where the `answer` field is extracted as a non-empty string and the source filtering logic works correctly.

**Acceptance Scenarios**:

1. **Given** a guidance query is processed by any supported provider, **When** the LLM returns its response, **Then** the engine extracts a structured JSON object containing at minimum an `answer` string field (used as the response text). Source scores are derived from ChromaDB distance metrics, not from the LLM response.
2. **Given** the LLM wraps its JSON response in markdown code fences, **When** the output is parsed, **Then** the engine strips the fences and successfully extracts the structured data.
3. **Given** the LLM returns malformed or unparseable output, **When** parsing fails, **Then** the engine falls back to returning the raw text as the `result` field and logs a warning — it does not crash or produce an error response.

---

### User Story 3 - Use a Local/Self-Hosted Model (Priority: P2)

A platform operator wants to use a self-hosted model (e.g., via sglang, vLLM, or Ollama) by pointing the engine at a local OpenAI-compatible endpoint, without needing a cloud API key.

**Why this priority**: Supports on-premises deployments and cost optimization. Builds on the provider abstraction from P1 stories.

**Independent Test**: Start the engine with an OpenAI-compatible provider pointing to a local endpoint. Send a query and verify a valid response.

**Acceptance Scenarios**:

1. **Given** the engine is configured with an OpenAI-compatible provider pointing to a local endpoint, **When** a query arrives, **Then** the engine sends the request to the local endpoint and returns a valid response.
2. **Given** the local endpoint is unreachable, **When** the engine attempts to invoke the LLM, **Then** it returns an error response with a meaningful message and does not hang indefinitely.

---

### User Story 4 - Per-Plugin Provider Override (Priority: P3)

A platform operator wants to use different providers for different plugins — e.g., Mistral for guidance (cost-effective RAG) and Anthropic for the expert engine (better reasoning). This is achieved by setting plugin-specific environment variables that override the global defaults.

**Why this priority**: Advanced use case that provides flexibility for optimized deployments. Not needed for initial provider-agnostic support.

**Independent Test**: Start two plugin instances: guidance with one provider and expert with a different provider. Send queries to each and verify they use their respective providers.

**Acceptance Scenarios**:

1. **Given** a global provider is set and a specific plugin has a provider override, **When** that plugin processes a query, **Then** it uses the overridden provider.
2. **Given** no per-plugin override is set, **When** a plugin processes a query, **Then** it uses the global provider configuration.

---

### Edge Cases

- What happens when the configured provider's API returns a rate limit error? The engine should retry with backoff (existing behavior) and eventually return an error response if retries are exhausted. There is no automatic failover to a secondary provider — the engine uses only the single configured provider (or per-plugin override) and surfaces the error.
- What happens when a provider is configured but the model name is invalid for that provider? The engine should surface the provider's error message in the response.
- What happens when the LLM returns an empty response? The engine should return a fallback message indicating the model returned no content.
- What happens when the structured output schema enforcement is not natively supported by the provider? The engine should fall back to prompt-based JSON extraction with defensive parsing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support at least three LLM providers: Mistral, OpenAI-compatible (including local models), and Anthropic.
- **FR-002**: System MUST select the LLM provider based on a configuration value with no code changes required.
- **FR-003**: System MUST produce identical RabbitMQ response envelope format regardless of which provider is used — the downstream server must not be able to distinguish which provider generated the response.
- **FR-004**: System MUST enforce structured output schemas on LLM responses for plugins that require structured data (e.g., the guidance plugin's JSON format with an `answer` field). Source relevance scores are derived from vector store distances, not from LLM output.
- **FR-005**: System MUST gracefully handle LLM responses that do not conform to the expected structure by falling back to raw text extraction rather than failing.
- **FR-006**: System MUST support custom base URLs for each provider to enable proxy routing and self-hosted model endpoints.
- **FR-007**: System MUST support provider-specific configuration (API key, base URL, model name) via environment variables following a consistent naming convention.
- **FR-008**: System MUST fail fast at startup with a descriptive error if the configured provider is not supported or required credentials are missing.
- **FR-009**: System MUST maintain backward compatibility — existing deployments using Mistral with current environment variables must continue to work without configuration changes.
- **FR-010**: System MUST log the active provider name and model at startup and on configuration change (not per request), at INFO level, to support operational visibility.
- **FR-011**: System MUST enforce a single global timeout for LLM invocations, configurable via environment variable. No per-provider timeout overrides.
- **FR-012**: System MUST support per-provider configuration of LLM generation parameters (temperature, max_tokens, top_p) via environment variables. Each provider can have independently tuned parameters to account for provider-specific behavior differences.
- **FR-013**: Each provider adapter MUST define a sensible default model name (e.g., `mistral-large-latest` for Mistral, `gpt-4o` for OpenAI, `claude-sonnet-4-6` for Anthropic). The operator MAY override the default via environment variable. When no model is explicitly configured, the default is used and no error is raised.

### Key Entities

- **LLM Provider**: Represents a supported LLM backend (Mistral, OpenAI, Anthropic). Characterized by an API protocol, authentication method, and model catalog.
- **Structured Output Schema**: Defines the expected response format for plugins that require structured data from the LLM. Includes field names, types, and optionality.
- **Provider Configuration**: The set of credentials and settings (API key, base URL, model name, generation parameters: temperature, max_tokens, top_p) needed to connect to a specific provider.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The engine can be switched between at least 3 providers by changing only environment variables — zero code changes required.
- **SC-002**: All 6 existing plugins produce valid response envelopes with any supported provider — verified by sending the same test message and comparing envelope structure.
- **SC-003**: The guidance plugin returns parseable structured responses (with `result` field present) for at least 95% of queries across all supported providers.
- **SC-004**: Existing Mistral-based deployments continue to work without any configuration changes after the upgrade.
- **SC-005**: A new provider can be added by creating a single adapter — no changes to plugins, router, or transport layer.

## Clarifications

### Session 2026-04-01

- Q: Should the engine auto-failover to a secondary provider on outage? → A: No — return error after retries are exhausted; no automatic failover.
- Q: Is streaming (token-by-token delivery) in scope? → A: Explicitly out of scope for this feature.
- Q: Should the engine log/emit metrics identifying which provider handled each request? → A: Log provider name + model at startup/config change only; not per request; no new metrics infrastructure.
- Q: Should per-provider timeout configuration be supported? → A: No — single global timeout for all providers; no per-provider override.
- Q: Should the provider abstraction use LangChain or custom adapters? → A: Use LangChain's chat model abstraction (BaseChatModel implementations).
- Q: Should LLM generation parameters (temperature, max_tokens, etc.) be configurable, and at what granularity? → A: Fully configurable per provider via env vars (temperature, max_tokens, top_p per provider).
- Q: Should provider adapters define default model names, or must the operator always specify the model? → A: Each provider has a sensible default model; operator can override via env var.

## Assumptions

- All target LLM providers support system messages and multi-turn conversation history.
- Structured output enforcement is available natively for the primary target providers, with prompt-based fallback for providers that lack native schema support.
- The existing sglang proxy infrastructure remains available for local model deployments and can be accessed via the OpenAI-compatible provider.
- Provider-specific prompt tuning (beyond structured output schema) is out of scope for the initial implementation — the same prompts are used across providers.
- The provider abstraction layer is built on LangChain's `BaseChatModel` implementations (`ChatMistralAI`, `ChatOpenAI`, `ChatAnthropic`), leveraging the existing project dependency on `langchain ^1.1.0`.
- Embeddings provider selection is a separate concern and out of scope for this feature.
- Streaming (token-by-token response delivery) is out of scope — all providers return complete responses via the existing RabbitMQ request/response envelope model.
- The platform operator (not the end user) is the person configuring provider settings.
