# Quickstart: RAG Evaluation Framework

**Feature**: 025-rag-evaluation-framework  
**Date**: 2026-04-06

## Prerequisites

1. **Pipeline operational**: ChromaDB running with indexed content, LLM provider configured
2. **Environment variables**: Same `.env` as the pipeline (LLM, embeddings, vector DB config)
3. **Dependencies installed**: `poetry install` (includes RAGAS and evaluation dependencies)

## 1. Run Your First Evaluation

```bash
# Run evaluation against the guidance plugin using the golden test set
poetry run python -m evaluation run --plugin guidance --label baseline
```

This will:
- Load the curated test cases from `evaluation/golden/test_set.jsonl`
- Query the pipeline with each test question (in-process, no server needed)
- Score each response using RAGAS metrics with the local LLM as judge
- Save results to `evaluations/20260406T143022_baseline.json`
- Print a summary report

## 2. Make a Pipeline Change, Then Compare

```bash
# After modifying retrieval params, chunking, prompts, etc.
poetry run python -m evaluation run --plugin guidance --label after-change

# Compare the two runs
poetry run python -m evaluation compare 20260406T143022_baseline 20260407T091500_after-change
```

## 3. Generate Synthetic Test Cases

```bash
# Generate 35 synthetic QA pairs from indexed content
poetry run python -m evaluation generate --collection alkem.io-knowledge --count 35

# Review the generated file, then merge into golden test set
cat evaluation/golden/synthetic.jsonl >> evaluation/golden/test_set.jsonl
```

## 4. List Previous Runs

```bash
poetry run python -m evaluation list
```

## Golden Test Set Format

Each line in `evaluation/golden/test_set.jsonl`:

```json
{"question": "What is Alkemio?", "expected_answer": "Alkemio is a platform for enabling multi-stakeholder collaboration on complex challenges.", "relevant_documents": ["https://alkem.io/about"]}
```

## Key Design Decisions

- **In-process invocation**: The evaluation calls the pipeline directly via Python import — no running server needed
- **Local LLM judge**: All evaluation metrics are computed using the pipeline's own LLM — no data leaves the infrastructure
- **TracingKnowledgeStore**: A decorator wrapper captures retrieved documents during pipeline execution for RAGAS metrics, without modifying existing plugins
- **File-based results**: Each run produces a JSON file in `evaluations/` (gitignored) — compare any two runs ad-hoc
