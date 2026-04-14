# Tasks: Early ACK with Async Processing

**Input:** Design documents from `specs/008-early-ack-async-processing/`
**Prerequisites:** plan.md (required), spec.md (required)
**Organization:** Tasks grouped by phase with dependency tracking.

## Format: `[ID] [P?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

---

## Phase 1: Configuration

**Purpose:** Add the `pipeline_timeout` config field before any behavioral changes.

- [ ] T001 Add `pipeline_timeout: int = 3600` field to `BaseConfig` in `core/config.py`. Add validation in `_resolve_backward_compat_and_validate()`: must be > 0.
  - **AC:** `PIPELINE_TIMEOUT=3600` env var parsed. `PIPELINE_TIMEOUT=0` raises `ValueError`. `PIPELINE_TIMEOUT=-1` raises `ValueError`.
  - **Test:** `tests/test_config_pipeline_timeout.py` -- validate default, valid override, and invalid values.

**Checkpoint:** Config field in place, validated at startup.

---

## Phase 2: Transport Adapter

**Purpose:** Expose raw message to callback so application layer can control ACK timing.

- [ ] T002 Add `consume_with_message()` method to `RabbitMQAdapter` in `core/adapters/rabbitmq.py`. This method declares the queue, binds to the exchange, and calls the callback with `(body: dict, message: AbstractIncomingMessage)`. It does NOT ACK or reject -- the callback is responsible for message lifecycle.
  - **AC:** Method is callable. Queue is declared and bound. Callback receives both parsed JSON body and raw message. No automatic ACK/reject.
  - **Test:** `tests/core/test_early_ack.py::test_consume_with_message_passes_body_and_message`

**Checkpoint:** Adapter passes raw message to callback.

---

## Phase 3: Application Layer -- Early ACK + Timeout + Task Management

**Purpose:** Rewrite `on_message` in `main.py` to support early ACK for ingest events, outer timeout, and fire-and-forget task management.

- [ ] T003 Rewrite `on_message` in `main.py` to use `transport.consume_with_message()`. The new callback receives `(body, message)`. Logic:
  1. Parse event via `router.parse_event(body)`.
  2. If event is `IngestWebsite` or `IngestBodyOfKnowledge` (ingest event):
     a. `message.ack()` immediately (early ACK).
     b. Create asyncio task for `_run_pipeline(event)`.
     c. Store task in `_active_tasks` set for shutdown tracking.
  3. If event is `Input` (engine query):
     a. Run `plugin.handle(event)` with `asyncio.wait_for(timeout=pipeline_timeout)`.
     b. Publish result.
     c. `message.ack()` (late ACK).
     d. On exception: publish error result, apply retry logic (republish with incremented x-retry-count header, or reject after max retries). This replicates the retry logic from the adapter's old `on_message` closure since `consume_with_message()` delegates all ACK/reject to the callback.
  - **AC:** Ingest messages ACKed before handle(). Engine queries ACKed after handle(). Timeout wraps all handle() calls.
  - **Tests:** `tests/core/test_early_ack.py::test_ingest_early_ack`, `test_engine_query_late_ack`, `test_pipeline_timeout`

- [ ] T004 Implement `_run_pipeline(event)` async helper in `main.py`. This function:
  1. Wraps `plugin.handle(event)` with `asyncio.wait_for(timeout=pipeline_timeout)`.
  2. On success: publishes result envelope to result queue.
  3. On `asyncio.TimeoutError`: logs error, publishes error envelope.
  4. On exception: logs error, publishes error envelope.
  5. Removes self from `_active_tasks` on completion (via task.add_done_callback).
  - **AC:** Success publishes result. Timeout publishes error. Exception publishes error. Task removed from tracking set.
  - **Tests:** `tests/core/test_early_ack.py::test_pipeline_success_publishes_result`, `test_pipeline_timeout_publishes_error`, `test_pipeline_exception_publishes_error`

- [ ] T005 Update graceful shutdown in `main.py` to await in-flight tasks. After `stop_event.wait()`, gather all `_active_tasks` with a grace period of 30 seconds. Log count of in-flight tasks. Cancel remaining tasks after grace period.
  - **AC:** Shutdown waits for active tasks. Tasks that complete within grace period are awaited. Tasks exceeding grace period are cancelled.
  - **Test:** `tests/core/test_early_ack.py::test_graceful_shutdown_awaits_tasks`

- [ ] T006 [P] Add `pipeline_timeout` to `_log_config()` fields list in `main.py`.
  - **AC:** Pipeline timeout logged at startup.

**Checkpoint:** Full early ACK + timeout + graceful shutdown implemented.

---

## Phase 4: Tests

**Purpose:** Comprehensive test coverage for the new behavior.

- [ ] T007 Write `tests/core/test_early_ack.py` with the following test cases:
  1. `test_ingest_event_acked_before_processing` -- Verify ACK called before handle().
  2. `test_engine_query_acked_after_processing` -- Verify ACK called after handle().
  3. `test_pipeline_timeout_publishes_error` -- Verify timeout triggers error result.
  4. `test_pipeline_success_publishes_result` -- Verify success publishes result.
  5. `test_pipeline_exception_publishes_error` -- Verify exception publishes error.
  6. `test_consume_with_message_delegates_to_callback` -- Verify adapter passes body and message.
  - **AC:** All tests pass. Tests use mock ports from `tests/conftest.py`.
  - **Test:** Self-verifying.

- [ ] T008 [P] Write `tests/test_config_pipeline_timeout.py`:
  1. `test_pipeline_timeout_default` -- Verify default is 3600.
  2. `test_pipeline_timeout_custom` -- Verify custom value is accepted.
  3. `test_pipeline_timeout_invalid_zero` -- Verify 0 raises ValueError.
  4. `test_pipeline_timeout_invalid_negative` -- Verify negative raises ValueError.
  - **AC:** All tests pass.

**Checkpoint:** Full test coverage.

---

## Phase 5: Polish

- [ ] T009 [P] Add `PIPELINE_TIMEOUT` to `_log_config()` fields list in `main.py` (if not already done in T006).

**Checkpoint:** Deployment-ready.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Config):** No dependencies -- start immediately.
- **Phase 2 (Adapter):** No dependencies on Phase 1 (different file).
- **Phase 3 (Application):** Depends on Phase 1 (config field) and Phase 2 (consume_with_message).
- **Phase 4 (Tests):** T007 depends on Phase 3 (tests the new behavior). T008 depends on Phase 1 only.
- **Phase 5 (Polish):** Depends on Phase 3.

### Parallel Opportunities

**Phase 1 + Phase 2:** Fully parallel (different files).
**Phase 4 T008:** Parallel with Phase 2 and Phase 3 (config-only test).
**Phase 5 T009:** Parallel with Phase 4.

### Implementation Strategy

1. T001 + T002 in parallel (config + adapter)
2. T003 + T004 + T005 + T006 sequentially (all in main.py)
3. T007 + T008 in parallel (test files)
4. T009 final polish
