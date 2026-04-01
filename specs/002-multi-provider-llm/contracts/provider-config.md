# Contract: Provider Configuration

**Status**: NEW — defines the environment variable interface for LLM provider selection.

## Environment Variable Schema

### Global LLM Configuration

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `LLM_PROVIDER` | `string` | No | `mistral` | Provider identifier: `mistral`, `openai`, `anthropic` |
| `LLM_API_KEY` | `string` | Conditional | — | API key for the selected provider. Required unless using local model with `LLM_BASE_URL`. |
| `LLM_MODEL` | `string` | No | Provider default | Model name (e.g., `gpt-4o`, `claude-sonnet-4-6`) |
| `LLM_BASE_URL` | `string` | No | Provider default | Custom base URL for the provider API or local endpoint |
| `LLM_TEMPERATURE` | `float` | No | Provider default | Generation temperature (0.0–2.0) |
| `LLM_MAX_TOKENS` | `int` | No | Provider default | Maximum response tokens |
| `LLM_TOP_P` | `float` | No | Provider default | Nucleus sampling parameter (0.0–1.0) |
| `LLM_TIMEOUT` | `int` | No | `120` | Global timeout in seconds for LLM invocations |

### Backward Compatibility (FR-009)

| Legacy Variable | Mapped To | Condition |
|----------------|-----------|-----------|
| `MISTRAL_API_KEY` | `LLM_API_KEY` | When `LLM_PROVIDER=mistral` and `LLM_API_KEY` not set |
| `MISTRAL_SMALL_MODEL_NAME` | `LLM_MODEL` | When `LLM_PROVIDER=mistral` and `LLM_MODEL` not set |

### Provider Defaults (FR-013)

| Provider | Default Model | Default Base URL |
|----------|--------------|-----------------|
| `mistral` | `mistral-large-latest` | Mistral API default |
| `openai` | `gpt-4o` | OpenAI API default |
| `anthropic` | `claude-sonnet-4-6` | Anthropic API default |

## Startup Validation (FR-008)

The engine validates provider configuration at startup. Validation failures prevent the engine from starting and produce a descriptive error message.

### Validation Rules

1. **Unknown provider**: `LLM_PROVIDER` value not in `{mistral, openai, anthropic}` → error with list of supported providers
2. **Missing API key**: No `LLM_API_KEY` (or backward-compat alias) and no `LLM_BASE_URL` → error naming which key is expected
3. **Invalid temperature**: `LLM_TEMPERATURE` outside [0.0, 2.0] → error
4. **Invalid max_tokens**: `LLM_MAX_TOKENS` ≤ 0 → error
5. **Invalid top_p**: `LLM_TOP_P` outside [0.0, 1.0] → error

### Error Message Format

```text
Configuration error: Unsupported LLM provider 'gemini'. Supported providers: mistral, openai, anthropic
Configuration error: LLM_API_KEY is required for provider 'anthropic'. Set LLM_API_KEY or provide LLM_BASE_URL for local models.
```

## Startup Logging (FR-010)

At startup, after successful provider resolution, log at INFO level:

```text
LLM provider: mistral | model: mistral-large-latest | base_url: default
LLM provider: openai | model: gpt-4o | base_url: http://localhost:8000/v1
```

## Example Configurations

### Switch from Mistral to OpenAI (Story 1)

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o
```

### Use Anthropic with custom temperature (Story 1 + FR-012)

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-6
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=4096
```

### Local model via vLLM (Story 3)

```env
LLM_PROVIDER=openai
LLM_API_KEY=not-needed
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=meta-llama/Llama-3-8b
```

### Backward-compatible Mistral deployment (FR-009)

```env
# No LLM_* vars set — existing config works unchanged
MISTRAL_API_KEY=existing-key
MISTRAL_SMALL_MODEL_NAME=mistral-small-latest
```

### Per-plugin override — use `{PLUGIN_NAME}_LLM_*` (Story 4)

Per-plugin override is achieved with prefixed variables (falling back to global `LLM_*`):

```yaml
# K8s deployment for guidance plugin
env:
  - name: PLUGIN_TYPE
    value: guidance
  - name: GUIDANCE_LLM_PROVIDER
    value: mistral
  - name: GUIDANCE_LLM_API_KEY
    value: ${MISTRAL_KEY}

# K8s deployment for expert plugin
env:
  - name: PLUGIN_TYPE
    value: expert
  - name: EXPERT_LLM_PROVIDER
    value: anthropic
  - name: EXPERT_LLM_API_KEY
    value: ${ANTHROPIC_KEY}
```
