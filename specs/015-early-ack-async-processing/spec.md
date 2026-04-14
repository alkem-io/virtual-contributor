# Feature Specification: Early ACK with Async Processing

**Feature Branch**: `story/1824-early-ack-async-processing`
**Created**: 2026-04-14
**Status**: In Progress
**Input**: Story alkemio#1824 (alkem-io/alkemio#1820) — "Decouple message acknowledgment from pipeline completion"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Early ACK for Ingest Messages (Priority: P1)

As a platform operator, I want ingest messages to be acknowledged immediately after schema validation so that RabbitMQ's `consumer_timeout` never triggers redelivery regardless of how long the pipeline takes. A single ingest trigger previously caused 30 redeliveries, 4,299 LLM API calls, and 15 hours of wasted compute.

**Why this priority**: This is the root cause of the infinite redelivery loop. Without early ACK, any ingest pipeline exceeding `consumer_timeout` (default 30 minutes) triggers cascading redelivery. This is the highest-value fix.

**Independent Test**: Configure `PIPELINE_TIMEOUT=60`, trigger an ingest that takes 45 seconds, and verify: (1) the message is ACKed within milliseconds, (2) the pipeline completes successfully, (3) no redelivery occurs.

**Acceptance Scenarios**:

1. **Given** an `IngestWebsite` message arrives, **When** the message passes Pydantic schema validation via `Router.parse_event()`, **Then** the message is ACKed before `plugin.handle()` begins.
2. **Given** an `IngestBodyOfKnowledge` message arrives, **When** the message passes schema validation, **Then** the message is ACKed before processing begins.
3. **Given** an ingest message is ACKed early, **When** `plugin.handle()` completes successfully, **Then** a result envelope is published to the result queue.
4. **Given** an ingest message is ACKed early, **When** `plugin.handle()` raises an exception, **Then** an error envelope is published to the result queue with error details.
5. **Given** an ingest message is ACKed early, **When** `plugin.handle()` exceeds the pipeline timeout, **Then** an error envelope is published with a timeout error.
6. **Given** an `Input` (engine query) message arrives, **When** processing completes, **Then** the message is ACKed only after `plugin.handle()` finishes (late ACK -- existing behavior preserved).

---

### User Story 2 - Outer Pipeline Timeout (Priority: P2)

As a platform operator, I want all `plugin.handle()` calls wrapped with a configurable timeout so that runaway pipelines cannot hold resources indefinitely, regardless of event type.

**Why this priority**: Independent of early ACK, a runaway pipeline can consume resources forever. The timeout is a safety net for both ingest and query events. The issue body explicitly requires this as a separate concern.

**Independent Test**: Set `PIPELINE_TIMEOUT=5`, trigger a pipeline that takes 10 seconds, and verify that a `TimeoutError` is raised and an error result is published after 5 seconds.

**Acceptance Scenarios**:

1. **Given** `PIPELINE_TIMEOUT=3600` (default), **When** `plugin.handle()` runs, **Then** it is wrapped with `asyncio.wait_for(timeout=3600)`.
2. **Given** `PIPELINE_TIMEOUT=60`, **When** `plugin.handle()` exceeds 60 seconds, **Then** the call is cancelled and an error result is published.
3. **Given** `PIPELINE_TIMEOUT=0`, **When** the application starts, **Then** startup fails with a validation error.
4. **Given** `PIPELINE_TIMEOUT=-1`, **When** the application starts, **Then** startup fails with a validation error.
5. **Given** the pipeline timeout applies universally, **When** an engine query exceeds the timeout, **Then** the query is cancelled and an error response is returned.

---

### User Story 3 - Graceful Shutdown of In-Flight Tasks (Priority: P3)

As a platform operator, I want the system to wait for in-flight pipeline tasks during shutdown so that SIGTERM does not kill pipelines mid-execution, preventing data corruption and partial ingests.

