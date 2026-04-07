# Data Model: RAG Evaluation Framework

**Feature**: 007-rag-evaluation-framework  
**Date**: 2026-04-06

## Entities

### TestCase

A single evaluation unit from the golden test set.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | `str` | Yes | The user query to evaluate against the pipeline |
| `expected_answer` | `str` | Yes | The reference answer grounded in the relevant documents |
| `relevant_documents` | `list[str]` | Yes (min 1) | Source URI/URLs matching vector store metadata |

**Storage**: JSONL file (`evaluation/golden/test_set.jsonl`), one JSON object per line.  
**Validation**: Pydantic model with `min_length=1` on all string fields, `min_length=1` on `relevant_documents` list.

```python
class TestCase(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    relevant_documents: list[str] = Field(min_length=1)
```

### EvaluationCase

A completed evaluation of a single test case, including pipeline output and metric scores.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `index` | `int` | Yes | Position in the test set (0-based) |
| `question` | `str` | Yes | The input question (from TestCase) |
| `expected_answer` | `str` | Yes | The reference answer (from TestCase) |
| `relevant_documents` | `list[str]` | Yes | Document references (from TestCase) |
| `pipeline_answer` | `str \| None` | No | The pipeline's generated answer |
| `retrieved_contexts` | `list[str]` | No | Document texts retrieved by the pipeline |
| `retrieved_sources` | `list[SourceInfo]` | No | Source metadata from pipeline response |
| `scores` | `MetricScores` | No | Per-metric scores (null if case failed) |
| `duration_seconds` | `float` | Yes | Wall-clock time for this case |
| `error` | `str \| None` | No | Error message if case failed |

```python
class SourceInfo(BaseModel):
    uri: str | None = None
    title: str | None = None
    score: float | None = None

class MetricScores(BaseModel):
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None

class EvaluationCase(BaseModel):
    index: int
    question: str
    expected_answer: str
    relevant_documents: list[str]
    pipeline_answer: str | None = None
    retrieved_contexts: list[str] = Field(default_factory=list)
    retrieved_sources: list[SourceInfo] = Field(default_factory=list)
    scores: MetricScores | None = None
    duration_seconds: float
    error: str | None = None
```

### AggregateMetrics

Summary statistics for a single metric across all cases.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mean` | `float` | Yes | Arithmetic mean |
| `median` | `float` | Yes | Median value |
| `min` | `float` | Yes | Minimum value |
| `max` | `float` | Yes | Maximum value |

```python
class AggregateMetrics(BaseModel):
    mean: float
    median: float
    min: float
    max: float
```

### EvaluationRun

A complete evaluation run persisted as a JSON file.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | Yes | Unique identifier: `<timestamp>[_<label>]` |
| `timestamp` | `datetime` | Yes | When the run started (ISO 8601) |
| `label` | `str \| None` | No | Optional human-readable tag |
| `plugin_type` | `str` | Yes | Pipeline plugin evaluated (e.g., `guidance`, `expert`) |
| `test_set_path` | `str` | Yes | Path to golden test set used |
| `test_case_count` | `int` | Yes | Total number of test cases |
| `success_count` | `int` | Yes | Number of successfully evaluated cases |
| `failure_count` | `int` | Yes | Number of failed cases |
| `duration_seconds` | `float` | Yes | Total wall-clock time |
| `aggregate` | `dict[str, AggregateMetrics]` | Yes | Per-metric summary statistics |
| `cases` | `list[EvaluationCase]` | Yes | Per-case results |

**Storage**: JSON file at `evaluations/<id>.json` (gitignored directory).  
**Identification**: Runs are identified by their `id` (timestamp + optional label). The `compare` command accepts two run IDs.

```python
class EvaluationRun(BaseModel):
    id: str
    timestamp: datetime
    label: str | None = None
    plugin_type: str
    test_set_path: str
    test_case_count: int
    success_count: int
    failure_count: int
    duration_seconds: float
    aggregate: dict[str, AggregateMetrics]
    cases: list[EvaluationCase]
```

### ComparisonReport

Before/after comparison between two evaluation runs.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `baseline_id` | `str` | Yes | ID of the baseline run |
| `current_id` | `str` | Yes | ID of the current run |
| `deltas` | `dict[str, MetricDelta]` | Yes | Per-metric comparison |

```python
class MetricDelta(BaseModel):
    baseline: float
    current: float
    absolute_delta: float
    percentage_change: float

class ComparisonReport(BaseModel):
    baseline_id: str
    current_id: str
    deltas: dict[str, MetricDelta]
```

## Entity Relationships

```
TestCase (JSONL file)
    │
    │ loaded by dataset.py
    ▼
EvaluationCase (in-memory during run)
    │ question, expected_answer, relevant_documents ← TestCase
    │ pipeline_answer, retrieved_contexts, retrieved_sources ← pipeline invocation
    │ scores ← RAGAS metrics
    │
    │ collected by runner.py
    ▼
EvaluationRun (JSON file)
    │ aggregate computed from cases
    │
    │ compared by report.py
    ▼
ComparisonReport (stdout / JSON)
```

## State Transitions

### EvaluationCase lifecycle

```
PENDING → RUNNING → COMPLETED (scores populated)
                  → FAILED (error populated, scores null)
```

- PENDING: TestCase loaded, not yet processed
- RUNNING: Pipeline invocation in progress
- COMPLETED: Pipeline response received and RAGAS metrics computed
- FAILED: Pipeline error or metric computation error; error message recorded, remaining cases continue (FR-010)

### EvaluationRun lifecycle

```
CREATED → RUNNING → COMPLETED (file persisted)
```

- CREATED: Test set loaded, run ID generated
- RUNNING: Cases being evaluated sequentially with progress reporting (FR-012)
- COMPLETED: All cases processed, aggregate computed, JSON written to `evaluations/`
