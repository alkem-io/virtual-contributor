# ADR 0009: Configurable Summarization LLM

## Status
Accepted

## Context
Ingest pipeline summarization is compute-intensive but does not require the same model quality as user-facing responses. Running summarization on the primary LLM wastes expensive capacity on a task where a cheaper, faster model would suffice. Additionally, retrieval parameters (number of results, score thresholds, context budgets) were hardcoded, preventing tuning without code changes.

## Decision

### Separate summarization LLM
A distinct LLM instance can be configured for ingest pipeline summarization via `SUMMARIZE_LLM_*` environment variables (`PROVIDER`, `MODEL`, `API_KEY`). All three fields are required to activate the separate instance — any subset falls back to the primary LLM with a warning log.

### Per-plugin retrieval parameters
Expert and guidance plugins have independent retrieval configuration:
- `{PLUGIN}_N_RESULTS` — number of chunks to retrieve
- `{PLUGIN}_MIN_SCORE` — minimum relevance score threshold
- `MAX_CONTEXT_CHARS` — global context budget; lowest-scoring chunks dropped first

### Environment-only configuration
All configuration is via environment variables. Per-space or per-knowledge-base configuration storage is explicitly out of scope — the system is configured at deployment level, not per-tenant.

## Consequences
- **Positive**: Ingest pipelines can use a cheaper/faster model (e.g., Mistral Small) while user-facing queries use a more capable model.
- **Positive**: Retrieval parameters are tunable without code changes or redeployment (environment variable update + restart).
- **Positive**: Three-field activation requirement prevents accidental partial configuration.
- **Negative**: No per-tenant configuration — all spaces sharing an instance use the same retrieval parameters.
