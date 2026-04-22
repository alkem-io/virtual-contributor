# Quickstart: Map-Reduce Summarization

**Branch**: `027-map-reduce-summarization` | **Date**: 2026-04-22

---

## Prerequisites

- Python 3.12 with Poetry
- Running LLM provider (Mistral, OpenAI, or Anthropic)
- Running ChromaDB instance
- Running RabbitMQ instance (for event-driven mode) or ability to run standalone

---

## Verification Steps

### 1. Run an ingestion with multiple documents

Either trigger a space ingest or website ingest with a corpus that has documents large enough to produce 4+ chunks each (the default `chunk_threshold`).

**Space ingest** (via RabbitMQ event or direct invocation):
```bash
PLUGIN_TYPE=ingest-space poetry run python main.py
```

**Website ingest**:
```bash
PLUGIN_TYPE=ingest-website poetry run python main.py
```

### 2. Check logs for map-reduce activity

Look for these log patterns:

```text
INFO  Map-reduce: N/M partial summaries produced
```
This confirms the map phase completed. `N` is the number of successful partial summaries, `M` is the total chunk count.

```text
INFO  Map-reduce: level X reduced N -> M
```
This confirms the tree-reduce is working. Each level merges batches of up to 10 partial summaries.

```text
INFO  Summarized document <doc_id>
```
This confirms a document summary was produced successfully.

```text
INFO  Generating body-of-knowledge summary (N sections) [model=...]
```
This confirms the BoK summary step is running with map-reduce.

### 3. Verify split-model support (optional)

To confirm that different models are used for map and reduce phases, configure different models:

```bash
# Summary model (used for map phase of doc summaries and map phase of BoK)
SUMMARIZE_LLM_MODEL=mistral-small-latest

# BoK model (used for reduce phase of doc summaries and reduce phase of BoK)
BOK_LLM_MODEL=mistral-large-latest
```

Check the logs for model name references in the `Summarizing document` and `Generating body-of-knowledge summary` lines. The map and reduce phases will use their respective configured models.

### 4. Verify fault tolerance (optional)

To test fault tolerance without a real failure, temporarily introduce a deliberate failure in test code or observe behavior when the LLM provider returns intermittent errors:

- Map failure: Look for `WARNING Map chunk X/Y failed: <error>` followed by `Map-reduce: N/M partial summaries produced` where N < M.
- Reduce failure: Look for `WARNING Reduce level X batch Y failed ... falling back to concatenation`.

### 5. Inspect stored summaries

Query ChromaDB for the summary entries:

```python
# Document summaries have embeddingType="summary" and documentId ending with "-summary"
# BoK summary has documentId="body-of-knowledge-summary"
```

Both should exist in the collection after a successful ingest run with sufficient documents.

---

## Running Tests

```bash
# All tests
poetry run pytest tests/ -v

# Map-reduce specific tests
poetry run pytest tests/core/domain/test_map_reduce.py -v
```
