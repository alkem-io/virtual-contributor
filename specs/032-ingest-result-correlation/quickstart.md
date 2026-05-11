# Quickstart: Ingest Website Result Correlation Fields

**Feature Branch**: `032-ingest-result-correlation`
**Date**: 2026-04-30

## What This Feature Does

Adds four identification fields — `bodyOfKnowledgeId`, `type`, `purpose`, `personaId` — to the `IngestWebsiteResult` event envelope, and propagates them from the inbound `IngestWebsite` request through every code path in the website ingest plugin. The alkemio-server result handler can now correlate every received result back to the originating persona without keeping any local correlation state.

## Configuration

No new environment variables. No new feature flags. No new configuration.

## How to Verify Locally

### 1. Run the affected test files

```bash
poetry run pytest tests/core/test_events.py::TestIngestWebsiteSerialization -v
poetry run pytest tests/plugins/test_ingest_website.py::TestIngestWebsitePlugin -v
```

Expected: all tests pass, including:

- `test_result_model` — confirms default-value payload includes `bodyOfKnowledgeId`, `personaId`, `type`, `purpose`.
- `test_result_with_identification_fields` — confirms explicit values round-trip via `model_dump`.
- `test_pipeline_composition` — confirms identification fields propagate from request to result on the normal ingest path.
- `test_empty_crawl_runs_cleanup` — confirms identification fields propagate on the cleanup-only path.

### 2. Inspect a result envelope manually

```python
from core.events.ingest_website import IngestWebsiteResult, IngestionResult

result = IngestWebsiteResult(
    body_of_knowledge_id="bok-1",
    type="website",
    purpose="knowledge",
    persona_id="persona-1",
    result=IngestionResult.SUCCESS,
)
print(result.model_dump(by_alias=True))
```

Expected output (camelCase keys):

```python
{
    "bodyOfKnowledgeId": "bok-1",
    "type":              "website",
    "purpose":           "knowledge",
    "personaId":         "persona-1",
    "timestamp":         1714502400000,
    "result":            "success",
    "error":             ""
}
```

### 3. End-to-end with a live RabbitMQ (optional)

If you want to observe the wire format on RabbitMQ:

```bash
PLUGIN_TYPE=ingest_website poetry run python main.py
```

Publish an `IngestWebsite` request to the configured queue with `personaId="p-1"`, `type="website"`, `purpose="knowledge"`, and a small `baseUrl`. Capture the result message — it MUST contain `personaId: "p-1"` alongside the existing `result` and `error` fields.

## Files Changed

| File | Change |
|---|---|
| `core/events/ingest_website.py` | Added four identification fields to `IngestWebsiteResult`; documented why `bodyOfKnowledgeId` defaults empty. |
| `plugins/ingest_website/plugin.py` | Populated `type`, `purpose`, `persona_id` from the inbound event in three result-construction sites: cleanup-only, normal success/failure, exception handler. |
| `tests/core/test_events.py` | Added default-payload assertion (camelCase aliases present) and explicit-value round-trip test. |
| `tests/plugins/test_ingest_website.py` | Added propagation assertions on the normal-ingest test and on the empty-crawl cleanup test. |

## Rollout Notes

- Backward compatible — no coordinated alkemio-server release required.
- Empty-string defaults mean any existing producer or consumer that does not yet handle the new fields continues to work.
- No data migration. No persistent state involved.
