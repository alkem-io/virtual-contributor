# Health Endpoint Contracts

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30

## Endpoints

### GET /healthz (Liveness Probe)

**Purpose**: Indicates the process is running and not deadlocked. Used by Kubernetes liveness probe.

**Response**:
- `200 OK` — Process is alive
- No response (connection refused) — Process is dead, Kubernetes restarts the container

```json
{
  "status": "ok"
}
```

**Checks**:
- Process is running (implicit — if it responds, it's alive)
- Event loop is not blocked (response within probe timeout)

**Kubernetes configuration**:
```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 3
```

### GET /readyz (Readiness Probe)

**Purpose**: Indicates the service is ready to process messages. Used by Kubernetes readiness probe.

**Response**:
- `200 OK` — Service is ready
- `503 Service Unavailable` — Service is not ready (starting up, RabbitMQ disconnected, plugin startup incomplete)

```json
{
  "status": "ready",
  "checks": {
    "rabbitmq": "connected",
    "plugin": "started"
  }
}
```

Error response:
```json
{
  "status": "not_ready",
  "checks": {
    "rabbitmq": "disconnected",
    "plugin": "starting"
  }
}
```

**Checks**:
1. RabbitMQ connection is established and active
2. Plugin `startup()` has completed successfully

**Kubernetes configuration**:
```yaml
readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

## Implementation Notes

- Health server runs on port `8080` (configurable via `HEALTH_PORT` env var)
- Uses lightweight `asyncio` HTTP handler (not a full web framework)
- Shares the same event loop as the RabbitMQ consumer
- Minimal resource footprint — no middleware, no routing framework
- Responses are JSON with `Content-Type: application/json`
