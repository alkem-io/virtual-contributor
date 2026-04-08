# Tasks: Early ACK with Async Processing

**Spec ID:** 008
**Story:** alkem-io/alkemio#1824
**Date:** 2026-04-08

## Task List (dependency-ordered)

### T-001: Add `pipeline_timeout` config field

**File:** `core/config.py`
**Depends on:** None
**Description:** Add `pipeline_timeout: int = 3600` to `BaseConfig`. Add validation in `_resolve_backward_compat_and_validate` that `pipeline_timeout > 0`.
**Acceptance criteria:**
- Field exists with default 3600.
- Env var `PIPELINE_TIMEOUT` overrides the default.
- Value <= 0 raises `ValueError`.
**Test:** `tests/core/test_config_validation.py` -- add test for pipeline_timeout validation.

### T-002: Refactor RabbitMQAdapter to early ACK and task dispatch

**File:** `core/adapters/rabbitmq.py`
**Depends on:** None
**Description:**
- Add `_tasks: set[asyncio.Task]` instance attribute.
- In `on_message` closure inside `consume()`:
  - Parse JSON from `message.body`. On failure, use existing retry/reject logic (unchanged).
  - On success, call `message.ack()` immediately.
  - Create `asyncio.Task` for `callback(body)`, add to `_tasks`, attach done-callback to remove from `_tasks` and log unhandled exceptions.
- Add `async def drain(self, timeout: float = 30.0) -> None` method that awaits all in-flight tasks with a bounded timeout, then cancels any remaining.
**Acceptance criteria:**
- Message is ACKed before callback executes.
- Callback runs as an asyncio.Task.
- JSON parse failure still triggers retry/reject logic without ACK.
- `drain()` waits for tasks up to timeout, then cancels.
- `_tasks` set is cleaned up as tasks complete.
**Test:** `tests/core/test_rabbitmq_early_ack.py`

### T-003: Add outer pipeline timeout in main.on_message

**File:** `main.py`
**Depends on:** T-001
**Description:**
- Wrap `plugin.handle(event)` in `asyncio.wait_for(timeout=config.pipeline_timeout)`.
- On `asyncio.TimeoutError`, log at ERROR level and publish an error result to the result queue.
**Acceptance criteria:**
- Slow handlers are cancelled after `pipeline_timeout` seconds.
- Timeout error produces an error result on the result queue.
- Normal (fast) handlers are unaffected.
**Test:** `tests/test_pipeline_timeout.py`

### T-004: Update shutdown sequence to drain in-flight tasks

**File:** `main.py`
**Depends on:** T-002
**Description:**
- Before `transport.close()`, call `await transport.drain()` to wait for in-flight tasks.
- Log the drain operation.
**Acceptance criteria:**
- Shutdown waits for in-flight tasks before closing the transport.
- After drain timeout, remaining tasks are cancelled.
**Test:** Covered by T-002 drain tests.

### T-005: Log pipeline_timeout at startup

**File:** `main.py`
**Depends on:** T-001
**Description:**
- Add `pipeline_timeout` to the `_log_config` fields list.
**Acceptance criteria:**
- `PIPELINE_TIMEOUT` value is logged at startup.
**Test:** Manual / visual inspection (startup logging).

### T-006: Write unit tests for early ACK behavior

**File:** `tests/core/test_rabbitmq_early_ack.py` (new)
**Depends on:** T-002
**Description:** Test cases:
1. Valid JSON message is ACKed before callback executes.
2. Invalid JSON message triggers retry with x-retry-count header.
3. Invalid JSON message after max retries is rejected.
4. `drain()` waits for in-flight tasks.
5. `drain()` cancels tasks after timeout.
6. Task cleanup: completed tasks are removed from `_tasks`.
**Acceptance criteria:** All tests pass. Coverage of `on_message` and `drain` methods.

### T-007: Write unit tests for pipeline timeout

**File:** `tests/test_pipeline_timeout.py` (new)
**Depends on:** T-003
**Description:** Test cases:
1. Handler completing within timeout produces normal result.
2. Handler exceeding timeout is cancelled and error result is published.
**Acceptance criteria:** All tests pass. Coverage of timeout path in `on_message`.

### T-008: Run full test suite and fix regressions

**Depends on:** T-001 through T-007
**Description:** Run `poetry run pytest` and fix any failures.
**Acceptance criteria:** All tests pass (exit code 0).
