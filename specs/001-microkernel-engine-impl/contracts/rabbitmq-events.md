# RabbitMQ Event Contracts

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30
**Verified against**: Source repository code (2026-03-30)
**Compatibility**: Must produce/consume identical wire format as current standalone services

## Transport Configuration

### Queue Names (per plugin — verified from .env.default files)

| Plugin | Input Queue | Result Queue | Result Routing Key |
|--------|------------|--------------|-------------------|
| expert | `virtual-contributor-engine-expert` | `virtual-contributor-invoke-engine-result` | `invoke-engine-result` |
| generic | `virtual-contributor-engine-generic` | `virtual-contributor-invoke-engine-result` | `invoke-engine-result` |
| guidance | `virtual-contributor-engine-guidance` | `virtual-contributor-invoke-engine-result` | `invoke-engine-result` |
| openai-assistant | `virtual-contributor-engine-openai-assistant` | `virtual-contributor-invoke-engine-result` | `invoke-engine-result` |
| ingest-website | `virtual-contributor-ingest-website` | `virtual-contributor-ingest-website-result` | `ingest-website-result` |
| ingest-space | `virtual-contributor-ingest-body-of-knowledge` | `virtual-contributor-ingest-body-of-knowledge-result` | `IngestSpaceResult` |

### Exchange

| Parameter | Value |
|-----------|-------|
| Name | `event-bus` (from `RABBITMQ_EVENT_BUS_EXCHANGE`) |
| Type | **DIRECT** (not topic) |
| Durable | Yes |

### Queue Properties

| Property | Value |
|----------|-------|
| `auto_delete` | `false` |
| `durable` | `true` |

Result queues are bound to the exchange via their respective routing keys.

### Connection Parameters

| Parameter | Env Var | Default |
|-----------|---------|---------|
| Host | `RABBITMQ_HOST` | `rabbitmq` |
| Port | `RABBITMQ_PORT` | `5672` |
| User | `RABBITMQ_USER` | `alkemio-admin` |
| Password | `RABBITMQ_PASSWORD` | `alkemio!` |

### Consumer Settings

- **Prefetch count**: 1 (sequential processing per plugin)
- **Acknowledgment**: Manual ACK after successful processing (Python services). Note: ingest-space (TypeScript) uses `noAck: true` — the Python port should switch to manual ACK for consistency with at-least-once delivery semantics.
- **Dead-letter**: Messages NACKed after repeated failures route to dead-letter queue
- **Serialization**: JSON with UTF-8 encoding

## Message Envelope Formats (Wire Format)

### Engine Query Messages (Input → Response)

**Incoming message body** (consumed from engine queue):
```json
{
  "input": {
    "engine": "string",
    "operation": "query",
    "userID": "string",
    "message": "string",
    "bodyOfKnowledgeID": "string | null",
    "contextID": "",
    "history": [
      {
        "content": "string",
        "role": "human | assistant"
      }
    ],
    "externalMetadata": {
      "threadId": "string | null"
    },
    "externalConfig": {
      "apiKey": "string | null",
      "assistantId": "string | null",
      "model": "string | null"
    },
    "displayName": "string",
    "description": "",
    "personaID": "string",
    "language": "EN",
    "resultHandler": {
      "action": "postReply | postMessage | none",
      "roomDetails": {
        "roomID": "string",
        "actorID": "string",
        "threadID": "string",
        "vcInteractionID": "string"
      }
    },
    "prompt": ["string"],
    "promptGraph": {}
  }
}
```

**Note**: The `input` key wraps the Input model. The top-level body may also contain `eventType` to distinguish message types.

**Published response**:
```json
{
  "response": {
    "result": "string | null",
    "humanLanguage": "string | null",
    "resultLanguage": "string | null",
    "knowledgeLanguage": "string | null",
    "originalResult": "string | null",
    "sources": [
      {
        "chunkIndex": 0,
        "embeddingType": "string | null",
        "documentId": "string | null",
        "source": "string | null",
        "title": "string | null",
        "type": "string | null",
        "score": 0.85,
        "uri": "string | null"
      }
    ],
    "threadId": "string | null"
  },
  "original": {
    "...Input fields..."
  }
}
```

### Ingest Website Messages

**Incoming message body** (consumed from ingest-website queue):
```json
{
  "eventType": "IngestWebsite",
  "baseUrl": "string",
  "type": "string",
  "purpose": "string",
  "personaId": "string",
  "summarizationModel": "mistral-medium"
}
```

