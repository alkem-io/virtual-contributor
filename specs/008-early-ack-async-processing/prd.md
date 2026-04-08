# PRD: Early ACK with Async Processing

**Spec ID:** 008
**Status:** Draft
**Date:** 2026-04-08
**Author:** Valentin Yanakiev

## Problem Statement

The ingest pipeline ACKs RabbitMQ messages only after the entire pipeline completes (crawl → chunk → summarize → embed → upsert → BoK summary). For content-heavy sites with large documents (e.g., blog posts with 20+ chunks), the pipeline can exceed RabbitMQ's `consumer_timeout` (default 30 minutes), causing the message to be redelivered and the pipeline to restart from scratch — in an infinite loop.

### Observed Impact

During the initial deployment of the Qwen3-4B summarization model on 2026-04-07:
- A single ingest trigger for the Alkemio Guidance VC (20 documentation pages) resulted in **30 redeliveries** over 15 hours
- **4,299 LLM API calls** were made (vs ~150 expected for a single pass)
- The pipeline never completed because each 30-minute cycle was insufficient to summarize all documents
- The root cause was compounded by Qwen3's `<think>` blocks inflating context, but even after fixing that, blog-heavy sites with 20+ chunk documents approach the timeout boundary

### Current Workaround

`consumer_timeout` has been increased to 2 hours (7,200,000 ms). This is a band-aid — a sufficiently large corpus or slower model will hit the same wall.

## Proposed Solution

Decouple message acknowledgment from pipeline completion by adopting an **early ACK + async result** pattern.

### Current Flow (Late ACK)

```
1. Consumer receives message from queue
2. Runs full pipeline (crawl → chunk → summarize → embed → upsert → BoK summary)
3. ACKs message only on success
4. If timeout expires before ACK → message redelivered → restart from scratch
```

### Proposed Flow (Early ACK)

```
1. Consumer receives message from queue
2. Validates message schema and extracts parameters
3. ACKs immediately ("I received a valid message, don't redeliver")
4. Runs pipeline asynchronously
5. On completion: publishes result to result queue (success/failure)
6. On failure: publishes error result with details for monitoring/retry
```

## Requirements

### FR-001: Early Acknowledgment
The consumer MUST ACK the message after successful validation of the message schema, before starting pipeline execution. This prevents redelivery loops regardless of processing time.

### FR-002: Result Reporting
On pipeline completion (success or failure), the consumer MUST publish a result message to the configured result queue containing:
- Original message correlation ID
- Success/failure status
- Error details (on failure)
- Processing duration
- Document/chunk counts

### FR-003: Idempotent Processing
The pipeline MUST be idempotent — receiving the same ingest request twice should produce the same end state. This is already partially achieved via content-hash deduplication (spec 006) and `get_or_create_collection`, but must be validated end-to-end.

### FR-004: Failure Visibility
Pipeline failures after early ACK MUST be observable. Options:
- Error result message on the result queue
- Structured log entry at ERROR level with correlation ID
- Health endpoint status degradation

### FR-005: Graceful Shutdown
On SIGTERM/SIGINT during pipeline execution, the consumer SHOULD:
- Complete the current pipeline step (not mid-LLM-call)
- Publish a partial-completion result
- Exit cleanly

### FR-006: Retry Strategy
For transient failures (LLM timeout, ChromaDB unavailable), the pipeline SHOULD retry at the step level (already implemented via `_retry` in adapters). For permanent failures (invalid message, missing collection), the pipeline SHOULD report failure and NOT retry.

## Non-Requirements

- **Distributed job tracking** (e.g., Celery, Redis-based job store) — out of scope for this change. Structured logging + result queue is sufficient.
- **Partial resume** — restarting a failed pipeline from the last successful step is desirable but adds significant complexity. Defer to a future spec.
- **Dead letter queue** — RabbitMQ DLX configuration for poison messages. Useful but orthogonal to this change.

## Technical Notes

### RabbitMQ Consumer Timeout Background

- Introduced in RabbitMQ 3.8.15, default 30 min in 3.9+
- Timer starts per-message when delivered to consumer (not when enqueued)
- On expiry: channel closed, message requeued with `redelivered=true`
- Independent of TCP heartbeat (heartbeat detects network death, consumer_timeout detects stuck processing)
- Can be set per-queue via `x-consumer-timeout` argument (RabbitMQ 3.12+)

### Current ACK Location

In `core/adapters/rabbitmq.py`, the message ACK happens after `plugin.handle()` returns. The change would move the ACK to before `plugin.handle()` is called, after message deserialization succeeds.

### Risk: Lost Messages

With early ACK, if the process crashes mid-pipeline, the message is gone — RabbitMQ won't redeliver it. Mitigation:
- The result queue provides a completeness check (every trigger should produce a result)
- The server can re-trigger ingest if no result arrives within a timeout
- Idempotent processing means accidental re-triggers are safe

## Success Criteria

- Ingest pipeline completes regardless of document count or processing time
- No `consumer_timeout`-related redeliveries in production
- Pipeline failures are reported via result queue within 30 seconds of failure
- `consumer_timeout` can be restored to default (30 min) without impact