**Why this priority**: Without task tracking, SIGTERM during pipeline execution kills the process mid-pipeline. This is a reliability concern for production deployments but less critical than fixing the redelivery loop.

**Independent Test**: Start an ingest pipeline that takes 10 seconds, send SIGTERM after 2 seconds, and verify the pipeline completes before the process exits (within a 30-second grace period).

**Acceptance Scenarios**:

1. **Given** in-flight pipeline tasks exist, **When** SIGTERM is received, **Then** the system waits for tasks to complete within a grace period.
2. **Given** a task exceeds the shutdown grace period, **When** the grace period expires, **Then** remaining tasks are cancelled and the process exits.
3. **Given** no in-flight tasks exist, **When** SIGTERM is received, **Then** the process exits immediately.

---

### Edge Cases

- When an ingest message fails Pydantic schema validation, the message is NOT early-ACKed (no ACK before validation).
- When the RabbitMQ connection drops after early ACK but before the pipeline task starts, the task still runs (message already ACKed; idempotent via content-hash dedup).
- When multiple ingest tasks are in flight during shutdown, all are awaited concurrently.
- When an engine query fails after late ACK, retry/reject behavior replicates the existing `RabbitMQAdapter.consume()` retry logic (republish with `x-retry-count` header, reject after max retries).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ACK ingest messages (`IngestWebsite`, `IngestBodyOfKnowledge`) immediately after successful Pydantic schema validation, before `plugin.handle()` begins.
- **FR-002**: System MUST retain late-ACK behavior for engine query messages (`Input` events) -- ACK only after `plugin.handle()` completes.
- **FR-003**: System MUST wrap all `plugin.handle()` calls with `asyncio.wait_for()` using the configurable `PIPELINE_TIMEOUT` setting.
- **FR-004**: System MUST publish a result envelope to the result queue on pipeline success.
- **FR-005**: System MUST publish an error envelope to the result queue on pipeline failure (exception or timeout).
- **FR-006**: System MUST validate `PIPELINE_TIMEOUT` at startup: must be > 0.
- **FR-007**: System MUST provide a `PIPELINE_TIMEOUT` setting with a default of 3600 seconds.
- **FR-008**: System MUST track in-flight pipeline tasks and await them during graceful shutdown.
- **FR-009**: System MUST cancel remaining tasks after a shutdown grace period.
- **FR-010**: System MUST log `PIPELINE_TIMEOUT` at startup.
- **FR-011**: Engine queries that fail MUST replicate the existing retry/reject behavior (republish with `x-retry-count`, reject after max retries).

### Key Entities

- **Pipeline Timeout**: A configurable duration (seconds) that limits how long any `plugin.handle()` call can run. Default: 3600s. Must be > 0.
- **Active Task Set**: A runtime set tracking in-flight asyncio tasks for graceful shutdown coordination.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Ingest messages are ACKed within milliseconds of arrival (before pipeline execution), eliminating `consumer_timeout` redelivery loops entirely.
- **SC-002**: Pipeline processing exceeding the configured timeout is cancelled with an error result, preventing indefinite resource consumption.
- **SC-003**: Engine query behavior is unchanged -- late ACK, retry/reject logic, and error handling remain identical to pre-change behavior.
- **SC-004**: Graceful shutdown waits for in-flight tasks, preventing mid-pipeline process termination.

## Assumptions

- The existing content-hash deduplication (SHA-256 on chunks) makes re-triggered ingest pipelines idempotent, so early ACK losing a message on crash is safe.
- The `TransportPort` protocol interface is NOT changed; the new `consume_with_message()` method is on the concrete `RabbitMQAdapter` only.
- The `PluginContract` protocol is NOT changed.
- The RabbitMQ server-side `consumer_timeout` can be restored to default (30 minutes) after deployment, since ingest messages will be ACKed within milliseconds.
- Non-ingest plugins (expert, generic, guidance, openai_assistant) are unaffected -- they receive `Input` events and retain late-ACK behavior.
