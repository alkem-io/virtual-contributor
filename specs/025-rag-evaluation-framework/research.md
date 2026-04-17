# Research: RAG Evaluation Framework

**Feature**: 025-rag-evaluation-framework  
**Date**: 2026-04-06  
**Status**: Complete

## R1: Evaluation Framework Selection

### Decision: RAGAS with LangChain LLM wrapper

### Rationale

RAGAS (Retrieval Augmented Generation Assessment) is the evaluation framework recommended in the source issue and provides exactly the four metrics required by the spec: Faithfulness, AnswerRelevancy, ContextPrecision, and ContextRecall. It has first-class LangChain integration via `LangchainLLMWrapper`, which allows us to use the pipeline's own LLM (any provider behind `LLMPort`) as the evaluation judge.

Key RAGAS capabilities that map to our requirements:

| Requirement | RAGAS Feature |
|-------------|--------------|
| FR-002: Four core metrics | `Faithfulness`, `AnswerRelevancy`, `ContextPrecision`, `ContextRecall` classes |
| FR-004: Local LLM as judge | `LangchainLLMWrapper(langchain_chat_model)` — wraps any LangChain `BaseChatModel` |
| FR-006: Synthetic generation | `TestsetGenerator.from_langchain()` with local LLM + embeddings |
| FR-010: Per-case scores | `evaluate()` returns per-sample scores via `result.scores` |

RAGAS API usage pattern:
```python
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
from ragas import evaluate, EvaluationDataset, SingleTurnSample

# Wrap pipeline's own LLM (already a LangChain BaseChatModel)
evaluator_llm = LangchainLLMWrapper(langchain_chat_model)

# Configure metrics with local judge
metrics = [
    Faithfulness(llm=evaluator_llm),
    AnswerRelevancy(llm=evaluator_llm),
    ContextPrecision(llm=evaluator_llm),
    ContextRecall(llm=evaluator_llm),
]

# Build dataset from pipeline outputs
samples = [
    SingleTurnSample(
        user_input=question,
        response=pipeline_answer,
        reference=expected_answer,
        retrieved_contexts=retrieved_doc_texts,
    )
    for question, pipeline_answer, expected_answer, retrieved_doc_texts in results
]
dataset = EvaluationDataset(samples=samples)

# Run evaluation
result = evaluate(dataset=dataset, metrics=metrics)
scores_df = result.to_pandas()  # Per-case scores
```

### Alternatives Considered

1. **DeepEval**: Comparable feature set (benchmark score 83.38 vs RAGAS 82.95) and LangChain support. Rejected because: RAGAS is explicitly recommended in the source issue, and DeepEval's metric names and API differ from what stakeholders expect. Switching later would be trivial since both use LangChain wrappers.

2. **Custom LLM-as-judge implementation**: Direct prompt-based metric computation without a framework. Rejected because: would require significant prompt engineering and validation to match RAGAS's tested metric implementations. Higher risk of subtle evaluation bugs. The simplicity benefit doesn't outweigh the reliability cost.

3. **Haystack evaluation**: Part of the Haystack framework. Rejected because: would introduce a large framework dependency for a small evaluation use case. RAGAS is purpose-built for RAG evaluation.

## R2: Pipeline Invocation Pattern

### Decision: In-process invocation via IoC container with TracingKnowledgeStore

### Rationale

The spec requires "Python API import — call the pipeline's query function directly in-process" (FR-001). The existing architecture supports this cleanly:

1. **Container setup**: Reuse `core/container.py` to resolve port dependencies (LLMPort, KnowledgeStorePort)
2. **Plugin instantiation**: Create the target plugin (guidance/expert) with resolved ports
3. **Event construction**: Build `Input` events with the test question
4. **Direct invocation**: Call `plugin.handle(input_event)` → get `Response`

**Challenge**: RAGAS metrics need `retrieved_contexts` (actual document text), but plugin `handle()` methods return `Response` which has `sources` (metadata) but not the raw document text.

**Solution**: `TracingKnowledgeStore` — a Decorator-pattern wrapper around `KnowledgeStorePort` that:
- Delegates all calls to the real adapter
- Records documents returned by `query()` calls
- Exposes `get_retrieved_contexts()` to extract captured text after each pipeline invocation
- Clears state between test cases via `clear()`

