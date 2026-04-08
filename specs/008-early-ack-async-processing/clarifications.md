# Clarifications -- Story #1824

## Iteration 1

### C-001: Should early ACK apply to all plugin types or only ingest plugins?

**Question:** The redelivery problem only manifests for ingest plugins (long-running pipelines). Should query plugins (expert, generic, guidance, openai_assistant) also use early ACK?

**Decision:** Yes, apply early ACK uniformly to all plugin types. The ACK-then-process pattern is correct for all message types: once a valid message is received, redelivery provides no value because the consumer has already committed to processing it. Applying it uniformly keeps the consumer callback simple and consistent.

**Rationale:** Query plugins already publish error results on failure, so the early ACK risk (lost messages on crash) has the same mitigation. A per-plugin-type branching strategy would add complexity with no benefit.

### C-002: Where should the early ACK happen -- in RabbitMQAdapter.consume() or in main.on_message()?

**Question:** The RabbitMQ adapter currently owns the ACK/NACK logic inside its `on_message` closure. Should the early ACK be implemented inside the adapter (making it transparent to main.py) or should main.py control the ACK timing?

**Decision:** Implement early ACK inside `RabbitMQAdapter.consume()`. The adapter's `on_message` closure will: (1) parse JSON, (2) ACK immediately, (3) call the callback. The callback signature remains `async def callback(body: dict) -> None`.

**Rationale:** This keeps the transport concern (ACK timing) inside the transport adapter where it belongs, per the hexagonal architecture. main.py should not know about ACK semantics.

### C-003: Should the async dispatch use asyncio.create_task or run in the on_message coroutine?

**Question:** After ACK, should the pipeline run inline (blocking the consumer coroutine) or be dispatched as a separate asyncio task?

**Decision:** Dispatch as `asyncio.create_task()`. The consumer callback returns immediately after ACK, and the pipeline runs as a background task. This prevents long-running pipelines from blocking heartbeat processing and other message handling.

**Rationale:** Running inline would still block the aio-pika consumer coroutine, which could delay heartbeat responses and cause connection-level timeouts, partially defeating the purpose.

### C-004: How should the outer timeout value be configured?

**Question:** The PRD mentions an outer timeout but does not specify a default or config field name.

**Decision:** Add `pipeline_timeout: int = 3600` to `BaseConfig` (env var: `PIPELINE_TIMEOUT`). Default is 3600 seconds (1 hour). The timeout wraps the entire `plugin.handle()` call via `asyncio.wait_for()`.

**Rationale:** 1 hour is generous for any ingest pipeline while still catching truly runaway processes. The current `consumer_timeout` workaround is 2 hours; this gives a safety net well within that.

### C-005: What should happen to in-flight tasks during graceful shutdown?

**Question:** If SIGTERM arrives while a pipeline task is running, should we cancel it immediately or wait for completion?

**Decision:** Wait for in-flight tasks with a bounded grace period. On shutdown signal, set the stop event, then await all in-flight tasks with `asyncio.wait()` using a timeout (30 seconds). After the grace period, cancel remaining tasks.

**Rationale:** This aligns with FR-005 in the PRD. A bounded wait prevents indefinite shutdown delays while giving in-progress work a chance to finish cleanly.

### C-006: Should the retry-with-header logic in RabbitMQAdapter be preserved for schema validation failures?

**Question:** Currently, any exception in the callback triggers the retry-with-x-retry-count-header logic. With early ACK, the message is already ACKed before the callback runs. What happens to retry logic?

**Decision:** Split error handling into two phases: (1) Pre-ACK: JSON parse failures trigger reject/retry using the existing header-based retry logic. (2) Post-ACK: Schema validation and processing errors are handled by publishing an error result to the result queue; no retry via RabbitMQ since the message is already ACKed.

**Rationale:** JSON parse failures indicate a malformed message that may be transient (truncation). Schema validation failures after successful JSON parse indicate a permanently invalid message that retry won't fix. Processing failures are handled by the result queue for server-side visibility.

### C-007: Should the callback receive the raw message to control ACK, or should the adapter handle everything?

**Question:** An alternative design passes the raw `aio_pika.IncomingMessage` to the callback, letting main.py decide when to ACK.

**Decision:** Keep the adapter in control. The adapter ACKs after JSON parse, then calls the callback with the parsed dict. The callback does not see or control the raw message. This is the current contract and preserving it minimizes changes.

**Rationale:** Exposing transport-layer details to the callback violates port/adapter boundaries.
