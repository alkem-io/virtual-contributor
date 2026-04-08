# Tasks: Early ACK with Async Processing

**Spec:** 008
**Story:** alkem-io/alkemio#1824

## Task List

### T1: Add `pipeline_timeout` config field
**File:** `core/config.py`
**Dependencies:** None
**Acceptance Criteria:**
- `pipeline_timeout: int = 7200` field added to `BaseConfig`
- Validation: must be >= 0 (0 means no timeout)
- Existing config tests pass
**Test:** `test_config_pipeline_timeout` -- validates default, custom value, and invalid value rejection

### T2: Rewrite `RabbitMQAdapter.consume()` for early ACK + async dispatch
**File:** `core/adapters/rabbitmq.py`
**Dependencies:** T1
**Acceptance Criteria:**
- `consume()` accepts optional `pipeline_timeout: float | None` parameter
- Inner `on_message`:
  1. Parses JSON from message body
  2. On JSON parse failure: NACK with `requeue=False`, log error, return
  3. On success: ACK immediately
  4. Spawn callback as background task via `asyncio.create_task()`
  5. If `pipeline_timeout` set, wrap callback in `asyncio.wait_for()`
  6. On timeout: log error (callback's own error handling publishes result)
- Background tasks tracked in `self._inflight_tasks: set[asyncio.Task]`
- Task `add_done_callback` removes from set on completion
**Test:** `test_valid_message_acked_before_callback`, `test_invalid_json_nacked`

### T3: Add `drain_tasks()` method to RabbitMQAdapter
**File:** `core/adapters/rabbitmq.py`
**Dependencies:** T2
**Acceptance Criteria:**
- `async def drain_tasks(self, timeout: float = 30.0) -> None`
- Gathers all in-flight tasks with the given timeout
- Logs count of pending tasks at start
- On timeout, logs warning about tasks that did not complete
- Cancels remaining tasks after timeout
**Test:** `test_graceful_shutdown_drains_tasks`

### T4: Update `main.py` to pass `pipeline_timeout` and drain on shutdown
**File:** `main.py`
**Dependencies:** T1, T2, T3
**Acceptance Criteria:**
- `transport.consume()` call passes `pipeline_timeout=config.pipeline_timeout`
- Shutdown sequence calls `await transport.drain_tasks()` before `transport.close()`
- `pipeline_timeout` logged at startup in `_log_config()`
**Test:** Manual verification (main.py excluded from coverage per pyproject.toml)

### T5: Write unit tests for early ACK behavior
**File:** `tests/core/test_rabbitmq_early_ack.py`
**Dependencies:** T2, T3
**Acceptance Criteria:**
- `test_valid_message_acked_before_callback` -- mock aio_pika message, verify ack() called before callback body executes
- `test_invalid_json_nacked` -- non-JSON body triggers reject(requeue=False)
- `test_pipeline_timeout_fires` -- slow callback exceeding timeout logs error
- `test_graceful_shutdown_drains_tasks` -- drain_tasks waits for pending work
- `test_callback_exception_does_not_crash_consumer` -- callback exception is caught, consumer continues
**Test:** Self-testing (this IS the test task)

### T6: Verify all existing tests pass
**Dependencies:** T1-T5
**Acceptance Criteria:**
- `poetry run pytest` exits 0
- No test modifications required
**Test:** Full test suite green

### T7: Verify lint, typecheck, build
**Dependencies:** T6
**Acceptance Criteria:**
- `poetry run ruff check core/ plugins/ tests/` exits 0
- `poetry run pyright core/ plugins/` exits 0
**Test:** Static analysis clean
