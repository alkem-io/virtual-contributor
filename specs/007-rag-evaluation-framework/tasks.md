# Tasks: RAG Evaluation Framework and Golden Test Set

**Input**: Design documents from `/specs/007-rag-evaluation-framework/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/cli.md, quickstart.md

**Tests**: Included per plan.md constitution check (P4: "Framework itself will have meaningful tests", P7: "Tests will validate meaningful evaluation paths").

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. US3 (Privacy-Preserving) is merged into US1 because it is a design constraint on how evaluation runs (local LLM as judge) rather than a separate feature — US3's acceptance criteria are satisfied by the architecture choices in metrics.py and pipeline_invoker.py.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US4)
- Include exact file paths in descriptions

## Path Conventions

- **evaluation/**: Top-level source package (evaluation framework code)
- **evaluation/golden/**: Version-controlled golden test set data
- **evaluations/**: Gitignored run results directory
- **tests/evaluation/**: Test suite for evaluation modules
- **docs/adr/**: Architecture Decision Records

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create project structure and add dependencies for the evaluation framework

- [x] T001 Create evaluation/ package directory with `__init__.py`, `__main__.py` entry point, and `golden/` subdirectory per plan.md project structure
- [x] T002 Add ragas, click, and pytest-asyncio dependencies to pyproject.toml
- [x] T003 [P] Add `evaluations/` directory to .gitignore and create `evaluations/.gitkeep` for the gitignored run results directory

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data models, JSONL I/O, and TracingKnowledgeStore that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Implement Pydantic data models (TestCase, SourceInfo, MetricScores, EvaluationCase, AggregateMetrics, EvaluationRun, MetricDelta, ComparisonReport) and JSONL I/O functions (load_test_set, validate, write) per data-model.md in evaluation/dataset.py
- [x] T005 [P] Implement TracingKnowledgeStore Decorator wrapper over KnowledgeStorePort with query delegation, context capture via `get_retrieved_contexts()`, and `clear()` per research.md R2 in evaluation/tracing.py
- [x] T006 [P] Create tests/evaluation/ directory with `__init__.py`
- [x] T018 [P] Create seed golden test set with ~15 manually curated question/expected-answer/relevant-document triples covering diverse Alkemio space content in evaluation/golden/test_set.jsonl

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 + User Story 3 — Run Evaluation Against Current Pipeline & Privacy-Preserving Evaluation (Priority: P1) MVP

**Goal**: Run the full evaluation suite via CLI, producing per-case and aggregate scores for faithfulness, answer relevance, context precision, and context recall — using the pipeline's own LLM as judge (US3: no evaluation data leaves the infrastructure boundary)

**Independent Test**: Invoke `poetry run python -m evaluation run --plugin guidance --label baseline` against the existing pipeline and verify that numeric metric scores are produced for each evaluation dimension, with aggregate statistics (mean, median, min, max) displayed in a human-readable report

**Requirements covered**: FR-001, FR-002, FR-003, FR-004, FR-007, FR-010, FR-012

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T007 [P] [US1] Write unit tests for JSONL loading, validation, duplicate detection, and TestCase Pydantic model in tests/evaluation/test_dataset.py
- [x] T008 [P] [US1] Write unit tests for RAGAS metric configuration and LangchainLLMWrapper/LangchainEmbeddingsWrapper setup in tests/evaluation/test_metrics.py
- [x] T009 [P] [US1] Write unit tests for evaluation runner orchestration, failure continuation (FR-010), aggregate computation, JSON persistence, and edge cases (empty retrieval → low scores not skip, judge model unreachable → graceful error) in tests/evaluation/test_runner.py

### Implementation for User Story 1

- [x] T010 [P] [US1] Implement RAGAS metric configuration with LangchainLLMWrapper using pipeline's own LLM as judge (FR-004/US3) and LangchainEmbeddingsWrapper for AnswerRelevancy per research.md R1 and R7 in evaluation/metrics.py
- [x] T011 [P] [US1] Implement pipeline invoker with Container setup, target plugin instantiation (guidance/expert), and TracingKnowledgeStore injection per research.md R2 in evaluation/pipeline_invoker.py
- [x] T012 [P] [US1] Implement aggregate report formatting with per-metric summary table (mean, median, min, max), failure listing, and run summary header per contracts/cli.md `run` output in evaluation/report.py
- [x] T013 [US1] Implement evaluation runner with sequential test case execution, pipeline invocation via pipeline_invoker, RAGAS scoring via metrics module, per-case progress logging (FR-012), graceful failure handling with error recording (FR-010) including edge cases (empty retrieval results still scored, judge model unreachable produces clear error without external API fallback), aggregate computation, and JSON result persistence to evaluations/ (FR-007) in evaluation/runner.py
- [x] T014 [US1] Implement Click CLI `run` command with --plugin, --label, --test-set, --body-of-knowledge-id options per contracts/cli.md in evaluation/cli.py

**Checkpoint**: User Story 1 fully functional — can run `poetry run python -m evaluation run --plugin guidance` and get scored evaluation results

---

## Phase 4: User Story 2 — Golden Test Set Curation (Priority: P1)

**Goal**: Generate synthetic test pairs from indexed content using the local LLM and merge with the seed golden test set to reach 50+ entries

**Independent Test**: Verify the test set file contains at least 50 entries, each loadable by the evaluation runner, and that synthetic generation completes without external API calls

**Requirements covered**: FR-006 (FR-005 partially — seed test set created in Phase 2, synthetic generation completes coverage here)

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US2] Write unit tests for synthetic test pair generator output format and JSONL serialization in tests/evaluation/test_generator.py

### Implementation for User Story 2

- [x] T016 [P] [US2] Implement synthetic test pair generator using RAGAS TestsetGenerator with local LLM and embeddings, ChromaDB document sourcing, and JSONL output per research.md R4 in evaluation/generator.py
- [x] T017 [US2] Implement Click CLI `generate` command with --collection, --count, --output options per contracts/cli.md in evaluation/cli.py

**Checkpoint**: Golden test set contains 50+ entries (manual + synthetic), loadable by the evaluation runner

---

## Phase 5: User Story 4 — Before/After Metric Comparison (Priority: P2)

**Goal**: Compare evaluation metrics between any two runs to objectively determine whether a pipeline change improved or degraded answer quality

**Independent Test**: Record a baseline evaluation, re-run evaluation, and verify the comparison report shows per-metric deltas (baseline value, current value, absolute delta, percentage change)

**Requirements covered**: FR-008

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T019 [P] [US4] Write unit tests for comparison report computation (MetricDelta calculation, percentage change, overall summary) and formatting in tests/evaluation/test_report.py

### Implementation for User Story 4

- [x] T020 [P] [US4] Implement comparison report logic: load two EvaluationRun JSON files by ID, compute MetricDelta per metric (baseline, current, absolute_delta, percentage_change), format before/after table per contracts/cli.md `compare` output in evaluation/report.py
- [x] T021 [US4] Implement Click CLI `compare` command with baseline-id and current-id arguments per contracts/cli.md in evaluation/cli.py
- [x] T022 [P] [US4] Implement Click CLI `list` command scanning evaluations/ directory for run metadata per contracts/cli.md in evaluation/cli.py

**Checkpoint**: All user stories (US1, US2, US3, US4) independently functional — full evaluation workflow operational

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, ADR, and end-to-end validation

- [x] T023 [P] Create ADR for RAGAS dependency selection documenting decision rationale from research.md R1 in docs/adr/NNNN-ragas-evaluation-framework.md
- [x] T024 Run quickstart.md end-to-end validation: execute all four CLI commands (run, generate, compare, list) and verify outputs match contracts/cli.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1+US3 (Phase 3)**: Depends on Foundational (Phase 2) — the MVP
- **US2 (Phase 4)**: Depends on Foundational (Phase 2) — can run in parallel with Phase 3 (different files)
- **US4 (Phase 5)**: Depends on Foundational (Phase 2) — can run in parallel with Phases 3-4 (different files), but `compare` is most useful after `run` produces results
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1+3 (P1)**: Can start after Foundational (Phase 2) — no dependencies on other stories. **This is the MVP.**
- **User Story 2 (P1)**: Can start after Foundational (Phase 2) — independent of US1 (generator.py is a separate file). Seed golden test set (T018) moved to Phase 2 so US1 checkpoint has test data.
- **User Story 4 (P2)**: Can start after Foundational (Phase 2) — comparison logic (report.py) and CLI commands (compare, list) are independent of runner implementation. Most useful after US1 produces at least one evaluation run.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Data models (Phase 2) before module implementation
- Core modules before CLI integration
- Independent modules (marked [P]) before orchestration modules

### Key Sequential Dependencies Within US1

```
T004 (data models) → T010 (metrics), T011 (pipeline_invoker), T012 (report)
T005 (tracing) → T011 (pipeline_invoker)
T010 + T011 → T013 (runner — needs metrics + invoker)
T013 + T012 → T014 (CLI run — needs runner + report)
```

### Parallel Opportunities

- **Phase 2**: T004, T005 [P], T006 [P] — tracing and test dir can run alongside models
- **Phase 3 tests**: T007, T008, T009 — all [P], different test files
- **Phase 3 implementation**: T010, T011, T012 — all [P], different source files (metrics, pipeline_invoker, report)
- **Phase 4**: T015 [P], T016 [P], T018 [P] — generator, tests, and manual test set are independent
- **Phase 5**: T019 [P], T020 [P], T022 [P] — comparison tests, comparison logic, and list command are independent
- **Cross-phase**: US2 (Phase 4) can run in parallel with US1 (Phase 3) since generator.py and golden test set are entirely separate files from runner.py and metrics.py

---

## Parallel Example: User Story 1

```bash
# Launch all tests for US1 together (TDD - write first, expect failures):
Task T007: "Unit tests for dataset loading in tests/evaluation/test_dataset.py"
Task T008: "Unit tests for metrics config in tests/evaluation/test_metrics.py"
Task T009: "Unit tests for runner orchestration in tests/evaluation/test_runner.py"

