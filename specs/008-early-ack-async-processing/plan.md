# Plan: Early ACK with Async Processing

**Spec ID:** 008
**Story:** alkem-io/alkemio#1824
**Date:** 2026-04-08

## Architecture

### Design Pattern: Early ACK + Fire-and-Forget Task

The RabbitMQ consumer callback (`on_message` in `RabbitMQAdapter`) will be restructured into two phases:

1. **Synchronous phase (pre-ACK):** Parse raw bytes to JSON. On failure, use existing retry-with-header logic. On success, ACK immediately.
2. **Async phase (post-ACK):** Dispatch the parsed message body to the application callback as an `asyncio.Task`. The task runs independently; the consumer callback returns.

The application callback (`on_message` in `main.py`) wraps `plugin.handle()` in `asyncio.wait_for(timeout=pipeline_timeout)` and publishes results (success or error) to the result queue.

### Data Flow

```
RabbitMQ delivers message
  |
  v
RabbitMQAdapter.on_message():
  1. JSON parse (fail -> retry/reject, succeed -> continue)
  2. message.ack()
  3. asyncio.create_task(callback(body))
  4. return immediately
  |
  v
main.on_message(body) [runs as background task]:
  1. router.parse_event(body)
  2. asyncio.wait_for(plugin.handle(event), timeout=pipeline_timeout)
  3. publish result to result queue
  4. on error/timeout: publish error result to result queue
```

## Affected Modules

### `core/adapters/rabbitmq.py` -- Primary change

- `on_message` closure inside `consume()`: Move ACK before callback invocation. Dispatch callback as `asyncio.create_task`. Track tasks for graceful shutdown.
- Add `_tasks: set[asyncio.Task]` instance variable for in-flight task tracking.
- Add done-callback on each task to log unhandled exceptions (prevents silent failures in fire-and-forget tasks).
- Add `drain()` method to wait for in-flight tasks during shutdown.

### `main.py` -- Secondary change

- `on_message` callback: Wrap `plugin.handle()` in `asyncio.wait_for(timeout=config.pipeline_timeout)`.
- Handle `asyncio.TimeoutError` with error result publication.
- Shutdown sequence: Call `transport.drain()` before `transport.close()`.

### `core/config.py` -- Config addition

- Add `pipeline_timeout: int = 3600` field to `BaseConfig`.
- Add validation: must be > 0.

### Tests -- New file

- `tests/core/test_rabbitmq_early_ack.py`: Unit tests for the early ACK behavior, task dispatch, retry on JSON parse failure, and drain.
- `tests/test_pipeline_timeout.py`: Integration-style test for the outer timeout in `on_message`.

## Data Model Deltas

None. No schema changes to events, no database migrations.

## Interface Contracts

### `RabbitMQAdapter` changes

```python
class RabbitMQAdapter:
    _tasks: set[asyncio.Task]  # NEW: track in-flight processing tasks

    async def consume(self, queue: str, callback: Callable) -> None:
        # CHANGED: ACK before callback, dispatch as task
        ...

    async def drain(self, timeout: float = 30.0) -> None:
        # NEW: wait for in-flight tasks to complete
        ...
```

### `BaseConfig` addition

```python
class BaseConfig(BaseSettings):
    pipeline_timeout: int = 3600  # NEW: seconds
```

### Callback contract (unchanged)

```python
async def callback(body: dict) -> None: ...
```

The callback signature is unchanged. The callback is now invoked inside an `asyncio.Task` instead of inline, but this is transparent to the callback.

## Test Strategy

1. **Unit tests for RabbitMQAdapter early ACK:**
   - Verify ACK is called before callback.
   - Verify callback runs as a background task.
   - Verify JSON parse failure triggers retry/reject (not ACK).
   - Verify `drain()` waits for in-flight tasks.

2. **Unit tests for main.on_message timeout:**
   - Verify `asyncio.wait_for` timeout cancels slow handlers.
   - Verify timeout publishes error result to result queue.

3. **Existing test suite:**
   - All current tests must pass unchanged.

## Rollout Notes

- **Backward compatible:** `PIPELINE_TIMEOUT` defaults to 3600s. No new required env vars.
- **Observable:** Timeout errors appear in logs and result queue.
- **Reversible:** Removing the change and reverting to late ACK is a single commit revert.
- **Post-deploy:** `consumer_timeout` on RabbitMQ server can be restored to default (30 min) since messages are now ACKed immediately.
