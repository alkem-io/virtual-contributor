# ADR 0012: OpenTelemetry pipeline tracing

## Status: Accepted

## Context

Story #28 needs correlated query and ingest visibility without sending prompts,
answers, or retrieved material outside Alkemio infrastructure. The candidate
approaches were vendor SDKs (Langfuse), log-only metrics, and OpenTelemetry.

## Decision

Use OpenTelemetry traces with OTLP/HTTP. Tracing is disabled by default and a
module-local `TracerProvider` is created only when both `TRACING_ENABLED` and
an explicit `TRACING_OTLP_ENDPOINT` are supplied. The provider is never made
global. Endpoint, headers, resource, and sampler are passed as constructor
arguments, not discovered from `OTEL_*` variables. LangChain instrumentation
uses a callback attached at model construction, covering adapter and
PromptGraph invocation paths.

## Consequences

- No configured endpoint means no exporter, no connection attempt, and no SDK
  work on query paths.
- The exporter is batched and shutdown force-flushes it within the existing
  grace period.
- Content attributes are independently configurable and bounded; numeric
  signals remain available when content capture is disabled.
- Self-hosted Langfuse (via OTLP), Grafana Tempo, and Elastic APM can consume
  the same wire format. Backend operation and dashboards remain infrastructure
  concerns rather than application dependencies.
- A retrieval decorator merges its attributes into an already-open
  `vc.retrieval` span, so a plugin's post-filter signals and the store's raw
  result signals remain on exactly one span. Guidance's cross-collection
  filtering is attributed to the root span because it has no single collection
  owner.
- A timed-out synchronous LLM call can finish in its worker thread after its
  root span closes. Dashboards should exclude those late child spans from
  root-duration rollups.
- Retrieval score statistics use `1 - distance` and are meaningful as bounded
  similarity only for cosine distance; l2 and inner-product deployments must
  interpret them according to their configured distance function.
