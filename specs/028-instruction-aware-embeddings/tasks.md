# Tasks: Instruction-Aware Embeddings

**Branch**: `028-instruction-aware-embeddings` | **Date**: 2026-04-23 | **Spec**: [spec.md](spec.md)

---

## Phase 1: US1 -- Retrieval Query Instruction Wrapping

### Task 1.1: Add `embed_query()` to `EmbeddingsPort` protocol
- [X] Add `embed_query(self, texts: list[str]) -> list[list[float]]` method to `EmbeddingsPort`
- [X] Update docstrings: `embed()` is for indexing, `embed_query()` is for retrieval
- **File**: `core/ports/embeddings.py`

### Task 1.2: Define `QWEN3_RETRIEVAL_INSTRUCTION` constant
- [X] Add module-level constant with the Qwen3 retrieval instruction prefix
- [X] Value: `"Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "`
- **File**: `core/adapters/openai_compatible_embeddings.py`

### Task 1.3: Implement `_resolve_query_instruction()` helper
- [X] Accept `model_name: str` and `explicit: str | None`
- [X] If `explicit is not None`, return it verbatim (including empty string)
- [X] If model name starts with `qwen3-embedding` (case-insensitive), return `QWEN3_RETRIEVAL_INSTRUCTION`
- [X] Otherwise return empty string
- **File**: `core/adapters/openai_compatible_embeddings.py`

### Task 1.4: Refactor `embed()` to delegate to `_call()`
- [X] Extract HTTP call logic (retry loop, httpx client, response parsing) into `_call(texts)` private method
- [X] `embed()` becomes one-liner: `return await self._call(texts)`
- **File**: `core/adapters/openai_compatible_embeddings.py`

### Task 1.5: Implement `embed_query()` on `OpenAICompatibleEmbeddingsAdapter`
- [X] Prepend `self._query_instruction` to each text if non-empty
- [X] Delegate to `self._call(texts)`
- **File**: `core/adapters/openai_compatible_embeddings.py`

### Task 1.6: Update `ChromaDBAdapter.query()` to call `embed_query()`
- [X] Change `await self._embeddings.embed(query_texts)` to `await self._embeddings.embed_query(query_texts)`
- [X] Update `EmbedFn` protocol to require both `embed()` and `embed_query()` methods
- **File**: `core/adapters/chromadb.py`

---

## Phase 2: US2 -- Auto-Detection and Configurable Override

### Task 2.1: Add `query_instruction` constructor parameter
- [X] Add `query_instruction: str | None = None` to `OpenAICompatibleEmbeddingsAdapter.__init__`
- [X] Call `_resolve_query_instruction(model_name, query_instruction)` and store result
- [X] Log instruction info when prefix is non-empty
- **File**: `core/adapters/openai_compatible_embeddings.py`

### Task 2.2: Add `embeddings_query_instruction` config field
- [X] Add `embeddings_query_instruction: str | None = None` field to `BaseConfig`
- [X] Add inline comment explaining the three-state behavior (None/empty/"value")
- **File**: `core/config.py`

### Task 2.3: Wire config value to adapter in `main.py`
- [X] Pass `query_instruction=config.embeddings_query_instruction` to `OpenAICompatibleEmbeddingsAdapter` constructor
- **File**: `main.py`

---

## Phase 3: US3 -- Backward Compatibility

### Task 3.1: Implement `embed_query()` on `OpenAIEmbeddingsAdapter`
- [X] Add `embed_query()` that delegates directly to `embed()`
- [X] Update class docstring to note OpenAI models are not instruction-aware
- **File**: `core/adapters/openai_embeddings.py`

### Task 3.2: Update `MockEmbeddingsPort` in test fixtures
- [X] Add `query_calls: list[list[str]]` tracking list
- [X] Add `embed_query()` method that appends to `query_calls` and returns mock embeddings
- **File**: `tests/conftest.py`

---

## Phase 4: Testing

### Task 4.1: Create test package `tests/core/adapters/`
- [X] Create `tests/core/adapters/__init__.py` (empty package marker)
- **File**: `tests/core/adapters/__init__.py`

### Task 4.2: Test instruction resolution -- Qwen3 auto-detection
- [X] Test that `qwen3-embedding-8b` auto-wraps with `QWEN3_RETRIEVAL_INSTRUCTION`
- [X] Test that mixed-case `Qwen3-Embedding-0.6B` also auto-wraps
- **File**: `tests/core/adapters/test_openai_compatible_embeddings.py`

### Task 4.3: Test instruction resolution -- non-Qwen3 default
- [X] Test that `text-embedding-3-small` produces empty instruction
- **File**: `tests/core/adapters/test_openai_compatible_embeddings.py`

### Task 4.4: Test instruction resolution -- explicit override
- [X] Test that explicit `query_instruction="Custom: "` overrides Qwen3 auto-detection
- [X] Test that explicit `query_instruction=""` disables wrapping for Qwen3 model
- **File**: `tests/core/adapters/test_openai_compatible_embeddings.py`

### Task 4.5: Test wrapping behavior -- `embed()` never wraps
- [X] Test that `embed()` sends raw texts to API even for Qwen3 model
- **File**: `tests/core/adapters/test_openai_compatible_embeddings.py`

### Task 4.6: Test wrapping behavior -- `embed_query()` wraps
- [X] Test that `embed_query()` prepends Qwen3 instruction to each text
- [X] Test that `embed_query()` sends raw texts when instruction is empty
- [X] Test that `embed_query()` uses custom instruction when configured
- **File**: `tests/core/adapters/test_openai_compatible_embeddings.py`
