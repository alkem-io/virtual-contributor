# Data Model: Ingest Website Result Correlation Fields

**Feature Branch**: `032-ingest-result-correlation`
**Date**: 2026-04-30

## Modified Entity: `IngestWebsiteResult`

Defined in `core/events/ingest_website.py`. Inherits from `EventBase`.

### Fields (post-change)

| Attribute | Wire alias | Type | Default | New? | Notes |
|---|---|---|---|---|---|
| `body_of_knowledge_id` | `bodyOfKnowledgeId` | `str` | `""` | **Yes** | Reserved for parity with other ingest result types. Website plugin leaves this empty because websites are URL-identified, not UUID-keyed. |
| `type` | `type` | `str` | `""` | **Yes** | Echoed from `IngestWebsite.type`. Identifies content category (e.g., `"website"`). |
| `purpose` | `purpose` | `str` | `""` | **Yes** | Echoed from `IngestWebsite.purpose`. Identifies usage class (e.g., `"knowledge"`). |
| `persona_id` | `personaId` | `str` | `""` | **Yes** | Echoed from `IngestWebsite.persona_id`. The primary correlation key — the persona that owns the body of knowledge. |
| `timestamp` | `timestamp` | `int` | `int(time.time() * 1000)` | No | Unchanged. Milliseconds since epoch. |
| `result` | `result` | `IngestionResult` | `SUCCESS` | No | Unchanged. `success` \| `failure`. |
| `error` | `error` | `str` | `""` | No | Unchanged. Empty string on success; error message on failure. |

### Validation Rules

- All four new fields are plain `str` with no length, format, or content validation. The wire contract does not require non-empty values; the alkemio-server treats empty strings as "not specified".
- No `Optional[str]` / `None` is used — every field has a stable default and is always present in the dumped payload.
- Pydantic `populate_by_name = True` (inherited from `EventBase`) means both attribute names and aliases are accepted on input.

## Relationships

`IngestWebsite` (request) → `IngestWebsiteResult` (response): the plugin handler copies three of the four new fields directly from the request:

```
IngestWebsite.type        → IngestWebsiteResult.type
IngestWebsite.purpose     → IngestWebsiteResult.purpose
IngestWebsite.persona_id  → IngestWebsiteResult.persona_id
```

`IngestWebsite.base_url` is **not** copied into `IngestWebsiteResult.body_of_knowledge_id` — see research.md D3 for rationale.

`IngestWebsite` is unchanged by this feature; it already carried `type`, `purpose`, and `persona_id`.

## State Transitions

None. The model is a one-shot result envelope with no lifecycle.

## Wire Format Example

Before this change, a successful result looked like:

```json
{
  "timestamp": 1714502400000,
  "result": "success",
  "error": ""
}
```

After this change, the same result emitted from a request with `personaId="p-1"`, `type="website"`, `purpose="knowledge"`:

```json
{
  "bodyOfKnowledgeId": "",
  "type": "website",
  "purpose": "knowledge",
  "personaId": "p-1",
  "timestamp": 1714502400000,
  "result": "success",
  "error": ""
}
```

A consumer that ignores unknown fields produces the same domain semantics from both payloads.

## Backward Compatibility

- **Producers**: existing call sites that construct `IngestWebsiteResult(...)` without the new kwargs continue to compile and produce valid payloads (all fields default to `""`).
- **Consumers**: existing consumers reading `result`, `error`, `timestamp` continue to work — none of those fields changed.
- **Schema validators**: any external schema validator that enforces "no extra fields" must be relaxed to ignore the additions. The alkemio-server validator is not strict in this regard.
