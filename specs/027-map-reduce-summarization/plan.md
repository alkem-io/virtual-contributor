# Implementation Plan: Map-Reduce Summarization

**Branch**: `027-map-reduce-summarization` | **Date**: 2026-04-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/027-map-reduce-summarization/spec.md`

---

## Summary

Switches summarization from O(n) sequential refine to O(log n) parallel map-reduce with split-model support and fault tolerance. The core change is a single new async function `_map_reduce_summarize()` in the pipeline steps module, six new prompt templates, and updated constructor signatures on the two summary step classes to accept optional secondary LLM ports. Plugin wiring passes the correct models into each step.

---

## Technical Context

- **Runtime**: Python 3.12, async-first with `asyncio`
- **Package manager**: Poetry
- **Test framework**: pytest with `asyncio_mode = "auto"`
- **LLM abstraction**: `LLMPort` protocol (`core/ports/llm.py`) with `invoke(messages) -> str`
- **Text splitting**: LangChain `RecursiveCharacterTextSplitter`
- **Pipeline engine**: `IngestEngine` in `core/domain/pipeline/engine.py` with ordered step execution (sequential and batched modes)
- **Affected steps**: `DocumentSummaryStep`, `BodyOfKnowledgeSummaryStep` in `core/domain/pipeline/steps.py`
- **Prompt store**: Module-level constants in `core/domain/pipeline/prompts.py`

---

## Constitution Check

| Principle | Verdict | Notes |
|-----------|---------|-------|
| P1 AI-Native Development | PASS | LLM summarization is a core AI capability of the system |
| P2 SOLID Architecture | PASS | `_map_reduce_summarize` is a shared domain function with single responsibility; step classes extend (not modify) their constructor contract via optional parameters; split-model is additive, not breaking |
| P3 No Vendor Lock-in | PASS | Works with any `LLMPort` implementation (Mistral, OpenAI, Anthropic); no vendor-specific API calls |
| P4 Optimised Feedback Loops | GAP | No unit tests added for `_map_reduce_summarize`, the new constructor parameters, or the error tolerance paths. The refine-based tests (if any) are not updated. This is a test gap that should be addressed in a follow-up. |
| P5 Best Available Infrastructure | N/A | No infrastructure changes |
| P6 SDD | PASS | Retrospec — spec generated from implemented code changes |
| P7 No Filling Tests | N/A | No tests were added or modified in this changeset |
| P8 ADR | N/A | No new port, contract, or deployment topology changes; the algorithm change is internal to existing step classes |

### Architecture Standards

| Standard | Verdict | Notes |
|----------|---------|-------|
| Domain Logic Isolation | PASS | `_map_reduce_summarize` lives in `core/domain/pipeline/steps.py`, not in plugins |
| Async-First | PASS | Uses `asyncio.gather`, `asyncio.Semaphore`, all calls are `await`-ed |
| Simplicity | PASS | Single function (~90 lines) with clear algorithm: map all, tree-reduce, error fallbacks |
| Port/Adapter Boundary | PASS | Takes `invoke` callables, not concrete adapter references |

---

## Project Structure

Files changed:

```
core/domain/pipeline/prompts.py       # +6 prompt constants (map & reduce for doc + BoK)
core/domain/pipeline/steps.py         # +_map_reduce_summarize(), modified DocumentSummaryStep
                                      #  and BodyOfKnowledgeSummaryStep constructors and execute()
plugins/ingest_space/plugin.py        # Wire reduce_llm_port and map_llm_port
plugins/ingest_website/plugin.py      # Wire reduce_llm_port and map_llm_port
```

No new files. No deleted files. No new dependencies.

---

## Complexity Tracking

No violations detected. The change is confined to one shared function, two modified constructors, and two plugin wiring updates. No circular dependencies introduced. No new ports or adapters.
