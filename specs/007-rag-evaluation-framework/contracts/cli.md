# CLI Contract: RAG Evaluation Framework

**Module**: `evaluation.cli` (invoked as `python -m evaluation`)  
**Framework**: Click  
**Date**: 2026-04-06

## Commands

### `run` — Execute evaluation suite (US1, FR-001, FR-002, FR-003, FR-010, FR-012)

Runs the full evaluation suite against the pipeline and persists results.

```
poetry run python -m evaluation run [OPTIONS]
```

| Option | Type | Default | Required | Description |
|--------|------|---------|----------|-------------|
| `--plugin` | `str` | `guidance` | No | Plugin type to evaluate (`guidance`, `expert`) |
| `--label` | `str` | None | No | Optional label for the run (appended to timestamp in filename) |
| `--test-set` | `path` | `evaluation/golden/test_set.jsonl` | No | Path to golden test set JSONL file |
| `--body-of-knowledge-id` | `str` | None | No | Body of knowledge ID for expert plugin |

**Behavior**:
1. Loads and validates the golden test set
2. Initializes the pipeline (container, plugin, tracing wrapper)
3. Configures RAGAS metrics with the pipeline's LLM as judge
4. For each test case (sequential):
   - Logs progress: `[N/TOTAL] Evaluating: "question..."` (FR-012)
   - Invokes pipeline with the question
   - Captures response and retrieved contexts
   - On failure: records error, continues to next case (FR-010)
   - Logs completion: `done (X.Xs)`
5. Runs RAGAS metric evaluation on all successful cases
6. Computes aggregate statistics (mean, median, min, max per metric)
7. Persists results to `evaluations/<timestamp>[_<label>].json`
8. Prints summary report to stdout

**Exit codes**:
- `0`: Evaluation completed (regardless of individual case failures)
- `1`: Fatal error (test set not found, pipeline initialization failed, judge LLM unreachable)

**Output** (stdout):
```
RAG Evaluation Run: 20260406T143022_baseline
Plugin: guidance | Test cases: 50 | Duration: 14m 2s

Results:
  Metric              Mean    Median  Min     Max
  faithfulness        0.820   0.850   0.450   1.000
  answer_relevancy    0.780   0.800   0.320   0.980
  context_precision   0.710   0.730   0.200   0.950
  context_recall      0.680   0.700   0.150   0.920

Failures: 2/50
  [7]  "How does..." — Pipeline timeout after 120s
  [34] "What are..." — Judge model returned empty score

Results saved: evaluations/20260406T143022_baseline.json
```

---

### `compare` — Compare two evaluation runs (US4, FR-008)

Produces a before/after comparison report between any two runs.

```
poetry run python -m evaluation compare <baseline-id> <current-id>
```

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `baseline-id` | `str` | Yes | Run ID of the baseline (e.g., `20260406T143022_baseline`) |
| `current-id` | `str` | Yes | Run ID of the current run |

**Behavior**:
1. Loads both run result files from `evaluations/`
2. Computes per-metric deltas (absolute and percentage)
3. Prints comparison table to stdout

**Exit codes**:
- `0`: Comparison completed
- `1`: One or both run IDs not found

**Output** (stdout):
```
Comparison: 20260406T143022_baseline vs 20260407T091500_after-chunking

Metric              Baseline  Current   Delta     Change
faithfulness        0.820     0.875     +0.055    +6.7%
answer_relevancy    0.780     0.792     +0.012    +1.5%
context_precision   0.710     0.685     -0.025    -3.5%
context_recall      0.680     0.720     +0.040    +5.9%

Overall: 3/4 metrics improved, 1/4 regressed
```

---

### `generate` — Generate synthetic test cases (US2, FR-006)

Generates synthetic question/answer pairs from indexed content using the local LLM.

```
poetry run python -m evaluation generate [OPTIONS]
```

| Option | Type | Default | Required | Description |
|--------|------|---------|----------|-------------|
| `--collection` | `str` | — | Yes | ChromaDB collection name to source documents from |
| `--count` | `int` | `35` | No | Number of synthetic test cases to generate |
| `--output` | `path` | `evaluation/golden/synthetic.jsonl` | No | Output file path for generated pairs |

**Behavior**:
1. Fetches source documents from the specified ChromaDB collection
2. Uses RAGAS TestsetGenerator with the pipeline's local LLM
3. Generates test pairs with diversity (simple, multi-context, reasoning)
4. Writes to output JSONL file (staging, not directly to golden test set)
5. Prints summary of generated cases

**Exit codes**:
- `0`: Generation completed
- `1`: Collection not found, LLM unreachable, or insufficient source documents

**Output** (stdout):
```
Synthetic Generation: alkem.io-knowledge
Source documents: 142 chunks
Generating 35 test cases...
  Simple:        18 (51%)
  Multi-context: 14 (40%)
  Reasoning:      3 (9%)

Generated: evaluation/golden/synthetic.jsonl (35 cases)
Review these before merging into the golden test set.
```

---

### `list` — List previous evaluation runs

Lists all persisted evaluation runs with summary info.

```
poetry run python -m evaluation list
```

**Behavior**:
1. Scans `evaluations/` directory for JSON files
2. Reads metadata (id, timestamp, label, plugin, case count, aggregate means)
3. Prints sorted by timestamp (newest first)

**Exit codes**:
- `0`: Always (empty list if no runs exist)

**Output** (stdout):
```
Evaluation Runs:
  ID                              Plugin     Cases  Faith.  Relev.  Prec.   Recall
  20260407T091500_after-chunking  guidance   50     0.875   0.792   0.685   0.720
  20260406T143022_baseline        guidance   50     0.820   0.780   0.710   0.680

2 runs found in evaluations/
```

## Environment Variables

The evaluation framework inherits all pipeline environment variables (LLM, embeddings, ChromaDB configuration). No additional environment variables are introduced.

Required for evaluation:
- `LLM_PROVIDER`, `LLM_API_KEY` (or `LLM_BASE_URL` for local), `LLM_MODEL` — for both pipeline and judge
- `EMBEDDINGS_ENDPOINT`, `EMBEDDINGS_API_KEY`, `EMBEDDINGS_MODEL_NAME` — for AnswerRelevancy metric
- `VECTOR_DB_HOST`, `VECTOR_DB_PORT` — for pipeline retrieval and document sourcing
