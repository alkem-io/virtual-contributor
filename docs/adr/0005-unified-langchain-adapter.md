# ADR 0005: Unified LangChain Adapter with Provider Factory

## Status
Accepted

## Context
The codebase has two per-provider LLM adapters (`MistralAdapter` in `core/adapters/mistral.py` and `OpenAILLMAdapter` in `core/adapters/openai_llm.py`) that are structurally identical — same retry logic, same message conversion, same `invoke`/`stream` signatures. The only difference is which LangChain model class (`ChatMistralAI` vs `ChatOpenAI`) is instantiated. Adding Anthropic support would mean a third copy of the same code. Selecting a provider requires code changes in `main.py`.

## Decision
Replace all per-provider adapters with:

1. **A unified `LangChainLLMAdapter`** (`core/adapters/langchain_llm.py`) that wraps any LangChain `BaseChatModel` instance and implements `LLMPort`. Contains retry logic (3 attempts, exponential backoff), message conversion (dict → LangChain message types), and streaming support — once, not per provider.

2. **A `create_llm_adapter()` factory function** (`core/provider_factory.py`) that reads provider configuration and returns a ready-to-use `LangChainLLMAdapter`. Maps `LLMProvider` enum values to LangChain model classes (`ChatMistralAI`, `ChatOpenAI`, `ChatAnthropic`) with default models per provider. Provider selection is driven entirely by environment variables (`LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, etc.).

3. **Backward-compatible configuration**: Existing `MISTRAL_API_KEY` and `MISTRAL_SMALL_MODEL_NAME` environment variables continue to work as fallback aliases when `LLM_PROVIDER=mistral` (the default).

## Consequences
- **Positive**: Adding a new provider requires only a factory dict entry and a `pyproject.toml` dependency — zero adapter code.
- **Positive**: Eliminates duplicated retry, message conversion, and streaming logic across adapters.
- **Positive**: Provider switching is a configuration concern — no code changes, no rebuild.
- **Positive**: Existing Mistral deployments work unchanged (backward compatibility via env var aliases).
- **Negative**: Depends on LangChain's `BaseChatModel` abstraction — all supported providers must have LangChain integrations.
- **Negative**: Provider-specific features (e.g., native tool calling differences) are not exposed through the unified adapter.
