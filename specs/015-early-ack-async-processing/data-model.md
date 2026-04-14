# Data Model: Early ACK with Async Processing

**Feature Branch**: `story/1824-early-ack-async-processing`
**Date**: 2026-04-14

## Overview

This feature adds a configuration field for pipeline timeout and modifies the RabbitMQ adapter to expose raw message handles. No new database tables, event schemas, or domain entities are created. All changes are additive.

## Entity: BaseConfig (modified)

**File**: `core/config.py`

### New Field -- Pipeline Timeout

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `pipeline_timeout` | `int` | `3600` | `PIPELINE_TIMEOUT` | Maximum duration (seconds) for any `plugin.handle()` call. Must be > 0. |

**Validation**: Checked in `_resolve_backward_compat_and_validate()`. Values <= 0 raise `ValueError`.

## Entity: RabbitMQAdapter (modified)

**File**: `core/adapters/rabbitmq.py`

### New Method -- consume_with_message

| Method | Signature | Description |
|--------|-----------|-------------|
| `consume_with_message` | `async def consume_with_message(self, queue: str, callback: Callable[[dict, AbstractIncomingMessage], Awaitable[None]]) -> None` | Declares queue, binds to exchange, passes parsed JSON body + raw message to callback. Does NOT ACK or reject. |

**Behavior**:
- Declares the queue and binds it to the exchange (same as `consume()`)
- Deserializes message body to JSON dict
- Passes `(body, message)` to callback
- Does NOT handle ACK, reject, or retry -- all message lifecycle is the callback's responsibility

### Existing Method -- consume (unchanged)

The existing `consume()` method continues to work as before. No signature or behavior changes.

## Entity: on_message callback (modified)

**File**: `main.py`

### Changed Behavior

- **Before**: Single callback for all events. Adapter handles ACK/reject.
- **After**: Callback receives raw message. Branching logic based on event type:

| Event Type | ACK Timing | Error Handling | Task Management |
|------------|-----------|----------------|-----------------|
| `IngestWebsite`, `IngestBodyOfKnowledge` | Early (before `handle()`) | Error envelope published | Fire-and-forget asyncio task |
| `Input` | Late (after `handle()`) | Retry/reject logic replicated | Inline execution |

### New Runtime State

| State | Type | Scope | Description |
|-------|------|-------|-------------|
| `_active_tasks` | `set[asyncio.Task]` | Module-level | Tracks in-flight pipeline tasks for graceful shutdown |

## Relationships

```text
BaseConfig
  └── pipeline_timeout → used by on_message (asyncio.wait_for)

RabbitMQAdapter
  └── consume_with_message() → passes (body, message) to on_message

on_message (main.py)
  ├── ingest events → message.ack() → asyncio.create_task(_run_pipeline)
  │                                    └── _active_tasks.add(task)
  └── engine queries → plugin.handle() → message.ack()

_run_pipeline (main.py)
  ├── asyncio.wait_for(plugin.handle(), timeout=pipeline_timeout)
  ├── success → transport.publish(result)
  ├── timeout → transport.publish(error)
  ├── exception → transport.publish(error)
  └── done_callback → _active_tasks.discard(task)

Graceful Shutdown
  └── asyncio.wait(_active_tasks, timeout=30) → cancel remaining
```

## State Transitions

### Message Lifecycle -- Ingest Events

```
RECEIVED → VALIDATED → ACKED → TASK_CREATED → PROCESSING → RESULT_PUBLISHED
                                                         → ERROR_PUBLISHED (on failure)
```

### Message Lifecycle -- Engine Queries

```
RECEIVED → VALIDATED → PROCESSING → RESULT_PUBLISHED → ACKED
                                  → ERROR → RETRY/REJECT
```