# Launch all independent implementation modules for US1 together:
Task T010: "RAGAS metric configuration in evaluation/metrics.py"
Task T011: "Pipeline invoker in evaluation/pipeline_invoker.py"
Task T012: "Aggregate report formatting in evaluation/report.py"
```

---

## Parallel Example: Cross-Story Parallelism

```bash
# After Phase 2 completes, these can run simultaneously:
# Developer A: US1 (Phase 3)
Task T010: "evaluation/metrics.py"
Task T011: "evaluation/pipeline_invoker.py"
Task T013: "evaluation/runner.py"

# Developer B: US2 (Phase 4)
Task T016: "evaluation/generator.py"
Task T018: "evaluation/golden/test_set.jsonl"

# Developer C: US4 (Phase 5)
Task T020: "evaluation/report.py (comparison logic)"
Task T022: "evaluation/cli.py (list command)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 + US3
4. **STOP and VALIDATE**: Run `poetry run python -m evaluation run --plugin guidance` and verify scored output
5. Minimum viable evaluation framework is operational

### Incremental Delivery

1. Complete Setup + Foundational -> Foundation ready
2. Add User Story 1+3 -> Run evaluation with local LLM judge -> MVP!
3. Add User Story 2 -> Curated golden test set with 50+ cases
4. Add User Story 4 -> Before/after comparison reports
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1+3 (evaluation runner + CLI)
   - Developer B: User Story 2 (generator + golden test set)
   - Developer C: User Story 4 (comparison reports)
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks in the same phase
- [Story] label maps task to specific user story for traceability
- US3 (Privacy-Preserving) is architecturally enforced by US1's implementation — metrics.py uses LangchainLLMWrapper with the pipeline's own LLM, and pipeline_invoker.py reuses the existing Container/port infrastructure. No separate implementation needed.
- US5 (CI/CD Integration) is explicitly DEFERRED per spec — not included in these tasks
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