This approach:
- Requires zero modifications to existing plugins or ports
- Follows the Hexagonal pattern (wraps a port, not an adapter)
- Captures exactly what the pipeline retrieved (not a separate query)

```python
class TracingKnowledgeStore:
    def __init__(self, delegate: KnowledgeStorePort):
        self._delegate = delegate
        self._captured: list[QueryResult] = []

    async def query(self, collection, query_texts, n_results) -> QueryResult:
        result = await self._delegate.query(collection, query_texts, n_results)
        self._captured.append(result)
        return result

    def get_retrieved_contexts(self) -> list[str]:
        contexts = []
        for result in self._captured:
            for doc_list in result.documents:
                contexts.extend(doc_list)
        return contexts

    def clear(self):
        self._captured = []

    # Delegate remaining methods (ingest, delete_collection) unchanged
```

### Alternatives Considered

1. **Modify plugin `handle()` to return contexts**: Would break the plugin contract (Response model) and require changes to all plugins. Rejected as contract-breaking.

2. **Run a separate knowledge store query**: Would duplicate retrieval, potentially with different results than what the plugin actually used (different query after history condensation, different score filtering). Rejected for inaccuracy.

3. **Mock the knowledge store**: Would test the LLM but not the retrieval pipeline. Rejected because the whole point is end-to-end evaluation.

## R3: Golden Test Set Format and Curation

### Decision: JSONL format with question/expected_answer/relevant_documents triples

### Rationale

Per FR-005, the golden test set uses JSONL (one JSON object per line) stored in `evaluation/golden/test_set.jsonl`. Each entry:

```json
{"question": "What is the purpose of Alkemio?", "expected_answer": "Alkemio is a platform for enabling multi-stakeholder collaboration on complex challenges.", "relevant_documents": ["https://alkem.io/about"]}
```

Field mapping to RAGAS `SingleTurnSample`:
- `question` → `user_input`
- `expected_answer` → `reference`
- `relevant_documents` → used for context recall validation (not `retrieved_contexts` — those come from the pipeline)

**Composition target** (per spec): ~30% manual (~15 cases), ~70% synthetic (~35+ cases).

**Manual curation approach**:
- Select representative questions across Alkemio space content categories
- Cover: factual queries, multi-hop questions, edge cases (no relevant docs, ambiguous queries)
- Expected answers grounded in actual indexed content
- Document references use source URI/URLs matching vector store metadata

**Validation rules**:
- Each entry must have non-empty `question`, `expected_answer`, and at least one `relevant_documents` URI
- URIs must be valid strings (format validation, not existence checking at load time)
- Duplicate questions are flagged as warnings

## R4: Synthetic Test Generation

### Decision: RAGAS TestsetGenerator with local LLM and embeddings

### Rationale

RAGAS provides `TestsetGenerator` which generates diverse test cases from source documents:

```python
from ragas.testset import TestsetGenerator

generator = TestsetGenerator.from_langchain(
    generator_llm=langchain_chat_model,   # Local LLM
    critic_llm=langchain_chat_model,       # Same local LLM
    embeddings=langchain_embeddings,       # Local embeddings
)
```

The generator creates test cases with different complexity distributions:
- **Simple**: Direct factual questions answerable from a single context
- **Multi-context**: Questions requiring information from multiple documents
- **Reasoning**: Questions requiring inference over retrieved content

**Privacy preservation**: Both generator and critic LLMs use the pipeline's own local LLM via the existing LangChain adapter, satisfying FR-006 (no data leaves infrastructure boundary).

**Document sourcing**: The generator needs source documents. We'll extract these from ChromaDB collections by querying stored chunks and their metadata. This avoids re-crawling or re-ingesting content.

**Quality review**: Generated synthetic pairs are written to a staging JSONL file for human review before inclusion in the golden test set. This matches the spec's requirement for quality review of synthetic entries.

### Alternatives Considered

1. **Custom prompt-based generation**: Write our own QA generation prompts. Rejected because RAGAS's generator handles diversity (simple/multi-context/reasoning) and quality filtering automatically.

2. **External generation service**: Use an API to generate test pairs. Rejected — violates data sovereignty (FR-004, FR-006).

## R5: Evaluation Results Persistence and Comparison

### Decision: File-based JSON with timestamp + optional label identifiers

### Rationale

Per FR-007 and FR-008:

