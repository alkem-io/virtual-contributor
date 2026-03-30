# ADR 0004: Sequential Processing Model

## Status
Accepted

## Context
The existing production services process RabbitMQ messages sequentially with `prefetch=1`. LLM and embedding API calls are inherently latency-bound by upstream providers (100ms-30s per call). Concurrent message processing within a single plugin instance risks resource contention and complicates error handling.

## Decision
Maintain sequential processing per plugin instance:
- `prefetch_count=1` on the RabbitMQ channel
- One message processed at a time per container
- Manual ACK after successful processing (at-least-once delivery)
- Dead-letter queue for poison messages

Horizontal scaling is achieved via Kubernetes replica count — each replica runs one plugin instance consuming from the same queue.

## Consequences
- **Positive**: Simple error handling — one message context at a time.
- **Positive**: Predictable resource usage — no concurrent LLM calls competing for rate limits.
- **Positive**: Horizontal scaling via replicas is operationally straightforward.
- **Negative**: Single-instance throughput limited to one message at a time.
- **Mitigation**: Future enhancement can add per-plugin concurrency control without changing the architecture.
