# Feature Specification: Instruction-Aware Embeddings

**Feature Branch**: `028-instruction-aware-embeddings`
**Created**: 2026-04-23
**Status**: Implemented
**Input**: Retrospec from code changes

---

## Overview

Split the `EmbeddingsPort` protocol into two semantic operations: `embed()` for document indexing and `embed_query()` for retrieval queries. Instruction-aware embedding models such as Qwen3-Embedding produce significantly better retrieval ranking when queries are wrapped with a task-specific instruction prefix. The `embed_query()` method handles this wrapping transparently at the adapter level, while `embed()` keeps documents in the plain embedding space.

---

## User Scenarios & Testing

### US1 (P1): Retrieval queries use instruction-wrapped embeddings for better ranking

**As** an operator deploying instruction-aware embedding models,
**I want** retrieval queries to be automatically wrapped with the model's recommended instruction prefix,
**so that** RAG retrieval ranking improves without any changes to plugin code.

**Acceptance criteria:**
- `EmbeddingsPort` defines both `embed(texts)` and `embed_query(texts)` methods.
- `ChromaDBAdapter.query()` calls `embed_query()` instead of `embed()` for computing query embeddings.
- The `OpenAICompatibleEmbeddingsAdapter.embed_query()` method prepends the configured instruction prefix to each query text before calling the embedding API.
- `embed()` never wraps -- documents are always embedded in the plain space.
- Retrieval results improve for Qwen3-Embedding models compared to using plain `embed()` for queries.

### US2 (P2): Auto-detection of Qwen3 models with configurable override

**As** an operator,
**I want** Qwen3 models to be auto-detected and wrapped with the correct retrieval instruction without manual configuration,
**so that** deploying a Qwen3 model works optimally out of the box, while still allowing explicit override.

**Acceptance criteria:**
- Model names starting with `qwen3-embedding` (case-insensitive) automatically use the Qwen3 retrieval instruction constant.
- An explicit `query_instruction` constructor parameter (or `EMBEDDINGS_QUERY_INSTRUCTION` env var) overrides auto-detection.
- Setting `query_instruction=""` (empty string) explicitly disables wrapping even for Qwen3 models.
- Setting `query_instruction` to `None` (or not setting the env var) triggers auto-detection.

### US3 (P3): Backward compatibility -- existing non-instruction models work unchanged

**As** an operator using OpenAI or other non-instruction-aware models,
**I want** the system to work identically to before this change,
**so that** upgrading does not require any configuration changes.

**Acceptance criteria:**
- `OpenAIEmbeddingsAdapter.embed_query()` delegates to `embed()` without any wrapping (OpenAI models are not instruction-aware).
- Non-Qwen3 models in `OpenAICompatibleEmbeddingsAdapter` receive no instruction prefix by default.
- `MockEmbeddingsPort` in test fixtures implements both `embed()` and `embed_query()` with separate call tracking.
- All existing tests pass without modification.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Qwen3 model name with mixed case (e.g., `Qwen3-Embedding-0.6B`) | Auto-detected via case-insensitive comparison |
| Non-Qwen3 model with no explicit instruction | `embed_query()` behaves identically to `embed()` |
| Explicit empty string instruction on Qwen3 model | Wrapping disabled; `embed_query()` passes raw text |
| Explicit custom instruction on non-Qwen3 model | Custom prefix applied to all query texts |
| `EMBEDDINGS_QUERY_INSTRUCTION` env var not set | `None` passed to adapter; auto-detection applies |
| ChromaDB query with no embeddings adapter | `ValueError` raised (existing behavior preserved) |
| Empty query text list | Returns empty list (no API call needed) |

---

## Requirements

### FR-001: EmbeddingsPort protocol gains `embed_query()` method

The `EmbeddingsPort` protocol shall define `embed_query(texts: list[str]) -> list[list[float]]` as a separate method from `embed()`. The docstring shall explain the semantic distinction: `embed()` is for indexing, `embed_query()` is for retrieval with optional instruction wrapping.

### FR-002: OpenAICompatibleEmbeddingsAdapter auto-detects Qwen3 models

The `_resolve_query_instruction()` function shall check if the model name starts with `qwen3-embedding` (case-insensitive). When matched and no explicit instruction is provided, it shall return the `QWEN3_RETRIEVAL_INSTRUCTION` constant.

### FR-003: Explicit query instruction override

The `OpenAICompatibleEmbeddingsAdapter` constructor shall accept an optional `query_instruction: str | None` parameter. When provided (including empty string `""`), it shall be used verbatim, overriding auto-detection. When `None`, auto-detection applies.

### FR-004: Adapter `_call()` refactor

The `OpenAICompatibleEmbeddingsAdapter` shall extract the HTTP call logic into a private `_call(texts)` method. Both `embed()` and `embed_query()` shall delegate to `_call()`, with `embed_query()` prepending the instruction prefix before delegation.

### FR-005: OpenAI adapter backward compatibility

The `OpenAIEmbeddingsAdapter` shall implement `embed_query()` as a direct delegation to `embed()`. OpenAI models (text-embedding-3-*) are not instruction-aware and require no wrapping.

### FR-006: ChromaDB uses `embed_query()` for retrieval

The `ChromaDBAdapter.query()` method shall call `self._embeddings.embed_query(query_texts)` instead of `self._embeddings.embed(query_texts)`. The `EmbedFn` protocol in `chromadb.py` shall require both `embed()` and `embed_query()` methods.

### FR-007: Config field for query instruction

`BaseConfig` shall include an `embeddings_query_instruction: str | None = None` field. When set, its value is passed to the adapter constructor, overriding auto-detection.

### FR-008: Wiring in `main.py`

The `_create_adapters()` function in `main.py` shall pass `config.embeddings_query_instruction` to the `OpenAICompatibleEmbeddingsAdapter` constructor as the `query_instruction` parameter.

### FR-009: Mock port and test coverage

`MockEmbeddingsPort` in `tests/conftest.py` shall implement `embed_query()` with a separate `query_calls` list for tracking. A dedicated test module `tests/core/adapters/test_openai_compatible_embeddings.py` shall contain tests for instruction resolution (5 tests) and wrapping behavior (4 tests).

---

## Success Criteria

| Criterion | Metric |
|-----------|--------|
| Retrieval improvement | Qwen3-Embedding queries with instruction prefix produce measurably better ranking than plain embedding queries |
| Auto-detection accuracy | All `qwen3-embedding*` model name variants (case-insensitive) are detected |
| Override correctness | Explicit instruction (including empty string) always takes precedence over auto-detection |
| Backward compatibility | All existing tests pass with zero modifications to plugin or test code |
| Separation of concerns | `embed()` never wraps; `embed_query()` always wraps when instruction is configured |
| Test coverage | 9 dedicated adapter tests pass, covering resolution and wrapping behavior |

---

## Assumptions

- The Qwen3-Embedding retrieval instruction format (`Instruct: ... \nQuery:` followed by a trailing space) is stable across Qwen3-Embedding model variants (0.6B, 8B, etc.).
- Instruction-aware wrapping is a query-side concern only -- document embeddings must remain in the plain space for the asymmetric retrieval to work correctly.
- The `QWEN3_RETRIEVAL_INSTRUCTION` constant is appropriate for general-purpose retrieval. Domain-specific use cases may need the explicit override.
- Other future instruction-aware models (e.g., E5-v2, BGE-v2) can be added to the auto-detection logic without breaking the existing API surface.
