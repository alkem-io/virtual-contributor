# Feature Specification: Early ACK with Async Processing

**Spec ID:** 008
**Story:** #1824 (alkem-io/alkemio#1820)
**Created:** 2026-04-14
**Status:** In Progress

## User Value

Platform operators suffer infinite redelivery loops when the ingest pipeline exceeds RabbitMQ's `consumer_timeout`. A single ingest trigger caused 30 redeliveries, 4,299 LLM API calls, and 15 hours of wasted compute. Decoupling message acknowledgment from pipeline completion eliminates this failure mode entirely.

## Scope

1. **Early ACK** -- Acknowledge RabbitMQ messages immediately after schema validation, before starting pipeline execution. This prevents `consumer_timeout`-triggered redelivery regardless of processing time.
2. **Async fire-and-forget processing** -- After early ACK, run `plugin.handle()` as an asyncio task. On completion (success or failure), publish a result to the result queue.
3. **Outer pipeline timeout** -- Wrap the entire `plugin.handle()` call with `asyncio.wait_for()` using a configurable `PIPELINE_TIMEOUT` setting. This prevents runaway pipelines from holding resources indefinitely.
4. **Configuration** -- New `pipeline_timeout` config field with a sensible default (3600 seconds = 1 hour).

## Out of Scope

- Distributed job tracking (Celery, Redis).
- Partial pipeline resume from last successful step.
- Dead letter queue (DLX) configuration.
- Changes to the RabbitMQ server-side `consumer_timeout` setting.
- Changes to plugin internals or the pipeline engine steps.

## Acceptance Criteria

- AC-1: Ingest messages are ACKed immediately after successful Pydantic schema validation (`Router.parse_event()`), before `plugin.handle()` begins.
- AC-2: Engine query messages (Input events) continue to use the existing late-ACK + error-reply pattern (only ingest events get early ACK).
- AC-3: Pipeline processing runs as a fire-and-forget asyncio task after early ACK.
- AC-4: Pipeline success publishes a result envelope to the result queue.
- AC-5: Pipeline failure (exception or timeout) publishes an error envelope to the result queue with error details.
- AC-6: An outer `asyncio.wait_for()` timeout wraps `plugin.handle()` with a configurable `PIPELINE_TIMEOUT` (default 3600s).
- AC-7: The `PIPELINE_TIMEOUT` setting is validated (must be > 0) at startup.
- AC-8: Engine queries that fail get retry/reject behavior equivalent to the existing `RabbitMQAdapter.consume()` retry logic (republish with x-retry-count header, reject after max retries). This logic is replicated in the application layer since `consume_with_message()` delegates ACK/reject to the callback.
- AC-9: Graceful shutdown waits for in-flight pipeline tasks to complete (with a shutdown grace period).

## Constraints

- Must not change the `TransportPort` protocol interface.
- Must not change the `PluginContract` protocol.
- Must remain backward-compatible for non-ingest plugins (expert, generic, guidance, openai_assistant).
- Early ACK applies only to ingest event types (`IngestWebsite`, `IngestBodyOfKnowledge`).
- The RabbitMQ adapter's existing retry/requeue mechanism must remain intact for engine queries.

## Clarifications (Iteration 1)

| # | Ambiguity | Chosen Answer | Rationale |
|---|-----------|---------------|-----------|
| C-1 | Where should the early-ACK / late-ACK branching happen -- in the RabbitMQ adapter or in `on_message`? | In `on_message` in `main.py`. The adapter will expose a new `consume_early_ack` method that passes the raw `message` object to the callback so it can decide when to ACK. | The Router already knows the event type. Keeping the decision in `on_message` avoids coupling the adapter to event-type knowledge. However, the adapter currently hides the aio-pika message from the callback. We need a way for the callback to receive the message handle for explicit ACK. The cleanest approach: the adapter's `on_message` will pass the raw message to the callback, and the callback decides when to ACK. |
| C-2 | Should the outer pipeline timeout apply only to ingest events or to all events? | All events. The timeout wraps `plugin.handle()` universally. | The issue body explicitly says "Independent of early ACK, main.py on_message needs an outer asyncio.wait_for timeout wrapping the entire plugin.handle() call." This is a separate concern from early ACK and applies to all plugin types. |
| C-3 | How should the `consume` method signature change to support early ACK without breaking `TransportPort`? | Add a separate `consume_early_ack` method to `RabbitMQAdapter` that is not part of `TransportPort`. Alternatively, modify the existing `consume` so the callback receives the raw message. | Decision: keep `TransportPort` unchanged. The `RabbitMQAdapter.consume()` method will change so its callback receives an `(aio_pika.AbstractIncomingMessage, dict)` tuple. Since `TransportPort` is only used for type annotations and the adapter is always constructed directly in `main.py`, this is safe. Actually, examining `main.py`, the transport is constructed as `RabbitMQAdapter` directly, not via `TransportPort`. So changing the concrete class is fine. |
| C-4 | Should the fire-and-forget task be tracked for graceful shutdown? | Yes. Store active tasks in a set and await them during shutdown. | Without task tracking, SIGTERM during pipeline execution would kill the process mid-pipeline. The issue explicitly requires graceful shutdown. |
| C-5 | What is the default pipeline timeout value? | 3600 seconds (1 hour). | The incident showed 30-minute timeouts were insufficient. The workaround set 2 hours. 1 hour provides a generous ceiling for legitimate pipelines while preventing runaway processing. Configurable via `PIPELINE_TIMEOUT`. |
| C-6 | Should the early ACK happen after JSON deserialization or after full Pydantic validation (Router.parse_event)? | After full Pydantic validation via `Router.parse_event()`. | If we ACK after JSON parse but the message fails Pydantic validation, we lose the message with no result published. Validating the event schema before ACK ensures we only ACK messages we can actually process. |
| C-7 | How does early ACK interact with the existing retry/requeue logic in `RabbitMQAdapter.consume()`? | For ingest events: early ACK means the adapter's retry logic is bypassed -- the message is ACKed before processing starts, so there is nothing to retry at the transport level. For engine queries: the existing retry/requeue continues unchanged. | The retry mechanism in the adapter catches exceptions from the callback and requeues. With early ACK for ingest, the callback ACKs first and then spawns an async task, so exceptions from the task never reach the adapter's retry logic. Engine queries continue with late ACK and the adapter retry loop. |
| C-8 | How should the callback communicate whether to early-ACK? | The `on_message` callback in `main.py` will determine this based on the parsed event type (ingest vs engine query). The adapter will pass the raw message to the callback, and the callback will call `message.ack()` at the right time. | This keeps event-type awareness in the application layer, not the transport adapter. |

## Clarifications (Iteration 2)

No new ambiguities found. All design decisions from iteration 1 are internally consistent and aligned with the codebase structure. Clarify loop complete.
