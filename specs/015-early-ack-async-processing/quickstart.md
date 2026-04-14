# Quickstart: Early ACK with Async Processing

**Feature Branch**: `story/1824-early-ack-async-processing`
**Date**: 2026-04-14

## What This Feature Does

Decouples RabbitMQ message acknowledgment from pipeline completion for ingest events, eliminating infinite redelivery loops caused by `consumer_timeout` expiry. Adds three improvements:

1. **Early ACK for ingest messages** -- ACK immediately after schema validation, before pipeline execution
2. **Outer pipeline timeout** -- configurable timeout wrapping all `plugin.handle()` calls
3. **Graceful shutdown** -- await in-flight tasks during SIGTERM

All changes are backward compatible: engine queries retain late-ACK behavior, and the default timeout (1 hour) accommodates all existing workloads.

## New Environment Variables

### Pipeline Timeout

```env
# Maximum duration (seconds) for any plugin.handle() call.
# Default: 3600 (1 hour). Must be > 0.
PIPELINE_TIMEOUT=3600
```

## Quick Verification

### 1. Early ACK for ingest

```bash
export PLUGIN_TYPE=ingest-website
export PIPELINE_TIMEOUT=3600
poetry run python main.py

# Trigger an ingest via RabbitMQ. Check logs for:
#   INFO: Early ACK for ingest event: IngestWebsite
#   INFO: Pipeline task created for event: IngestWebsite
#   INFO: Pipeline completed successfully
#
# The message is ACKed within milliseconds. No redelivery occurs
# even if the pipeline takes 30+ minutes.
```

### 2. Pipeline timeout

```bash
export PIPELINE_TIMEOUT=60  # 1 minute timeout

# Trigger a pipeline that exceeds 60 seconds. Check logs for:
#   ERROR: Pipeline timed out after 60s
#   INFO: Error result published to result queue
```

### 3. Engine query (unchanged behavior)

```bash
export PLUGIN_TYPE=expert
export PIPELINE_TIMEOUT=3600
poetry run python main.py

# Engine queries still use late ACK. The message is ACKed
# only after plugin.handle() completes successfully.
```

### 4. Config validation

```bash
export PIPELINE_TIMEOUT=0
poetry run python main.py
# Startup fails with: ValueError: pipeline_timeout must be > 0

export PIPELINE_TIMEOUT=-1
poetry run python main.py
# Startup fails with: ValueError: pipeline_timeout must be > 0
```

### 5. Graceful shutdown

```bash
export PLUGIN_TYPE=ingest-website
poetry run python main.py

# Trigger an ingest, then send SIGTERM during processing:
#   kill -TERM <pid>
#
# Check logs for:
#   INFO: Graceful shutdown: waiting for N in-flight tasks (30s grace period)
#   INFO: All in-flight tasks completed
```

## Files Changed

| File | Change |
|------|--------|
| `core/config.py` | Add `pipeline_timeout: int = 3600` with > 0 validation |
| `core/adapters/rabbitmq.py` | Add `consume_with_message()` method |
| `main.py` | Rewrite `on_message`: early ACK for ingest, outer timeout, task management, graceful shutdown |
| `tests/core/test_early_ack.py` | Unit tests for early ACK, timeout, task tracking |
| `tests/test_config_pipeline_timeout.py` | Config validation tests |

## Contracts

No external interface changes:
- **TransportPort**: Unchanged (`consume_with_message` is on concrete adapter only)
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
