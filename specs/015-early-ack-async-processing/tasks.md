# Tasks: Early ACK with Async Processing

**Input**: Design documents from `specs/015-early-ack-async-processing/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Config Fields)

**Purpose**: All new config fields that MUST be in place before user story work begins.

- [X] T001 Add `pipeline_timeout: int = 3600` field to `BaseConfig` in `core/config.py`. Add validation in `_resolve_backward_compat_and_validate()`: must be > 0.
  - **AC**: `PIPELINE_TIMEOUT=3600` env var parsed. `PIPELINE_TIMEOUT=0` raises `ValueError`. `PIPELINE_TIMEOUT=-1` raises `ValueError`.
  - **Test**: `tests/test_config_pipeline_timeout.py` -- validate default, valid override, and invalid values.

**Checkpoint**: Config field in place, validated at startup.

---

## Phase 2: User Story 1 - Early ACK for Ingest Messages (Priority: P1) MVP

**Goal**: Ingest messages are ACKed immediately after schema validation, before pipeline execution.

**Independent Test**: Trigger an ingest message and verify ACK occurs before `plugin.handle()` begins. Verify result is published on success and error envelope on failure.

### Implementation for User Story 1

- [X] T002 [US1] Add `consume_with_message()` method to `RabbitMQAdapter` in `core/adapters/rabbitmq.py`. This method declares the queue, binds to the exchange, and calls the callback with `(body: dict, message: AbstractIncomingMessage)`. It does NOT ACK or reject -- the callback is responsible for message lifecycle.
  - **AC**: Method is callable. Queue is declared and bound. Callback receives both parsed JSON body and raw message. No automatic ACK/reject.
  - **Test**: `tests/core/test_early_ack.py::test_consume_with_message_delegates_to_callback`

- [X] T003 [US1] Rewrite `on_message` in `main.py` to use `transport.consume_with_message()`. The new callback receives `(body, message)`. For ingest events (`IngestWebsite`, `IngestBodyOfKnowledge`): (a) `message.ack()` immediately after `Router.parse_event()`, (b) create asyncio task for `_run_pipeline(event)`, (c) store task in `_active_tasks` set. For engine queries (`Input`): (a) run `plugin.handle(event)` with timeout, (b) publish result, (c) `message.ack()` after processing, (d) on exception: publish error, apply retry logic.
  - **AC**: Ingest messages ACKed before handle(). Engine queries ACKed after handle(). Timeout wraps all handle() calls.
  - **Tests**: `tests/core/test_early_ack.py::test_ingest_early_ack`, `test_engine_query_late_ack`

- [X] T004 [US1] Implement `_run_pipeline(event)` async helper in `main.py`. Wraps `plugin.handle(event)` with `asyncio.wait_for(timeout=pipeline_timeout)`. On success: publishes result envelope. On `asyncio.TimeoutError`: logs error, publishes error envelope. On exception: logs error, publishes error envelope. Removes self from `_active_tasks` on completion via `task.add_done_callback`.
  - **AC**: Success publishes result. Timeout publishes error. Exception publishes error. Task removed from tracking set.
  - **Tests**: `tests/core/test_early_ack.py::test_pipeline_success_publishes_result`, `test_pipeline_timeout_publishes_error`, `test_pipeline_exception_publishes_error`

**Checkpoint**: Ingest messages receive early ACK. Engine queries retain late ACK. Fire-and-forget task management in place.

---

## Phase 3: User Story 2 - Outer Pipeline Timeout (Priority: P2)

**Goal**: Configurable timeout wraps all `plugin.handle()` calls, preventing runaway pipelines.

**Independent Test**: Set `PIPELINE_TIMEOUT=5`, trigger a pipeline taking 10 seconds, verify timeout error published after 5 seconds.

### Implementation for User Story 2

- [X] T005 [US2] Verify pipeline timeout is applied in both ingest and query paths in `main.py`. The `asyncio.wait_for(timeout=pipeline_timeout)` wrapping in `_run_pipeline()` (ingest) and `on_message` (queries) covers all event types.
  - **AC**: Timeout applies to ingest events (via `_run_pipeline`) and engine queries (via `on_message`). Exceeding timeout produces error result.
  - **Test**: `tests/core/test_early_ack.py::test_pipeline_timeout`

- [X] T006 [P] [US2] Add `pipeline_timeout` to `_log_config()` fields list in `main.py`.
  - **AC**: Pipeline timeout logged at startup.

**Checkpoint**: All `plugin.handle()` calls are time-bounded.

---

## Phase 4: User Story 3 - Graceful Shutdown (Priority: P3)

**Goal**: In-flight pipeline tasks are awaited during shutdown, preventing mid-pipeline termination.

**Independent Test**: Start a pipeline, send SIGTERM, verify pipeline completes within grace period.

### Implementation for User Story 3

- [X] T007 [US3] Update graceful shutdown in `main.py` to await in-flight tasks. After `stop_event.wait()`, gather all `_active_tasks` with a grace period of 30 seconds. Log count of in-flight tasks. Cancel remaining tasks after grace period.
  - **AC**: Shutdown waits for active tasks. Tasks completing within grace period are awaited. Tasks exceeding grace period are cancelled.
  - **Test**: `tests/core/test_early_ack.py::test_graceful_shutdown_awaits_tasks`

**Checkpoint**: Graceful shutdown protects in-flight pipelines.

---

## Phase 5: Tests

**Purpose**: Comprehensive test coverage for the new behavior.

- [X] T008 Write `tests/core/test_early_ack.py` with the following test cases: (1) `test_ingest_event_acked_before_processing`, (2) `test_engine_query_acked_after_processing`, (3) `test_pipeline_timeout_publishes_error`, (4) `test_pipeline_success_publishes_result`, (5) `test_pipeline_exception_publishes_error`, (6) `test_consume_with_message_delegates_to_callback`.
  - **AC**: All tests pass. Tests use mock ports from `tests/conftest.py`.

- [X] T009 [P] Write `tests/test_config_pipeline_timeout.py` with: (1) `test_pipeline_timeout_default`, (2) `test_pipeline_timeout_custom`, (3) `test_pipeline_timeout_invalid_zero`, (4) `test_pipeline_timeout_invalid_negative`.
  - **AC**: All tests pass.

**Checkpoint**: Full test coverage.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T010 [P] Verify `PIPELINE_TIMEOUT` appears in `_log_config()` fields list (covered by T006).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies -- start immediately
- **User Story 1 (Phase 2)**: Depends on Phase 1 (config field) -- BLOCKS other stories
- **User Story 2 (Phase 3)**: Depends on Phase 2 (timeout wrapping implemented there)
- **User Story 3 (Phase 4)**: Depends on Phase 2 (task tracking implemented there)
- **Tests (Phase 5)**: T008 depends on Phase 2-4. T009 depends on Phase 1 only.
- **Polish (Phase 6)**: Depends on Phase 2.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 1) -- No dependencies on other stories
- **User Story 2 (P2)**: Timeout wrapping is implemented as part of US1 code; US2 validates it applies universally
- **User Story 3 (P3)**: Task tracking is implemented as part of US1 code; US3 adds graceful shutdown

### Parallel Opportunities

**Phase 1**: T001 standalone.
**Phase 2**: T002 parallel with T001 (different file). T003, T004 sequential (both in main.py).
**Phase 5**: T008 and T009 parallel (different test files).
**Phase 6**: T010 parallel with Phase 5.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Config field
2. Complete Phase 2: Early ACK + timeout + task management
3. **STOP and VALIDATE**: Test early ACK independently
4. Deploy -- ingest redelivery loop eliminated

### Incremental Delivery

1. Phase 1 + Phase 2 -> Early ACK for ingest (MVP!)
2. Add Phase 3 -> Verify timeout applies universally
3. Add Phase 4 -> Graceful shutdown protection
4. Phase 5 + 6 -> Tests and polish
