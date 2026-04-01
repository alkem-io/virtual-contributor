# Contract: LLMPort Interface

**Status**: UNCHANGED — this contract is stable and not modified by this feature.

## Interface Definition

```python
@runtime_checkable
class LLMPort(Protocol):
    """Port for LLM chat completion interactions."""

    async def invoke(self, messages: list[dict]) -> str:
        """Single chat completion call.
        
        Args:
            messages: List of message dicts with "role" and "content" keys.
                      Roles: "system", "human", "assistant"/"ai".
        
        Returns:
            The LLM's text response as a string.
        
        Raises:
            Exception: After retry exhaustion, propagates the provider's error.
        """
        ...

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Streaming chat completion call.
        
        Args:
            messages: Same format as invoke().
        
        Yields:
            Text chunks as they arrive from the provider.
        """
        ...
```

## Message Format

```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "human", "content": "What is Alkemio?"},
  {"role": "assistant", "content": "Alkemio is a platform for..."},
  {"role": "human", "content": "Tell me more."}
]
```

## Guarantees

1. **Provider-agnostic**: Any adapter implementing this protocol is interchangeable (Liskov Substitution).
2. **Async**: Both methods are `async`. `invoke` awaits the full response; `stream` yields incrementally.
3. **Retry**: `invoke` retries up to 3 times with exponential backoff. `stream` does not retry.
4. **String output**: `invoke` always returns a `str`. Structured parsing is the caller's responsibility.
5. **Role mapping**: The adapter maps roles to provider-specific message types internally.

## Consumers

| Consumer | Methods Used |
|----------|-------------|
| GenericPlugin | `invoke` |
| ExpertPlugin | `invoke` (via PromptGraph) |
| GuidancePlugin | `invoke` |
| IngestWebsitePlugin | `invoke` (summarization) |
| IngestSpacePlugin | `invoke` (summarization) |
| PromptGraph | Both (passed as LangChain model directly) |
| SummarizeGraph | `invoke` |
