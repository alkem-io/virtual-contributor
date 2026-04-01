# Data Model: Multi-Provider LLM Support

**Feature**: 002-multi-provider-llm | **Date**: 2026-04-01

## Entities

### 1. LLMProvider (Enum)

Enumerates supported LLM provider backends.

| Value | Description | LangChain Class |
|-------|-------------|-----------------|
| `mistral` | Mistral AI (default, backward-compatible) | `ChatMistralAI` |
| `openai` | OpenAI and OpenAI-compatible endpoints | `ChatOpenAI` |
| `anthropic` | Anthropic Claude models | `ChatAnthropic` |

**Validation**: Must be one of the enumerated values. Invalid values trigger fail-fast at startup (FR-008).

### 2. ProviderConfig (Value Object)

Configuration for a single LLM provider instance. Resolved from environment variables at startup.

| Field | Type | Required | Default | Env Var Pattern |
|-------|------|----------|---------|-----------------|
| `provider` | `LLMProvider` | Yes | `mistral` | `LLM_PROVIDER` |
| `api_key` | `str` | Yes* | — | `LLM_API_KEY` |
| `model` | `str` | No | Provider-specific default | `LLM_MODEL` |
| `base_url` | `str \| None` | No | Provider default | `LLM_BASE_URL` |
| `temperature` | `float \| None` | No | Provider default | `LLM_TEMPERATURE` |
| `max_tokens` | `int \| None` | No | Provider default | `LLM_MAX_TOKENS` |
| `top_p` | `float \| None` | No | Provider default | `LLM_TOP_P` |
| `timeout` | `int` | No | `120` | `LLM_TIMEOUT` |

\* `api_key` is required unless `base_url` points to a local endpoint (some local models don't require auth). Validation: if no `api_key` and no `base_url`, fail-fast with descriptive error.

**Default models per provider** (FR-013):

| Provider | Default Model |
|----------|--------------|
| `mistral` | `mistral-large-latest` |
| `openai` | `gpt-4o` |
| `anthropic` | `claude-sonnet-4-6` |

### 3. LLMConfigSection (Pydantic Settings Model)

Extension to `BaseConfig` that replaces the current Mistral-only fields. Lives in `core/config.py`.

```python
# New fields added to BaseConfig
llm_provider: str = "mistral"          # LLM_PROVIDER
llm_api_key: str | None = None         # LLM_API_KEY
llm_model: str | None = None           # LLM_MODEL
llm_base_url: str | None = None        # LLM_BASE_URL
llm_temperature: float | None = None   # LLM_TEMPERATURE
llm_max_tokens: int | None = None      # LLM_MAX_TOKENS
llm_top_p: float | None = None         # LLM_TOP_P
llm_timeout: int = 120                 # LLM_TIMEOUT

# Backward compatibility aliases (FR-009)
mistral_api_key: str | None = None     # MISTRAL_API_KEY (existing)
mistral_model_name: str | None = None  # MISTRAL_SMALL_MODEL_NAME (existing)
```

**Resolution precedence** (for Mistral backward compatibility):
1. `LLM_API_KEY` → used directly
2. If `LLM_API_KEY` not set and `LLM_PROVIDER` is `mistral` → fall back to `MISTRAL_API_KEY`
3. `LLM_MODEL` → used directly
4. If `LLM_MODEL` not set and `LLM_PROVIDER` is `mistral` → fall back to `MISTRAL_SMALL_MODEL_NAME`

### 4. LangChainLLMAdapter (Adapter)

Unified adapter wrapping any LangChain `BaseChatModel`. Implements `LLMPort`.

| Method | Input | Output | Behavior |
|--------|-------|--------|----------|
| `invoke(messages)` | `list[dict]` | `str` | Convert to LangChain messages → `ainvoke` → extract `.content` → return string. Retry 3× with exponential backoff. |
| `stream(messages)` | `list[dict]` | `AsyncIterator[str]` | Convert to LangChain messages → `astream` → yield `.content` chunks. No retry (streaming). |

**Constructor**: `__init__(self, llm: BaseChatModel)` — receives an already-configured LangChain model instance.

**Message conversion** (shared, extracted from existing adapters):

| Input `role` | LangChain Type |
|-------------|---------------|
| `"system"` | `SystemMessage` |
| `"assistant"` / `"ai"` | `AIMessage` |
| `"human"` / other | `HumanMessage` |

## Relationships

```text
BaseConfig ──contains──▶ LLMProvider (enum field)
BaseConfig ──contains──▶ provider config fields (flat Pydantic fields)
     │
     ▼
create_llm_adapter(config) ──reads──▶ BaseConfig fields
     │                      ──maps──▶ LLMProvider → BaseChatModel class
     │                      ──returns──▶ LangChainLLMAdapter
     ▼
LangChainLLMAdapter ──wraps──▶ BaseChatModel (ChatMistralAI | ChatOpenAI | ChatAnthropic)
     │
     ▼
Container ──registers──▶ LLMPort → LangChainLLMAdapter instance
     │
     ▼
Plugins ──receive via DI──▶ LLMPort (unchanged interface)
```

## State Transitions

### Provider Resolution (Startup)

```text
[Config loaded] 
  → Validate LLM_PROVIDER is supported
    → ❌ FAIL FAST: "Unsupported LLM provider '{value}'. Supported: mistral, openai, anthropic"
    → ✅ Resolve API key (LLM_API_KEY or backward-compat alias)
      → ❌ FAIL FAST: "LLM_API_KEY required for provider '{provider}'" (unless base_url set for local models)
      → ✅ Resolve model name (LLM_MODEL or provider default)
        → Instantiate BaseChatModel with all config
          → Wrap in LangChainLLMAdapter
            → Register as LLMPort in Container
              → [Ready]
```

### Backward Compatibility (FR-009)

```text
[Existing deployment — only MISTRAL_API_KEY set]
  → LLM_PROVIDER defaults to "mistral"
  → LLM_API_KEY not set → falls back to MISTRAL_API_KEY ✅
  → LLM_MODEL not set → falls back to MISTRAL_SMALL_MODEL_NAME or default ✅
  → Result: identical behavior to current system
```

## Validation Rules

1. `LLM_PROVIDER` must be a valid `LLMProvider` enum value
2. API key must be present for cloud providers (Mistral, OpenAI without base_url, Anthropic)
3. `LLM_TEMPERATURE` if set: 0.0 ≤ value ≤ 2.0
4. `LLM_MAX_TOKENS` if set: value > 0
5. `LLM_TOP_P` if set: 0.0 ≤ value ≤ 1.0
6. `LLM_TIMEOUT` if set: value > 0
7. Backward compat: if only `MISTRAL_API_KEY` is set (no `LLM_*` vars), system works as before