**Note**: Ingest messages are NOT wrapped in an `input` key. They use `eventType` at the top level for discrimination.

**Published result**:
```json
{
  "response": {
    "timestamp": 1711756800000,
    "result": "success | failure",
    "error": ""
  }
}
```

### Ingest Body of Knowledge Messages (ingest-space)

**Incoming message body** (consumed from ingest-body-of-knowledge queue):
```json
{
  "bodyOfKnowledgeId": "string",
  "type": "alkemio-space | alkemio-knowledge-base",
  "purpose": "knowledge | context",
  "personaId": "string"
}
```

**Published result**:
```json
{
  "response": {
    "bodyOfKnowledgeId": "string",
    "type": "string",
    "purpose": "string",
    "personaId": "string",
    "timestamp": 1711756800000,
    "result": "success | failure",
    "error": {
      "code": "string | null",
      "message": "string | null"
    }
  }
}
```

## Message Flow Patterns

### Engine Query (Request/Response)

```
Alkemio Server
    │
    ├──publish──→ [queue: virtual-contributor-engine-{plugin}]
    │              body: {"input": {Input fields}}
    │                           │
    │                     Router: Input(**body["input"])
    │                           │
    │                     Plugin.handle(Input) → Response
    │                           │
    │                     Publish: {"response": Response, "original": Input}
    │                           │
    ←──consume──← [exchange: event-bus, key: invoke-engine-result]
                   [queue: virtual-contributor-invoke-engine-result]
```

### Ingest Website (Fire and Notify)

```
Alkemio Server
    │
    ├──publish──→ [queue: virtual-contributor-ingest-website]
    │              body: {"eventType": "IngestWebsite", ...fields}
    │                           │
    │                     Router: IngestWebsite(**body)
    │                           │
    │                     Plugin.handle(IngestWebsite) → IngestWebsiteResult
    │                           │
    │                     Publish: {"response": IngestWebsiteResult}
    │                           │
    ←──consume──← [exchange: event-bus, key: ingest-website-result]
                   [queue: virtual-contributor-ingest-website-result]
```

### Ingest Space (Fire and Notify)

```
Alkemio Server
    │
    ├──publish──→ [queue: virtual-contributor-ingest-body-of-knowledge]
    │              body: {IngestBodyOfKnowledge fields}
    │                           │
    │                     Router: IngestBodyOfKnowledge(**body)
    │                           │
    │                     Plugin.handle(IngestBodyOfKnowledge) → IngestBodyOfKnowledgeResult
    │                           │
    │                     Publish: {"response": IngestBodyOfKnowledgeResult}
    │                           │
    ←──consume──← [exchange: event-bus, key: IngestSpaceResult]
                   [queue: virtual-contributor-ingest-body-of-knowledge-result]
```

## Backward Compatibility Requirements

1. **Queue names**: Must match exactly — the Alkemio server is configured with these specific queue names. Note the ingest-space queue is `virtual-contributor-ingest-body-of-knowledge` (not `virtual-contributor-ingest-space`).
2. **Field names**: Wire format must use camelCase aliases (e.g., `bodyOfKnowledgeID`, `personaID`)
3. **Message envelope**: Engine queries use `{"input": {...}}` wrapper. Ingest events are at the top level with `eventType` discriminator.
4. **Response envelope**: All responses use `{"response": {...}, "original": {...}}` wrapper (engine queries include original input; ingest may omit original).
5. **Exchange type**: DIRECT (not topic or fanout)
6. **Routing keys**: Exact strings as documented — case-sensitive (note `IngestSpaceResult` uses PascalCase)
7. **Serialization**: JSON with UTF-8 encoding, no compression
8. **Content type**: `application/json` message property
9. **Role enum values**: `"human"` and `"assistant"` (not `"user"`)

## Contract Tests

Each event model must have a contract test that:
1. Serializes a known event instance with `model_dump(by_alias=True)`
2. Asserts all field names are camelCase in the output
3. Asserts the message envelope format is correct (`{"input": {...}}` for queries, top-level for ingest)
4. Deserializes a known JSON payload (captured from production) and asserts correct model population
5. Round-trips: `model.model_dump(by_alias=True)` → JSON → `Model.model_validate(json)` → assert equal
6. Validates enum values: `MessageSenderRole` uses `"human"` not `"user"`, `IngestionResult` uses `"success"`/`"failure"`
