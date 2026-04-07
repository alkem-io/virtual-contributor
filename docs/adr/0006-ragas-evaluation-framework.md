# ADR 0006: RAGAS as RAG Evaluation Framework

## Status
Accepted

## Context
The virtual contributor pipeline needs a systematic way to measure answer quality after changes to retrieval parameters, chunking strategies, or prompt engineering. Manual spot-checking is unreliable and doesn't scale. The team requires objective, repeatable metrics covering faithfulness, answer relevance, context precision, and context recall — the four dimensions that map directly to RAG pipeline quality.

Three evaluation approaches were considered:
1. **RAGAS** — purpose-built RAG evaluation library with LangChain integration
2. **DeepEval** — comparable feature set (benchmark score 83.38 vs RAGAS 82.95)
3. **Custom LLM-as-judge** — direct prompt-based metric computation

## Decision
Use **RAGAS** (`ragas ^0.2`) as the evaluation framework, accessed through its LangChain wrapper (`LangchainLLMWrapper`, `LangchainEmbeddingsWrapper`).

Key design choices:
1. **Pipeline's own LLM as judge**: RAGAS metrics are configured with `LangchainLLMWrapper(pipeline_chat_model)`, reusing the same LLM that powers the pipeline. No evaluation data leaves the infrastructure boundary.
2. **TracingKnowledgeStore decorator**: A wrapper around `KnowledgeStorePort` captures retrieved documents during pipeline execution, providing the `retrieved_contexts` that RAGAS needs — without modifying existing plugins or ports.
3. **In-process invocation**: The evaluation calls `plugin.handle()` directly via the existing IoC container, not through RabbitMQ or HTTP.
4. **Four core metrics**: `Faithfulness`, `AnswerRelevancy`, `LLMContextPrecisionWithoutReference`, `LLMContextRecall` — matching the spec's four evaluation dimensions.

## Consequences
- **Positive**: Battle-tested metric implementations reduce risk of subtle evaluation bugs vs. custom prompts.
- **Positive**: LangChain integration means any LLM provider works as judge with zero code changes (same provider factory).
- **Positive**: Synthetic test generation (`TestsetGenerator`) is included, supporting golden test set expansion.
- **Positive**: Data sovereignty maintained — all evaluation uses the pipeline's own LLM and embeddings.
- **Negative**: External dependency (~5 transitive packages) increases supply chain surface.
- **Negative**: RAGAS metric implementations are opaque — if a metric produces unexpected scores, debugging requires understanding RAGAS internals.
- **Negative**: Tied to RAGAS's metric definitions — custom metrics would require either contributing upstream or bypassing the framework.
