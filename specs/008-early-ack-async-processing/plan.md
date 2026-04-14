# Implementation Plan: Early ACK with Async Processing

**Branch:** `story/1824-early-ack-async-processing` | **Date:** 2026-04-14 | **Spec:** [spec.md](spec.md)
**Story:** #1824 (alkem-io/alkemio#1820)

## Summary

Decouple RabbitMQ message acknowledgment from pipeline completion to eliminate consumer_timeout redelivery loops. Ingest messages are ACKed immediately after schema validation, then processed asynchronously as fire-and-forget tasks. An outer pipeline timeout wraps all `plugin.handle()` calls regardless of event type. Engine queries retain the existing late-ACK + retry pattern.

## Technical Context

**Language/Version:** Python 3.12 (Poetry)
**Primary Dependencies:** aio-pika 9.5.7, pydantic-settings ^2.11.0
**Testing:** pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform:** Linux server (Docker containers, K8s)
**Project Type:** Microkernel service
**Performance Goals:** Eliminate infinite redelivery loops; 30-minute consumer_timeout is safe again
**Constraints:** No changes to TransportPort, PluginContract, or plugin internals
**Scale/Scope:** 3 files modified + 1 new test file, ~120 lines added

## Architecture

### Design Decision: Where to Split ACK from Processing

The `RabbitMQAdapter.consume()` method currently wraps the entire callback in a try/except that handles ACK/reject. We need the callback (`on_message` in `main.py`) to control ACK timing based on event type.

**Approach:** Modify `RabbitMQAdapter.consume()` to accept an `early_ack_callback` parameter -- a new callback signature that receives both the parsed JSON body and the raw `aio_pika.AbstractIncomingMessage`. This lets the application layer decide ACK timing. The adapter still handles JSON deserialization and the retry/requeue loop for callbacks that raise, but only when using the original callback style.

Revised approach (simpler): Keep the adapter's `consume()` signature unchanged. Instead, add a new `consume_with_message()` method on `RabbitMQAdapter` that passes both the parsed body and the raw message to the callback. The `on_message` callback in `main.py` will use this method and handle ACK/retry itself.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/config.py` | Add `pipeline_timeout: int = 3600` field with validation |
| `core/adapters/rabbitmq.py` | Add `consume_with_message()` method |
| `main.py` | Rewrite `on_message` to support early ACK for ingest events, outer timeout for all events, fire-and-forget task management, graceful shutdown of in-flight tasks |
| `tests/core/test_early_ack.py` (new) | Unit tests for early ACK behavior, timeout, task tracking |

### Data Model Deltas

None. No changes to event models, database schemas, or wire formats.

### Interface Contracts

**TransportPort:** Unchanged. The new `consume_with_message()` method is on the concrete `RabbitMQAdapter` only.

**RabbitMQAdapter.consume_with_message():**
```python
async def consume_with_message(
    self,
    queue: str,
    callback: Callable[[dict, aio_pika.abc.AbstractIncomingMessage], Awaitable[None]],
) -> None:
```
- Declares queue, binds to exchange
- Passes parsed JSON body + raw message to callback
- Does NOT ACK or reject -- that is the callback's responsibility

### Message Flow After Change

**Ingest events:**
```
RabbitMQ -> Adapter.consume_with_message() -> on_message(body, message)
  -> Router.parse_event(body)  [validates schema]
  -> message.ack()             [early ACK -- before processing]
  -> asyncio.create_task(...)  [fire-and-forget]
      -> asyncio.wait_for(plugin.handle(event), timeout=pipeline_timeout)
      -> transport.publish(result)
      -> [on exception: transport.publish(error result)]
```

**Engine queries:**
```
RabbitMQ -> Adapter.consume_with_message() -> on_message(body, message)
  -> Router.parse_event(body)  [validates schema]
  -> asyncio.wait_for(plugin.handle(event), timeout=pipeline_timeout)
  -> transport.publish(result)
  -> message.ack()             [late ACK -- after processing]
  -> [on exception: transport.publish(error), retry/reject]
```

### Test Strategy

1. **Unit tests** (`tests/core/test_early_ack.py`):
   - Ingest event: message ACKed before handle() runs
   - Ingest event: result published on success
   - Ingest event: error result published on failure
   - Ingest event: timeout triggers error result
   - Engine query: message ACKed after handle() completes
   - Engine query: timeout triggers error response
   - Graceful shutdown: in-flight tasks awaited

2. **Existing tests must pass unchanged** -- no plugin or domain logic changes.

### Rollout Notes

- The `PIPELINE_TIMEOUT` env var defaults to 3600s. Operators can tune this.
- After deployment, the RabbitMQ server-side `consumer_timeout` can be restored to the default 30 minutes, since ingest messages will be ACKed within milliseconds.
- Content-hash deduplication ensures that re-triggers after crashes are safe (idempotent).

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Automated change, no interactive steps |
| P2 | SOLID Architecture | PASS | Open/Closed: new method on adapter, no port changes. SRP: ACK strategy in application layer, not adapter |
| P3 | No Vendor Lock-in | PASS | aio-pika is the existing RabbitMQ client, no new deps |
| P4 | Optimised Feedback Loops | PASS | Config validation catches invalid timeout at startup |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full spec -> plan -> tasks -> implement |
| P7 | No Filling Tests | PASS | Tests verify actual ACK timing and error behavior |
| P8 | ADR | N/A | No new ports, no new external deps |
| AS:Microkernel | Microkernel Architecture | PASS | Change is in main.py (application wiring) and adapter |
| AS:Hexagonal | Hexagonal Boundaries | PASS | TransportPort unchanged |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged |
| AS:Domain | Domain Logic Isolation | PASS | No domain changes |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal change surface; no job tracking system |
| AS:Async | Async-First Design | PASS | Uses asyncio.create_task, asyncio.wait_for |

**Gate result:** PASS -- no violations.
