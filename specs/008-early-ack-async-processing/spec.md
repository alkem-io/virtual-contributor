# Spec: Early ACK with Async Processing

**Story:** alkem-io/alkemio#1824
**Epic:** alkem-io/alkemio#1820
**Spec ID:** 008
**Status:** Active
**Date:** 2026-04-08

## User Value

Ingest pipelines for content-heavy sites (20+ pages, many chunks each) currently exceed RabbitMQ's `consumer_timeout` (default 30 min), causing infinite redelivery loops. This wastes thousands of LLM API calls and prevents ingestion from ever completing. By decoupling message acknowledgment from pipeline completion, the system eliminates redelivery loops entirely, ensuring any corpus can be ingested regardless of size or processing time.

## Scope

1. **Early ACK** -- Move message acknowledgment to immediately after successful message validation (JSON parse + schema validation), before pipeline execution begins. Applies to all plugin types.
2. **Async pipeline dispatch** -- After ACK, run `plugin.handle()` as an asyncio background task so the consumer callback returns promptly.
3. **Outer pipeline timeout** -- Wrap the entire `plugin.handle()` call in `asyncio.wait_for()` with a configurable timeout (`PIPELINE_TIMEOUT`, default 7200s / 2 hours). This prevents any single message from running indefinitely.
4. **Result reporting on completion/failure** -- Publish a result envelope to the result queue on both success and failure, including error details when applicable.
5. **Configuration** -- Add `PIPELINE_TIMEOUT` config field with validation.

## Out of Scope

- Distributed job tracking (Celery, Redis job store)
- Partial pipeline resume from last successful step
- Dead letter queue (DLX) configuration
- RabbitMQ `consumer_timeout` per-queue tuning
- Changes to the ingest pipeline steps themselves
- Retry at the message level (step-level retries already exist)

## Acceptance Criteria

1. After receiving a valid message, the RabbitMQ consumer ACKs within milliseconds -- before `plugin.handle()` starts.
2. Invalid messages (JSON parse failure) are rejected/nacked (requeue=False) without running the pipeline. Schema validation failures occur after ACK and are reported as error results.
3. Pipeline execution runs asynchronously after ACK.
4. An outer `asyncio.wait_for()` timeout wraps the pipeline call; exceeding it logs an error and publishes a timeout error result.
5. `PIPELINE_TIMEOUT` is configurable via environment variable (default: 7200 seconds).
6. On success, the result envelope is published to the result queue (existing behavior preserved).
7. On failure (exception or timeout), an error result envelope is published to the result queue with error details.
8. Graceful shutdown waits for in-flight pipeline tasks before exiting.
9. All existing tests pass without modification (backward compatible).
10. New unit tests cover: early ACK path, timeout behavior, error result publishing, invalid message rejection.

## Constraints

- Must not change the wire format of published result messages (backward compatible with platform consumers).
- Must preserve the existing retry logic for transient LLM/DB failures at the step level.
- Must work with aio-pika's robust connection model.
- Python 3.12, async-first architecture.
- The RabbitMQ adapter is the only transport; no abstraction leakage into plugins.

## Clarifications

Resolved during /speckit.clarify -- 3 iterations, 10 questions, 0 remaining.

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Should early ACK apply to all plugin types or only ingest? | All plugin types | Uniform behavior simplifies code and prevents future timeout issues for any plugin |
| 2 | Where should early ACK + async dispatch live? | `RabbitMQAdapter.consume()` | Adapter owns message lifecycle; hexagonal architecture keeps transport concerns in the adapter |
| 3 | What constitutes "valid message" for ACK? | JSON-parseable body | JSON parsing is the minimum transport-level gate; schema failures are app-level errors reported via result queue |
| 4 | Should invalid JSON be ACK'd or NACK'd? | NACK with requeue=False | Non-JSON messages will never become valid; reject permanently to prevent poison message cycling |
| 5 | How to track background tasks for graceful shutdown? | `set[asyncio.Task]` with done callbacks | Standard asyncio pattern, Python 3.12 compatible |
| 6 | Default pipeline timeout value? | 7200s (2 hours) | Matches current workaround; provides headroom for large corpora |
| 7 | Preserve `rabbitmq_max_retries` retry loop alongside early ACK? | Remove retry loop from adapter `on_message` | With early ACK the message is gone; retrying a consumed message is meaningless. Step-level retries remain. Config field kept for backward compat. |
| 8 | Should `on_message` callback signature change? | No change | Callback remains `async def(body: dict) -> None`; adapter handles ACK and task spawning transparently |
| 9 | Who publishes to result queue -- callback or adapter? | Callback (main.on_message) | Callback already has response-building logic; moving it would violate separation of concerns |
| 10 | Should adapter's `consume` method signature change? | Add optional `pipeline_timeout: float | None` parameter | Minimal API change to enable new behavior |
