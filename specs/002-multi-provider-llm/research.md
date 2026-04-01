# Research: Multi-Provider LLM Support

**Feature**: 002-multi-provider-llm | **Date**: 2026-04-01

## Decision 1: Unified LangChain Adapter vs Per-Provider Adapters

**Decision**: Use a single unified `LangChainLLMAdapter` that wraps any `BaseChatModel` instance, replacing the per-provider adapters (`MistralAdapter`, `OpenAILLMAdapter`).

**Rationale**: The existing `MistralAdapter` and `OpenAILLMAdapter` are structurally identical — same retry logic, same message conversion, same `invoke`/`stream` signatures. The only difference is which LangChain model class is instantiated. A unified adapter eliminates duplication and means adding a new provider requires zero adapter code — only a factory entry.

**Alternatives considered**:
- **Keep per-provider adapters**: Rejected — leads to N duplicated files with identical logic. Violates DRY. Each new provider would copy-paste the same retry/conversion code.
- **Mixin/base class for shared logic**: Rejected — adds inheritance complexity for no benefit when a single wrapper class suffices.

## Decision 2: Provider Factory Pattern

**Decision**: Introduce a `create_llm_adapter()` factory function in `core/provider_factory.py` that reads a provider name from config and instantiates the correct `BaseChatModel` + wraps it in `LangChainLLMAdapter`.

**Rationale**: The factory centralises provider resolution in one place. It maps provider names to LangChain model classes, validates required config, and returns a ready-to-use `LLMPort` implementation. This is the minimal abstraction needed — a function, not a class hierarchy.

**Alternatives considered**:
- **Abstract factory class hierarchy**: Rejected — over-engineering for a function that maps a string to a constructor call. Violates Simplicity Over Speculation.
- **Plugin-based provider discovery**: Rejected — providers are infrastructure adapters, not domain plugins. The microkernel pattern applies to business logic plugins, not to adapter selection.
- **LangChain's `init_chat_model()` utility**: Considered but rejected — it abstracts away constructor parameters, making it harder to pass provider-specific settings (base_url, generation params) explicitly. Direct instantiation of `ChatMistralAI`, `ChatOpenAI`, `ChatAnthropic` gives full control.

## Decision 3: LangChain ChatAnthropic Integration

**Decision**: Add `langchain-anthropic` as a new dependency. Use `ChatAnthropic(model=..., api_key=..., temperature=..., max_tokens=...)` for Anthropic provider support.

**Rationale**: LangChain provides first-class `ChatAnthropic` integration that implements `BaseChatModel` — same as `ChatMistralAI` and `ChatOpenAI`. All three support `ainvoke()` and `astream()`. Using the LangChain integration maintains consistency with the existing adapter pattern and is the approach specified in the feature spec's clarifications.

**Alternatives considered**:
- **Direct Anthropic SDK**: Rejected — would require custom message conversion and response parsing. LangChain already handles this.
- **Generic HTTP adapter**: Rejected — reinvents what LangChain provides; more code, more bugs.

## Decision 4: OpenAI-Compatible Local Models via `base_url`

**Decision**: Support local/self-hosted models by using `ChatOpenAI` with a custom `base_url` parameter pointing to the local endpoint (vLLM, sglang, Ollama).

**Rationale**: LangChain's `ChatOpenAI` natively supports custom `base_url` for any OpenAI-compatible endpoint. This is documented and proven for vLLM, Ollama, and other local inference servers. No special adapter needed — the OpenAI provider with a non-default base URL covers this use case entirely.

**Alternatives considered**:
- **Dedicated local model adapter**: Rejected — unnecessary since these endpoints implement the OpenAI API spec. `ChatOpenAI(base_url="http://localhost:8000/v1")` works out of the box.
- **Separate "local" provider type**: Rejected — would duplicate OpenAI adapter logic. Instead, the OpenAI provider config accepts an optional `base_url` override.

## Decision 5: Structured Output Strategy

