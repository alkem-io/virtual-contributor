# Plan: Early ACK with Async Processing

**Spec:** 008
**Story:** alkem-io/alkemio#1824

## Architecture

The change is confined to the transport layer (`RabbitMQAdapter`) and the application bootstrap (`main.py`). No plugin code changes are required.

### Current Flow

```
RabbitMQ delivers message
  -> adapter.on_message() {
       parse JSON
       await callback(body)       # blocks until plugin.handle() completes
       await message.ack()        # ACK only on success
     }
```

### New Flow

```
RabbitMQ delivers message
  -> adapter.on_message() {
       parse JSON                  # if fails -> NACK(requeue=False)
       await message.ack()         # ACK immediately after valid JSON
       spawn background task {
         asyncio.wait_for(callback(body), timeout=pipeline_timeout)
       }
     }
```

## Affected Modules

| Module | Change | Risk |
|--------|--------|------|
| `core/adapters/rabbitmq.py` | Major rewrite of `consume()` inner `on_message` function. Add background task management, early ACK, graceful shutdown. | Medium -- core message loop, must not break existing behavior |
| `main.py` | Pass `pipeline_timeout` to `transport.consume()`. Update shutdown to drain in-flight tasks. | Low -- configuration plumbing |
| `core/config.py` | Add `pipeline_timeout` field (int, default 7200, validated > 0). | Low -- additive config field |
| `tests/core/test_rabbitmq_early_ack.py` | New test file covering early ACK behavior. | None -- new file |

## Data Model Deltas

None. No database, vector store, or event schema changes.

## Interface Contracts

### RabbitMQAdapter.consume() -- updated signature

```python
async def consume(
    self,
    queue: str,
    callback: Callable,
    pipeline_timeout: float | None = None,
) -> None
```

- `pipeline_timeout`: When set, the callback runs in a background task wrapped in `asyncio.wait_for(timeout=pipeline_timeout)`. When None, the callback runs inline (legacy behavior for tests).

### RabbitMQAdapter -- new methods

```python
async def drain_tasks(self, timeout: float = 30.0) -> None:
    """Wait for all in-flight background tasks to complete, up to timeout."""
```

### BaseConfig -- new field

```python
pipeline_timeout: int = 7200  # seconds; >= 0, where 0 = no timeout
```

## Test Strategy

### Unit Tests (new file: `tests/core/test_rabbitmq_early_ack.py`)

1. **test_valid_message_acked_before_callback** -- Verify ACK is called before callback starts executing.
2. **test_invalid_json_nacked** -- Verify non-JSON message is NACK'd with requeue=False.
3. **test_callback_error_publishes_result** -- Verify that callback exceptions do not prevent error result publishing.
4. **test_pipeline_timeout_fires** -- Verify that a slow callback triggers TimeoutError.
5. **test_graceful_shutdown_drains_tasks** -- Verify `drain_tasks()` waits for in-flight work.

### Existing Tests

All existing tests must pass unchanged. The RabbitMQAdapter is mocked (`MockTransportPort`) in plugin tests, so the internal change is invisible to them.

## Rollout Notes

- **Backward compatible** -- No wire format changes. Existing RabbitMQ queues and exchanges are unchanged.
- **Config** -- New `PIPELINE_TIMEOUT` env var. Default 7200s means zero-config upgrade.
- **Monitoring** -- After deployment, `consumer_timeout` can be restored to default (30 min) since messages are ACK'd immediately.
- **Rollback** -- Safe to revert; the only behavior difference is ACK timing. Late ACK is the pre-existing behavior.
