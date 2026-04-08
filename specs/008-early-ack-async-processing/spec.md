# Spec: Early ACK with Async Processing

**Spec ID:** 008
**Story:** alkem-io/alkemio#1824
**Status:** Active
**Date:** 2026-04-08

## User Value

Ingest pipeline consumers currently ACK RabbitMQ messages only after the full pipeline completes. For content-heavy corpora, processing time exceeds RabbitMQ's `consumer_timeout`, causing infinite redelivery loops that waste LLM API calls, never complete, and block the queue. This change decouples acknowledgment from processing, eliminating timeout-triggered redeliveries and enabling arbitrarily large ingestion runs to complete reliably.

## Scope

1. **Early ACK in RabbitMQ consumer** -- ACK the message immediately after successful JSON deserialization and schema validation, before invoking `plugin.handle()`.
2. **Async fire-and-forget processing** -- After ACK, dispatch `plugin.handle()` as an asyncio task; the consumer callback returns immediately, freeing the RabbitMQ channel.
3. **Outer pipeline timeout** -- Wrap the entire `plugin.handle()` call in `asyncio.wait_for()` with a configurable timeout (`PIPELINE_TIMEOUT`, default 3600 seconds) to prevent runaway pipelines.
4. **Error reporting post-ACK** -- On pipeline failure (exception or timeout), publish an error result to the result queue so the server has visibility.
5. **Configuration** -- Add `PIPELINE_TIMEOUT` to `BaseConfig`.

## Out of Scope

- Distributed job tracking (Celery, Redis job store).
- Partial resume of failed pipelines from last successful step.
- Dead letter queue (DLX) configuration.
- Changes to the retry strategy inside individual adapters (LLM retries, ChromaDB retries).
- Changes to RabbitMQ server-side `consumer_timeout` configuration.

## Acceptance Criteria

1. After receiving a valid message, the RabbitMQ consumer ACKs the message before calling `plugin.handle()`.
2. An invalid message (JSON parse failure, schema validation failure) is rejected/NACKed without calling `plugin.handle()`.
3. Pipeline processing runs asynchronously after ACK; the consumer callback returns immediately.
4. A configurable outer timeout (`PIPELINE_TIMEOUT`, default 3600s) cancels runaway pipelines and publishes an error result.
5. On pipeline failure post-ACK, an error result is published to the result queue with error details.
6. Graceful shutdown waits for in-flight pipeline tasks before exiting.
7. All existing tests continue to pass.
8. New unit tests cover: early ACK path, timeout behavior, error reporting after ACK, graceful shutdown of in-flight tasks.

## Constraints

- Must not break existing message flow for query plugins (expert, generic, guidance, openai_assistant).
- Must preserve the existing retry semantics for malformed messages (retry with x-retry-count header).
- Must be backward-compatible: no new required env vars; all new config fields have sensible defaults.
- Must not introduce new runtime dependencies.