**Decision**: Use LangChain's `with_structured_output()` method where available (OpenAI, Anthropic support `method="json_schema"`). For providers without native support, fall back to the existing prompt-based JSON extraction with defensive parsing (regex fence stripping + `json.loads`).

**Rationale**: `with_structured_output()` is supported by all three target providers via their LangChain integrations. This provides native schema enforcement at the API level. The existing `_parse_json_sources()` logic in the guidance plugin already handles the fallback case (markdown fence stripping). The structured output concern stays in the plugins/domain layer, not in the adapter — the adapter's job is `invoke`/`stream`, not output parsing.

**Alternatives considered**:
- **Move structured output parsing into the adapter**: Rejected — violates Single Responsibility. Structured output is a domain concern (what format does the plugin expect?), not a transport concern (how do I talk to the LLM?).
- **Always use prompt-based extraction**: Rejected — native schema enforcement is more reliable and reduces parsing failures. But prompt-based fallback must remain for providers that don't support it.

## Decision 6: Configuration Schema — Environment Variable Convention

**Decision**: Use a hierarchical environment variable naming convention:
- **Global**: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TOP_P`, `LLM_TIMEOUT`
- **Per-provider override**: `LLM_{PROVIDER}_API_KEY`, `LLM_{PROVIDER}_MODEL`, `LLM_{PROVIDER}_BASE_URL`, `LLM_{PROVIDER}_TEMPERATURE`, `LLM_{PROVIDER}_MAX_TOKENS`, `LLM_{PROVIDER}_TOP_P`
- **Backward compatibility**: `MISTRAL_API_KEY` and `MISTRAL_SMALL_MODEL_NAME` remain functional as aliases

**Rationale**: A consistent `LLM_` prefix groups all LLM-related config together. Per-provider overrides enable FR-012 (per-provider generation parameters). Backward compatibility (FR-009) is maintained by treating the old Mistral env vars as fallback aliases in the config model.

**Alternatives considered**:
- **Flat namespace** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`): Rejected — inconsistent naming, doesn't scale, no clear grouping.
- **YAML/JSON config file**: Rejected — the project uses environment variables exclusively for runtime config. A config file would be a new pattern.

## Decision 7: Per-Plugin Provider Override (P3 — Story 4)

**Decision**: Support per-plugin provider override via environment variables following the pattern `{PLUGIN_NAME}_LLM_PROVIDER`, `{PLUGIN_NAME}_LLM_API_KEY`, etc. (e.g., `GUIDANCE_LLM_PROVIDER=mistral`, `EXPERT_LLM_PROVIDER=anthropic`). This is resolved in `main.py`'s `_create_adapters()` — if plugin-specific config is set, it overrides the global `LLM_*` values.

**Rationale**: Since each plugin runs in its own container (Single Image, Multiple Deployments), per-plugin config is naturally per-container env vars. The simplest approach is: check for plugin-specific vars first, fall back to global vars. No runtime switching needed.

**Alternatives considered**:
- **Runtime provider selection per request**: Rejected — over-complex, not requested. The `external_config` mechanism already exists for per-request overrides in the OpenAI Assistant plugin.
- **Config file per plugin**: Rejected — same reason as Decision 6.

## Decision 8: Retry and Error Handling

**Decision**: Keep retry logic (3 attempts, exponential backoff) in the unified adapter. The adapter catches exceptions from LangChain's `ainvoke`/`astream` and retries. After exhausting retries, the exception propagates to the message handler in `main.py`, which wraps it in an error response envelope.

**Rationale**: The existing retry pattern works well and is consistent across both current adapters. Moving it to the unified adapter preserves this behavior. No automatic failover to a secondary provider (per spec clarification).

**Alternatives considered**:
- **Retry at the factory level**: Rejected — retry is a per-call concern, not a construction concern.
- **Configurable retry count**: Rejected — not requested; 3 retries with exponential backoff is a sensible default. Can be added later if needed (Simplicity Over Speculation).
