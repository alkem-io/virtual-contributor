# Implementation Plan: RAG Evaluation Framework and Golden Test Set

**Branch**: `025-rag-evaluation-framework` | **Date**: 2026-04-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/025-rag-evaluation-framework/spec.md`

## Summary

Build an evaluation framework that measures RAG pipeline quality using four core metrics (faithfulness, answer relevance, context precision, context recall) against a curated golden test set of 50+ question/answer/document triples. The framework uses RAGAS with the pipeline's own LLM as judge (via LangChain wrapper) to preserve data sovereignty, supports synthetic test generation from indexed content, persists run results as JSON files, and produces before/after comparison reports. Invoked via CLI, calling the pipeline in-process.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: RAGAS (evaluation metrics + synthetic generation), langchain ^1.1.0, langchain-openai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, chromadb-client ^1.5.0, click (CLI)  
**Storage**: File-based JSON (evaluation results in `evaluations/`), JSONL (golden test set in `evaluation/golden/`), ChromaDB (vector store — read-only for evaluation)  
**Testing**: pytest + pytest-asyncio  
**Target Platform**: Linux server (local CLI invocation, same environment as pipeline)  
**Project Type**: CLI tool + library (evaluation framework within existing service repository)  
**Performance Goals**: Under 30 minutes for 50 test cases (SC-006)  
**Constraints**: All evaluation data MUST remain local — no external API calls. Uses pipeline's own LLM as judge via existing LangChain adapter. Evaluation results gitignored.  
**Scale/Scope**: 50+ test cases, 4 evaluation metrics, ad-hoc run-to-run comparison

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| P1 AI-Native Development | PASS | CLI-based evaluation supports autonomous agent execution — no interactive UI required |
| P2 SOLID Architecture | PASS | Each module has single responsibility (runner, metrics, dataset, report, generator). Pipeline invoked through port interfaces. New metrics addable without modifying existing code |
| P3 No Vendor Lock-in | PASS | Judge LLM accessed via existing `LLMPort` through LangChain wrapper — any provider works |
| P4 Optimised Feedback Loops | PASS | The evaluation framework IS a feedback loop. Framework itself will have meaningful tests |
| P5 Best Available Infrastructure | N/A | CLI tool, not CI pipeline (CI deferred to US5) |
| P6 Spec-Driven Development | PASS | Following SDD workflow now |
| P7 No Filling Tests | PASS | Tests will validate meaningful evaluation paths — metric computation, dataset loading, comparison logic |
| P8 ADR Required | PASS | ADR `0006-ragas-evaluation-framework.md` created — documents RAGAS selection rationale |
| Microkernel Architecture | JUSTIFIED DEVIATION | Evaluation framework is a top-level `evaluation/` module, not a plugin or core domain logic. Justified: evaluation is an auxiliary development tool that invokes the pipeline but doesn't participate in runtime message processing |
| Hexagonal Boundaries | PASS | Uses existing `LLMPort` and `KnowledgeStorePort` via tracing wrapper (Decorator pattern) — no adapter imports |
| Plugin Contract | PASS | No modifications to plugin contract |
| Async-First | PASS | Evaluation runner uses async for pipeline invocation and LLM judge calls |
| Simplicity Over Speculation | PASS | Minimal CLI with only the required features. No configuration UI, no CI integration (deferred), no custom metrics |

## Project Structure

### Documentation (this feature)

```text
specs/025-rag-evaluation-framework/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli.md           # CLI interface contract
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
evaluation/
├── __init__.py
├── __main__.py           # Entry point for `python -m evaluation`
├── cli.py               # Click-based CLI entry point
├── runner.py            # Evaluation orchestrator (runs test cases, collects results)
├── metrics.py           # RAGAS metric configuration with local LLM wrapper
├── dataset.py           # Golden test set I/O (JSONL load/validate/write)
├── generator.py         # Synthetic test pair generation from indexed content
├── report.py            # Report generation (aggregate stats + run comparison)
├── pipeline_invoker.py  # In-process pipeline invocation (container setup + plugin handle)
├── tracing.py           # TracingKnowledgeStore wrapper (captures retrieved contexts)
└── golden/              # Golden test set data (version-controlled)
    └── test_set.jsonl   # The curated golden test set (50+ entries)

evaluations/             # Run results directory (gitignored)
└── <timestamp>_<label>.json

docs/adr/
└── 0006-ragas-evaluation-framework.md  # ADR for RAGAS dependency selection

tests/
└── evaluation/
    ├── __init__.py
    ├── test_runner.py
    ├── test_dataset.py
    ├── test_metrics.py
    ├── test_report.py
    └── test_generator.py
```

**Structure Decision**: Top-level `evaluation/` directory alongside `core/` and `plugins/`. The evaluation framework is a development tool that imports the pipeline in-process but does not participate in the runtime message processing flow. This parallels how `tests/` is a top-level directory for test code. The `evaluations/` directory (note plural) stores gitignored run results, separate from the framework code.

## Constitution Re-Check (Post-Phase 1 Design)

All gates from the initial check continue to pass after design completion. Specific validations:

| Principle | Post-Design Status | Validation |
|-----------|-------------------|------------|
| P2 SOLID | PASS | TracingKnowledgeStore follows Decorator pattern (OCP). Modules have clear SRP: runner, metrics, dataset, report, generator. DIP maintained — depends on port interfaces only |
| P3 No Vendor Lock-in | PASS | RAGAS accepts any LangChain `BaseChatModel` via `LangchainLLMWrapper`. Swapping LLM providers requires zero evaluation code changes |
| P4 Feedback Loops | PASS | Tests planned for all evaluation modules (runner, dataset, metrics, report, generator) |
| P8 ADR | PASS | ADR `0006-ragas-evaluation-framework.md` created. Decision: RAGAS over DeepEval/custom; rationale documented in research.md R1 |
| Hexagonal Boundaries | PASS | Data model uses Pydantic models independent of any adapter. Pipeline invoked via port-injected plugin instances |
| Simplicity | PASS | 9 source files in `evaluation/`, 4 CLI commands mapping directly to user stories. No speculative abstractions |

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Top-level `evaluation/` directory | Evaluation is a standalone CLI tool, not a plugin or domain logic | Placing in `core/domain/evaluation/` would conflate a development tool with runtime domain logic |
| RAGAS external dependency | Provides battle-tested metric implementations (faithfulness, relevance, precision, recall) with LangChain integration | Custom metric implementation would require significant prompt engineering and validation effort for equivalent quality |
| TracingKnowledgeStore wrapper | Captures retrieved contexts during pipeline execution for RAGAS metrics without modifying plugins | Modifying plugin `handle()` to return contexts would break the plugin contract; querying separately would run retrieval twice with potentially different results |