**Result file format**: `evaluations/<timestamp>_<label>.json`
- Timestamp: ISO 8601 format (`20260406T143022`)
- Label: optional human-readable tag (e.g., `baseline`, `after-chunking-change`)
- If no label: `evaluations/20260406T143022.json`
- If label: `evaluations/20260406T143022_baseline.json`

**Result JSON structure**:
```json
{
  "id": "20260406T143022_baseline",
  "timestamp": "2026-04-06T14:30:22Z",
  "label": "baseline",
  "plugin_type": "guidance",
  "test_set_path": "evaluation/golden/test_set.jsonl",
  "test_case_count": 50,
  "duration_seconds": 842.5,
  "aggregate": {
    "faithfulness": {"mean": 0.82, "median": 0.85, "min": 0.45, "max": 1.0},
    "answer_relevancy": {"mean": 0.78, "median": 0.80, "min": 0.32, "max": 0.98},
    "context_precision": {"mean": 0.71, "median": 0.73, "min": 0.20, "max": 0.95},
    "context_recall": {"mean": 0.68, "median": 0.70, "min": 0.15, "max": 0.92}
  },
  "cases": [
    {
      "index": 0,
      "question": "What is Alkemio?",
      "expected_answer": "...",
      "pipeline_answer": "...",
      "retrieved_contexts": ["..."],
      "scores": {
        "faithfulness": 0.92,
        "answer_relevancy": 0.88,
        "context_precision": 0.85,
        "context_recall": 0.79
      },
      "duration_seconds": 4.2,
      "error": null
    }
  ],
  "failures": []
}
```

**Comparison report** (FR-008): Given two run IDs, produce per-metric deltas:
```
Metric              | Baseline | Current  | Delta    | Change
--------------------|----------|----------|----------|---------
faithfulness        | 0.820    | 0.875    | +0.055   | +6.7%
answer_relevancy    | 0.780    | 0.792    | +0.012   | +1.5%
context_precision   | 0.710    | 0.685    | -0.025   | -3.5%
context_recall      | 0.680    | 0.720    | +0.040   | +5.9%
```

### Alternatives Considered

1. **SQLite database**: Richer querying. Rejected — overkill for file-based comparison of small result sets. Adds dependency. JSONL comparison is sufficient.

2. **Single results file with appended runs**: Simpler file management. Rejected — makes concurrent runs problematic and diffs harder to review. One file per run is cleaner.

## R6: CLI Design

### Decision: Click-based CLI with subcommands

### Rationale

Click provides a clean subcommand structure that maps directly to user stories:

```bash
# US1: Run evaluation
poetry run python -m evaluation run --plugin guidance [--label baseline] [--test-set evaluation/golden/test_set.jsonl]

# US2: Generate synthetic test cases
poetry run python -m evaluation generate --collection alkem.io-knowledge --count 35 --output evaluation/golden/synthetic.jsonl

# US4: Compare two runs
poetry run python -m evaluation compare <run-id-1> <run-id-2>

# List previous runs
poetry run python -m evaluation list
```

Click is already a transitive dependency of LangChain and provides argument parsing, help generation, and error handling with minimal code.

### Alternatives Considered

1. **argparse**: Built-in, no dependency. Rejected — more boilerplate for subcommands, less ergonomic. Click is already in the dependency tree.

2. **Typer**: Modern Click wrapper with type hints. Rejected — adds another dependency for marginal benefit.

## R7: RAGAS Embeddings Requirement

### Decision: Use pipeline's existing embeddings adapter via LangChain wrapper

### Rationale

Some RAGAS metrics (notably `AnswerRelevancy`) require an embeddings model to compute semantic similarity. The pipeline already has an `EmbeddingsPort` with `OpenAICompatibleEmbeddingsAdapter` (Scaleway/local endpoint).

RAGAS accepts embeddings via `LangchainEmbeddingsWrapper`. We can either:
1. Create a thin LangChain `Embeddings` subclass that delegates to our `EmbeddingsPort`
2. Use `langchain_openai.OpenAIEmbeddings` configured with the same endpoint/key

Option 2 is simpler since the existing adapter already uses an OpenAI-compatible endpoint. We configure `OpenAIEmbeddings` with the same `EMBEDDINGS_ENDPOINT` and `EMBEDDINGS_API_KEY`.

This keeps all evaluation data local (same embedding endpoint as the pipeline).
