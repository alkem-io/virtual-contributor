# Quickstart: Multi-Provider LLM Support

## Prerequisites

- Python 3.12+
- Poetry
- Running RabbitMQ instance
- API key for at least one LLM provider (Mistral, OpenAI, or Anthropic)

## 1. Install dependencies

```bash
poetry install
```

This installs all providers including the new `langchain-anthropic` dependency.

## 2. Configure your provider

Copy `.env.example` to `.env` and set the LLM provider:

### Option A: OpenAI

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-openai-key
LLM_MODEL=gpt-4o          # optional, this is the default
```

### Option B: Anthropic

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-your-key
LLM_MODEL=claude-sonnet-4-6   # optional, this is the default
```

### Option C: Mistral (default — backward compatible)

```env
# Either new-style:
LLM_PROVIDER=mistral
LLM_API_KEY=your-mistral-key

# Or existing-style (still works):
MISTRAL_API_KEY=your-mistral-key
```

### Option D: Local model (vLLM / sglang / Ollama)

```env
LLM_PROVIDER=openai
LLM_API_KEY=not-needed
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=meta-llama/Llama-3-8b
```

## 3. Optional: Tune generation parameters

```env
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=4096
LLM_TOP_P=0.9
LLM_TIMEOUT=120
```

## 4. Run the engine

```bash
PLUGIN_TYPE=generic poetry run python main.py
```

The startup log confirms the active provider:

```text
INFO  LLM provider: openai | model: gpt-4o | base_url: default
INFO  Engine ready — consuming from virtual-contributor-engine-generic
```

## 5. Run tests

```bash
poetry run pytest
```

## 6. Verify provider switching

Switch providers by changing only env vars — no code changes, no rebuild:

```bash
# Test with OpenAI
LLM_PROVIDER=openai LLM_API_KEY=sk-... PLUGIN_TYPE=generic poetry run python main.py

# Test with Anthropic
LLM_PROVIDER=anthropic LLM_API_KEY=sk-ant-... PLUGIN_TYPE=generic poetry run python main.py
```

Both produce identical RabbitMQ response envelopes. The downstream server cannot distinguish which provider generated the response.

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Unsupported LLM provider 'X'` | Invalid `LLM_PROVIDER` value | Use: `mistral`, `openai`, or `anthropic` |
| `LLM_API_KEY is required` | No API key configured | Set `LLM_API_KEY` env var |
| `Connection refused` (local model) | Local endpoint not running | Start vLLM/sglang/Ollama first |
| Works with Mistral but not OpenAI | Different prompt expectations | Check model-specific output; structured output parsing handles format differences |
