# Research: Early ACK with Async Processing

**Feature Branch**: `story/1824-early-ack-async-processing`
**Date**: 2026-04-14

## Research Tasks

### R1: Where should the early-ACK / late-ACK branching happen?

**Context**: The `RabbitMQAdapter.consume()` method currently wraps the entire callback in a try/except that handles ACK/reject. We need the callback (`on_message` in `main.py`) to control ACK timing based on event type.

**Findings**:

The adapter currently hides the `aio_pika.AbstractIncomingMessage` from the callback -- it only passes the parsed JSON body. For the application layer to control ACK timing, it needs access to the raw message handle.

Two approaches evaluated:
1. Modify `consume()` signature to pass the raw message -- breaks existing callback contract.
2. Add a new `consume_with_message()` method that passes both the parsed body and the raw message, delegating all ACK/reject responsibility to the callback.

Approach 2 is cleaner: `TransportPort` stays unchanged, `consume()` is untouched, and the new method is on the concrete `RabbitMQAdapter` only. Since `main.py` constructs the adapter directly (not via `TransportPort`), calling a concrete method is safe.

**Decision**: Add `consume_with_message()` to `RabbitMQAdapter`. The callback receives `(body: dict, message: AbstractIncomingMessage)` and handles all ACK/reject.
**Rationale**: Keeps `TransportPort` stable. Keeps event-type awareness in the application layer, not the transport adapter.
**Alternatives considered**: (a) Modify `consume()` signature -- rejected (breaks TransportPort contract). (b) Pass ACK/reject callbacks instead of raw message -- rejected (adds indirection without benefit; the message object already has `.ack()` and `.reject()`).

---

### R2: Should early ACK happen after JSON parse or after Pydantic validation?

**Context**: There is a choice between ACKing after basic JSON deserialization or after full Pydantic schema validation via `Router.parse_event()`.

**Findings**:

If we ACK after JSON parse but the message fails Pydantic validation, we lose the message with no result published (it is already ACKed, so no redelivery, but no error notification either). ACKing after Pydantic validation ensures we only ACK messages we can actually process.

The time between JSON parse and Pydantic validation is negligible (microseconds), so there is no timeout risk from waiting.

**Decision**: ACK after full Pydantic validation via `Router.parse_event()`.
**Rationale**: Prevents silent message loss for malformed events. The validation time is negligible relative to `consumer_timeout`.
**Alternatives considered**: ACK after JSON parse -- rejected (risks silent message loss on schema validation failure).

---

### R3: How should fire-and-forget tasks be tracked for graceful shutdown?

**Context**: After early ACK, the ingest pipeline runs as an asyncio task. Without tracking, SIGTERM kills in-flight tasks.

**Findings**:

Python's `asyncio.create_task()` returns a `Task` object. Tasks can be stored in a `set()` and removed via `task.add_done_callback()`. During shutdown, `asyncio.gather(*active_tasks)` with a timeout provides a grace period.

The approach is standard Python asyncio practice and requires no external dependencies.

**Decision**: Store tasks in a module-level `set()`. Add a done callback to remove completed tasks. On shutdown, `asyncio.wait(active_tasks, timeout=30)` then cancel remaining.
**Rationale**: Minimal implementation. No external dependencies. Standard asyncio pattern.
**Alternatives considered**: (a) No task tracking, just `asyncio.all_tasks()` -- rejected (catches unrelated tasks). (b) External job tracker (Celery/Redis) -- rejected (massive over-engineering for this use case).

---

### R4: Should the outer timeout apply to all events or only ingest?

**Context**: The issue body says "Independent of early ACK, `main.py` `on_message` needs an outer `asyncio.wait_for` timeout wrapping the entire `plugin.handle()` call."

**Findings**:

The timeout is a separate safety concern from early ACK. A runaway engine query plugin could hold resources indefinitely. Applying the timeout universally is both safer and simpler (one code path).

**Decision**: Apply `asyncio.wait_for(timeout=pipeline_timeout)` to all `plugin.handle()` calls, regardless of event type.
**Rationale**: Explicitly required by the issue. Simpler implementation (no branching on event type for timeout). Safer (catches runaway queries too).
**Alternatives considered**: Timeout only for ingest -- rejected (leaves query plugins unbounded; contradicts issue requirements).

---

### R5: How should engine query retry/reject work with consume_with_message?

**Context**: The existing `consume()` method handles retry/reject internally. With `consume_with_message()`, the callback must handle this itself.

**Findings**:

The existing retry logic in `RabbitMQAdapter.consume()`: on exception, if `x-retry-count < max_retries`, republish with incremented header; otherwise, reject. This logic must be replicated in the `on_message` callback for engine queries.

For ingest events, retry is not needed: the message is already ACKed, so there is nothing to retry at the transport level. Pipeline failures are reported via error envelopes.

**Decision**: Replicate retry logic in `on_message` for engine queries only. Ingest events use fire-and-forget with error envelope publication.
**Rationale**: Engine queries need the same reliability guarantees. Ingest events are idempotent via content-hash dedup, so error reporting (not retry) is the correct strategy.
**Alternatives considered**: No retry for queries either -- rejected (would degrade reliability for user-facing queries).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| ACK/reject control | `consume_with_message()` on concrete adapter | TransportPort unchanged |
| ACK timing | After Pydantic validation | Prevents silent message loss |
| Task tracking | Module-level set + done callbacks | Standard asyncio, no deps |
| Timeout scope | All events (universal) | Issue requirement; simpler; safer |
| Engine query retry | Replicate in on_message callback | Preserve existing reliability |
| Default timeout | 3600 seconds (1 hour) | Generous ceiling; configurable |
