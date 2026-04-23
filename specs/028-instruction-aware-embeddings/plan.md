# Implementation Plan: Instruction-Aware Embeddings

**Branch**: `028-instruction-aware-embeddings` | **Date**: 2026-04-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/028-instruction-aware-embeddings/spec.md`

---

## Summary

Splits the `EmbeddingsPort` protocol into `embed()` (indexing) and `embed_query()` (retrieval) to support instruction-aware embedding models. The `OpenAICompatibleEmbeddingsAdapter` auto-detects Qwen3 models and wraps queries with a retrieval instruction prefix, with an explicit override mechanism. ChromaDB retrieval calls `embed_query()` instead of `embed()`. The OpenAI adapter adds `embed_query()` as a no-op alias. Config gains one new field, wiring passes it through, and 9 adapter tests validate the behavior.

---

## Technical Context

- **Runtime**: Python 3.12, async-first with `asyncio`
- **Package manager**: Poetry
- **Test framework**: pytest with `asyncio_mode = "auto"`
- **HTTP client**: `httpx` (for OpenAI-compatible adapter)
- **OpenAI SDK**: `openai` (for native OpenAI adapter)
- **Embeddings abstraction**: `EmbeddingsPort` protocol (`core/ports/embeddings.py`)
- **Adapters**: `OpenAICompatibleEmbeddingsAdapter` (`core/adapters/openai_compatible_embeddings.py`), `OpenAIEmbeddingsAdapter` (`core/adapters/openai_embeddings.py`)
- **Knowledge store**: `ChromaDBAdapter` (`core/adapters/chromadb.py`) -- consumes embeddings port
- **Config**: `BaseConfig` in `core/config.py` (Pydantic Settings)

---

## Constitution Check

| Principle | Verdict | Notes |
|-----------|---------|-------|
| P1 AI-Native Development | PASS | Embeddings are a core AI capability; instruction-aware wrapping improves retrieval quality autonomously |
| P2 SOLID Architecture | PASS | `EmbeddingsPort` gains a method that is semantically distinct (ISP: each method has one purpose). All adapters implement both methods (LSP). No plugin code changes required (OCP). |
| P3 No Vendor Lock-in | PASS | Port interface is vendor-agnostic. Qwen3 detection is in the adapter, not in port or plugin code. Override mechanism allows any instruction format. |
| P4 Optimised Feedback Loops | PASS | 9 dedicated unit tests covering instruction resolution and wrapping behavior. Tests run locally in <1s. |
| P5 Best Available Infrastructure | N/A | No infrastructure changes |
| P6 SDD | PASS | Retrospec -- spec generated from implemented code changes |
| P7 No Filling Tests | PASS | All 9 tests verify meaningful behavior: auto-detection, case sensitivity, explicit override, empty string disable, wrapping/non-wrapping in actual API calls |
| P8 ADR | N/A | Port interface change is additive (new method, not modified signature). Existing `embed()` callers are unaffected. Does not meet the threshold for a formal ADR. |

### Architecture Standards

| Standard | Verdict | Notes |
|----------|---------|-------|
| Hexagonal Boundaries | PASS | Port gains method, adapters implement it, plugins are unaware of the change |
| Domain Logic Isolation | PASS | Instruction logic is in the adapter (correct layer -- adapters encapsulate provider-specific behavior) |
| Async-First | PASS | Both new methods are `async` |
| Simplicity | PASS | ~20 lines of new logic in adapter, one new config field, one port method -- minimal surface area |
| Port/Adapter Boundary | PASS | ChromaDB adapter consumes the port protocol, not a concrete adapter class |

---

## Project Structure

Files changed:

```text
core/ports/embeddings.py                                    # +embed_query() method to protocol
core/adapters/openai_compatible_embeddings.py               # +_resolve_query_instruction(), +_call(),
                                                            #  +embed_query(), QWEN3_RETRIEVAL_INSTRUCTION
core/adapters/openai_embeddings.py                          # +embed_query() as alias
core/adapters/chromadb.py                                   # query() calls embed_query(), EmbedFn updated
core/config.py                                              # +embeddings_query_instruction field
main.py                                                     # Wire query_instruction to adapter
tests/conftest.py                                           # MockEmbeddingsPort gains embed_query()
tests/core/adapters/__init__.py                             # NEW (empty, package marker)
tests/core/adapters/test_openai_compatible_embeddings.py    # NEW (9 tests)
```

No deleted files. No new dependencies.

---

## Complexity Tracking

No violations detected. The change is additive: one new protocol method, adapter implementations, one config field, and one wiring change. No circular dependencies. No new ports or event types.
