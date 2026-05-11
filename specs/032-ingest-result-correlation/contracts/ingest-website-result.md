# Contract: `IngestWebsiteResult` Wire Schema

**Feature Branch**: `032-ingest-result-correlation`
**Date**: 2026-04-30

## Scope

Defines the JSON-on-the-wire contract for the `IngestWebsiteResult` event published from the virtual-contributor `ingest_website` plugin to the alkemio-server result handler over RabbitMQ. This is a wire-format change governed by the constitution's "Event Schema as Wire Contract" standard.

## Before

```json
{
  "timestamp": "<int, ms-epoch>",
  "result":    "success | failure",
  "error":     "<str, empty when result=success>"
}
```

Pydantic source:

```python
class IngestWebsiteResult(EventBase):
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""
```

## After

```json
{
  "bodyOfKnowledgeId": "<str, default ''>",
  "type":              "<str, default ''>",
  "purpose":           "<str, default ''>",
  "personaId":         "<str, default ''>",
  "timestamp":         "<int, ms-epoch>",
  "result":            "success | failure",
  "error":             "<str, empty when result=success>"
}
```

Pydantic source:

```python
class IngestWebsiteResult(EventBase):
    body_of_knowledge_id: str = Field(default="", alias="bodyOfKnowledgeId")
    type: str = ""
    purpose: str = ""
    persona_id: str = Field(default="", alias="personaId")
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""
```

## Diff

```diff
+ "bodyOfKnowledgeId": "",
+ "type":              "",
+ "purpose":           "",
+ "personaId":         "",
  "timestamp":         <int>,
  "result":            "success" | "failure",
  "error":             ""
```

Four fields added. Zero fields removed, renamed, or retyped.

## Backward Compatibility

| Direction | Compatible? | Why |
|---|---|---|
| New producer → old consumer | **Yes** | Old consumer ignores the four new keys; existing keys (`timestamp`, `result`, `error`) are unchanged in name and type. |
| Old producer → new consumer | **Yes** | New consumer reads the four new keys with empty-string defaults if they are absent. (In practice no old producer remains after this image rolls out, but the schema permits it.) |
| Round-trip (Pydantic) | **Yes** | `model_validate(model_dump(..., by_alias=True))` reconstructs an equivalent model. |

## Producer Behaviour

The `ingest_website` plugin is the sole producer. After this change, `IngestWebsitePlugin.handle` populates `type`, `purpose`, and `persona_id` from the inbound `IngestWebsite` event on every return path:

| Return path | Trigger | Identification fields populated? |
|---|---|---|
| Cleanup-only success | Crawl/extract returned zero documents | Yes — copied from inbound event |
| Normal success | Pipeline ran and `IngestEngine` returned `success=True` | Yes |
| Normal failure | Pipeline ran and `IngestEngine` returned `success=False` | Yes |
| Exception | Any uncaught exception in `handle` | Yes |

`bodyOfKnowledgeId` is **not** populated by this plugin — see research.md D3.

## Consumer Expectations

The alkemio-server result handler MAY use any of the new fields to correlate the result back to a persona record. The recommended primary correlation key is `personaId`. `type` and `purpose` are advisory tags that the server may use for status reporting. `bodyOfKnowledgeId` is reserved and SHOULD be treated as advisory until a producer plugin begins populating it.

## Verification

| Check | Where |
|---|---|
| Default-value serialization with all four camelCase aliases | `tests/core/test_events.py::TestIngestWebsiteSerialization::test_result_model` |
| Explicit-value round-trip | `tests/core/test_events.py::TestIngestWebsiteSerialization::test_result_with_identification_fields` |
| Plugin propagation on normal-ingest path | `tests/plugins/test_ingest_website.py::TestIngestWebsitePlugin::test_pipeline_composition` |
| Plugin propagation on cleanup-only path | `tests/plugins/test_ingest_website.py::TestIngestWebsitePlugin::test_empty_crawl_runs_cleanup` |
