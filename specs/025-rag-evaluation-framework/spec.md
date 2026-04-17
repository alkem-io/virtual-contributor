# Feature Specification: RAG Evaluation Framework and Golden Test Set

**Feature Branch**: `025-rag-evaluation-framework`  
**Created**: 2026-04-06  
**Status**: Draft  
**Input**: User description: "implement https://github.com/orgs/alkem-io/projects/50/views/8?pane=issue&itemId=172807481&issue=alkem-io%7Cvirtual-contributor%7C25"  
**Source Issue**: [alkem-io/virtual-contributor#25](https://github.com/alkem-io/virtual-contributor/issues/25)  
**Parent Epic**: [alkem-io/alkemio#1816](https://github.com/alkem-io/alkemio/issues/1816)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Evaluation Against Current Pipeline (Priority: P1)

As a pipeline developer, I want to run an evaluation suite against the current RAG pipeline so that I get quantitative metrics (faithfulness, answer relevance, context precision, context recall) that tell me how well the pipeline is performing.

**Why this priority**: Without a runnable evaluation, no other feature in this spec delivers value. This is the foundational capability everything else depends on.

**Independent Test**: Can be fully tested by invoking the evaluation from the command line against the existing pipeline and verifying that numeric metric scores are produced for each evaluation dimension.

**Acceptance Scenarios**:

1. **Given** the pipeline is operational and a golden test set exists, **When** the operator runs the evaluation command, **Then** the system produces scores for faithfulness, answer relevance, context precision, and context recall for each test case.
2. **Given** the evaluation completes, **When** the operator views the results, **Then** aggregate metrics (mean, median, min, max per dimension) are displayed in a human-readable report.
3. **Given** the evaluation is running, **When** any test case fails to produce a score (e.g., pipeline timeout), **Then** the failure is recorded with a reason and remaining test cases continue to execute.

---

### User Story 2 - Golden Test Set Curation (Priority: P1)

As a pipeline developer, I want a curated golden test set of at least 50 question/expected-answer/relevant-document triples so that evaluation results are grounded in realistic, representative data from actual Alkemio space content.

**Why this priority**: Evaluation metrics are only meaningful if the test data is representative. Without a golden test set, the evaluation framework has nothing to measure against.

**Independent Test**: Can be tested by verifying the test set file contains at least 50 entries, each with a question, expected answer, and relevant document reference, and that the entries are loadable by the evaluation runner.

**Acceptance Scenarios**:

1. **Given** the golden test set is created, **When** it is loaded, **Then** it contains at least 50 question/expected-answer/relevant-document triples.
2. **Given** a triple in the golden test set, **When** inspected, **Then** the question is a realistic user query, the expected answer is factually grounded in the referenced document, and the document reference maps to indexed content.
3. **Given** synthetic generation is used to supplement the test set, **When** synthetic pairs are generated, **Then** they are produced using the local LLM (no data leaves the infrastructure boundary).

---

### User Story 3 - Privacy-Preserving Evaluation (Priority: P1)

As a platform operator, I want the evaluation judge model to run locally using the pipeline's own LLM so that no evaluation data (questions, space content, answers) leaves the infrastructure boundary, preserving Alkemio's data sovereignty commitment.

**Why this priority**: Privacy is a hard constraint, not a nice-to-have. If evaluation data leaks externally, the feature violates Alkemio's core data sovereignty goal and cannot be used.

**Independent Test**: Can be tested by running the evaluation in a network-isolated environment and verifying it completes successfully without any outbound network calls to external LLM APIs.

**Acceptance Scenarios**:

1. **Given** the evaluation framework is configured, **When** evaluation runs, **Then** all LLM judge calls are routed to the pipeline's own LLM or a designated local model.
2. **Given** the evaluation is running, **When** network traffic is monitored, **Then** no evaluation data (questions, answers, context) is sent to any external API endpoint.

---

### User Story 4 - Before/After Metric Comparison (Priority: P2)

As a pipeline developer, I want to compare evaluation metrics before and after a pipeline change so that I can objectively determine whether the change improved or degraded answer quality.

**Why this priority**: This is the primary use case for the evaluation framework — measuring the impact of changes. It depends on the evaluation runner (US1) being functional first.

**Independent Test**: Can be tested by recording a baseline evaluation, making a known pipeline change, re-running evaluation, and verifying the comparison report shows metric deltas.

**Acceptance Scenarios**:

1. **Given** a baseline evaluation result exists and a new evaluation has been run, **When** the operator requests a comparison, **Then** the system displays per-metric deltas (improvement/regression) between the two runs.
2. **Given** a comparison report is generated, **When** the operator reviews it, **Then** each metric shows the baseline value, new value, absolute delta, and percentage change.
3. **Given** no previous evaluation run exists, **When** the operator runs the first evaluation, **Then** the results are persisted and available as a reference for future ad hoc comparisons against subsequent runs.

---

### User Story 5 - Automated Evaluation in CI (Priority: P3 — DEFERRED)

> **Deferred**: This user story is out of scope for the current feature. It will be addressed in a follow-up once the manual evaluation workflow (US1, US4) is proven stable.

As a pipeline developer, I want evaluation to run automatically on every pipeline change so that regressions are caught before they reach production.

---

### Edge Cases

- What happens when the golden test set references documents that have been removed or re-indexed? The evaluation should detect missing documents and report them as test set maintenance issues rather than pipeline failures.
- How does the system handle evaluation when the local LLM is unavailable or unresponsive? The evaluation should fail gracefully with a clear error indicating the judge model is unreachable, rather than falling back to external APIs.
- What happens when a pipeline change causes the retrieval step to return no documents for a test question? The evaluation should still score the test case (likely producing low context precision/recall scores) rather than skipping it.
- How does the system handle very long answers or context windows that exceed the judge model's token limit? The evaluation should truncate or chunk appropriately and note the truncation in the results.

## Out of Scope

The following are explicitly excluded from this feature and may be addressed in follow-up work:

- **Web dashboard or UI** for viewing evaluation results (CLI and file-based reports only).
- **Custom metric definitions** — only the four core metrics (faithfulness, answer relevance, context precision, context recall) are supported.
- **Production traffic evaluation** — evaluation runs against the golden test set only, not live queries.
- **Multi-space comparison** — evaluation targets a single space's indexed content per run.
- **CI/CD integration** (User Story 5) — automated evaluation in CI is deferred to a follow-up feature. This includes FR-009 (configurable thresholds for pass/fail) and FR-011 (CI exit codes).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a command-line interface to run the full evaluation suite against the current pipeline. The evaluation framework invokes the pipeline directly via Python API import (in-process), without requiring a running server instance.
- **FR-002**: System MUST compute four core metrics for each test case: faithfulness, answer relevance, context precision, and context recall.
- **FR-003**: System MUST produce an aggregate evaluation report with per-metric summary statistics (mean, median, min, max).
- **FR-004**: System MUST use the pipeline's own LLM (or a designated local model) as the evaluation judge — no evaluation data may be sent to external APIs.
- **FR-005**: System MUST support a golden test set of at least 50 question/expected-answer/relevant-document triples, stored in JSONL format (one JSON object per line) in a version-controlled directory within the repository (e.g., `evaluation/golden/`). Relevant document references use source URI/URLs matching the vector store metadata.
- **FR-006**: System MUST support synthetic test pair generation using the local LLM to bootstrap test coverage from indexed space content.
- **FR-007**: System MUST persist evaluation results as file-based JSON — one file per run in a gitignored local directory (e.g., `evaluations/<timestamp>_<label>.json`) — so that previous runs can be compared against new runs. The `evaluations/` directory is excluded from version control.
- **FR-008**: System MUST produce a before/after comparison report showing per-metric deltas (absolute and percentage) between any two evaluation runs specified by their identifiers (timestamp/label). There is no single pinned baseline — any two runs can be compared ad hoc.
- **FR-009**: ~~System MUST support configurable metric thresholds that determine pass/fail in automated runs.~~ *(Deferred — part of CI/CD integration, US5.)*
- **FR-010**: System MUST continue evaluating remaining test cases when individual cases fail, recording failures with reasons.
- **FR-012**: System MUST provide per-case progress reporting during evaluation, logging each test case start/completion with timing (e.g., `[12/50] Evaluating: "..."... done (4.2s)`).
- **FR-011**: ~~System MUST be runnable in a CI/CD pipeline and return an exit code reflecting pass/fail based on metric thresholds.~~ *(Deferred — part of CI/CD integration, US5.)*

### Key Entities

- **Test Case**: A single evaluation unit consisting of a question, expected answer, and one or more relevant document references (source URI/URLs as stored in vector store metadata). Stored as one JSON object per line in a JSONL file. Serves as the atomic input for evaluation.
- **Evaluation Run**: A complete execution of the evaluation suite against the pipeline, producing per-case scores and aggregate metrics. Identified by a timestamp and optional label. Persisted as a single JSON file in a local `evaluations/` directory.
- **Evaluation Report**: The output of an evaluation run — includes per-case scores, aggregate statistics, and optionally a comparison against a baseline run.
- **Golden Test Set**: The curated collection of test cases used for evaluation, stored in-repo under a dedicated directory (e.g., `evaluation/golden/`) and version-controlled. Target composition: ~30% manually curated (~15 cases) and ~70% synthetically generated (~35+ cases), with all synthetic entries quality-reviewed before inclusion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Evaluation suite runs end-to-end and produces scores for all four metrics (faithfulness, answer relevance, context precision, context recall) for at least 50 test cases.
- **SC-002**: Golden test set contains at least 50 representative question/answer/document triples covering diverse Alkemio space content.
- **SC-003**: Zero evaluation data leaves the infrastructure boundary during any evaluation run (verifiable via network monitoring).
- **SC-004**: Before/after comparison reports correctly identify metric improvements and regressions within 5% tolerance of manual calculation.
- **SC-005**: Baseline metrics for the current pipeline are recorded and available for comparison within the first evaluation run.
- **SC-006**: Evaluation suite completes within a reasonable time window (under 30 minutes for 50 test cases) to remain practical for regular use.
- **SC-007**: Pipeline developers can determine whether a change improved or degraded quality within 2 minutes of reviewing the comparison report.

## Clarifications

### Session 2026-04-06

- Q: What should be explicitly declared out-of-scope? → A: Web dashboard, custom metric definitions, production traffic evaluation, multi-space comparison, and CI/CD integration (US5 deferred entirely to follow-up).
- Q: What file format should the golden test set use? → A: JSONL (one JSON object per line) — supports append, VCS diffing, streaming, and JSON Schema validation.
- Q: How should evaluation results be persisted? → A: File-based JSON — one file per run in a local directory (e.g., `evaluations/<timestamp>_<label>.json`).
- Q: What is the expected balance between manual and synthetic test cases? → A: ~30% manual (~15 cases) anchoring quality and edge cases, ~70% synthetic (~35+ cases) providing volume. Synthetic cases undergo quality review.
- Q: What level of progress reporting should the evaluation runner provide? → A: Per-case progress — log each test case as it starts/completes with timing (e.g., `[12/50] Evaluating: "..."... done (4.2s)`).
- Q: How should the evaluation framework invoke the RAG pipeline? → A: Python API import — call the pipeline's query function directly in-process.
- Q: What form should "relevant document references" take in test cases? → A: Source URI/URL as stored in the pipeline's vector store metadata — human-readable and stable across re-indexing.
- Q: How should baseline management work for before/after comparisons? → A: Any-two-runs ad hoc — compare any two runs by specifying their identifiers (timestamp/label).
- Q: Should the golden test set be stored in-repo or externally? → A: In-repo under a dedicated directory (e.g., `evaluation/golden/`), version-controlled alongside the pipeline code.
- Q: Should evaluation result files be version-controlled or gitignored? → A: Gitignored local directory — persist in `evaluations/` but exclude from VCS.

## Assumptions

- The pipeline's own LLM is capable of serving as an evaluation judge (i.e., it can assess answer quality, faithfulness, and relevance with sufficient accuracy for comparative measurement).
- Sufficient representative Alkemio space content is available and indexed to create a meaningful golden test set of 50+ entries.
- The pipeline is operational and can process queries end-to-end (retrieval + generation) for evaluation to function. The evaluation framework imports the pipeline's query function directly (in-process invocation).
- Synthetic test generation will supplement, not replace, manually curated test cases — target ratio is ~30% manual (~15 cases) to ~70% synthetic (~35+ cases). Quality review of synthetic pairs is expected before inclusion.
- The RAGAS framework (recommended in the issue) supports custom LLM wrappers to enforce local-only evaluation, but the specific framework choice is an implementation decision.
- CI/CD infrastructure exists or will be available to support automated evaluation runs.
- Evaluation metrics are used for relative comparison (before/after deltas) rather than as absolute quality guarantees — the primary value is detecting regressions.
