# Quickstart: Instruction-Aware Embeddings

**Branch**: `028-instruction-aware-embeddings` | **Date**: 2026-04-23

---

## Prerequisites

- Python 3.12 with Poetry
- Running embedding provider with OpenAI-compatible API (Scaleway, vLLM, Ollama, etc.)
- Running ChromaDB instance (for retrieval verification)
- Running RabbitMQ instance (for event-driven mode) or ability to run standalone

---

## New Environment Variable

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EMBEDDINGS_QUERY_INSTRUCTION` | `str` or unset | unset (`None`) | Instruction prefix for retrieval queries. When unset, Qwen3 models auto-apply the retrieval instruction. Set to a custom string to override. Set to empty string `""` to disable wrapping. |

---

## Verification Steps

### 1. Deploy with a Qwen3-Embedding model (auto-detection)

```bash
EMBEDDINGS_MODEL_NAME=qwen3-embedding-8b \
EMBEDDINGS_API_KEY=your-key \
EMBEDDINGS_ENDPOINT=https://your-provider/v1 \
PLUGIN_TYPE=expert \
poetry run python main.py
```

Check logs for the auto-detection confirmation:

```text
INFO  Embeddings adapter will wrap queries with instruction (model=qwen3-embedding-8b, prefix_len=88)
```

This confirms the Qwen3 retrieval instruction was auto-applied.

### 2. Deploy with a non-Qwen3 model (no wrapping)

```bash
EMBEDDINGS_MODEL_NAME=text-embedding-3-small \
EMBEDDINGS_API_KEY=your-key \
EMBEDDINGS_ENDPOINT=https://your-provider/v1 \
PLUGIN_TYPE=expert \
poetry run python main.py
```

The "wrap queries with instruction" log line should NOT appear.

### 3. Deploy with explicit override

```bash
EMBEDDINGS_MODEL_NAME=some-custom-model \
EMBEDDINGS_QUERY_INSTRUCTION="Search: " \
EMBEDDINGS_API_KEY=your-key \
EMBEDDINGS_ENDPOINT=https://your-provider/v1 \
PLUGIN_TYPE=expert \
poetry run python main.py
```

Check logs for:

```text
INFO  Embeddings adapter will wrap queries with instruction (model=some-custom-model, prefix_len=8)
```

### 4. Deploy with wrapping explicitly disabled

```bash
EMBEDDINGS_MODEL_NAME=qwen3-embedding-8b \
EMBEDDINGS_QUERY_INSTRUCTION="" \
EMBEDDINGS_API_KEY=your-key \
EMBEDDINGS_ENDPOINT=https://your-provider/v1 \
PLUGIN_TYPE=expert \
poetry run python main.py
```

The "wrap queries with instruction" log line should NOT appear, even though the model is Qwen3.

---

## Running Tests

```bash
# All tests
poetry run pytest tests/ -v

# Instruction-aware adapter tests only
poetry run pytest tests/core/adapters/test_openai_compatible_embeddings.py -v
```

Expected output: 9 tests pass.

---

## Files Changed

| File | Change |
|------|--------|
| `core/ports/embeddings.py` | Added `embed_query()` method to `EmbeddingsPort` protocol |
| `core/adapters/openai_compatible_embeddings.py` | Added `QWEN3_RETRIEVAL_INSTRUCTION`, `_resolve_query_instruction()`, `_call()`, `embed_query()`, `query_instruction` constructor param |
| `core/adapters/openai_embeddings.py` | Added `embed_query()` as alias for `embed()` |
| `core/adapters/chromadb.py` | `query()` calls `embed_query()` instead of `embed()`, `EmbedFn` protocol updated |
| `core/config.py` | Added `embeddings_query_instruction` field |
| `main.py` | Wires `config.embeddings_query_instruction` to adapter constructor |
| `tests/conftest.py` | `MockEmbeddingsPort` gains `embed_query()` with `query_calls` tracking |
| `tests/core/adapters/__init__.py` | New empty package marker |
| `tests/core/adapters/test_openai_compatible_embeddings.py` | New test module with 9 tests |
