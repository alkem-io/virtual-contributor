# Feature Specification: Retry Error Reporting

**Feature Branch**: `024-retry-error-reporting`
**Created**: 2026-04-17
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Silent Retries with Final Error (Priority: P1)

As a virtual contributor user, when my query fails due to a transient error, the system retries silently without spamming the chat with intermediate failure messages — and only when all retries are exhausted, I receive a single, clear error message explaining what went wrong.

**Why this priority**: Previously, the error response was published on every failure before retry, flooding the chat with "Error: ..." messages for a single query. Users saw multiple error messages for what was effectively one failure, degrading trust and creating confusion.

**Independent Test**: Send a message that causes a handler timeout, configure max_retries=3, and verify only one error response is published (after the 3rd attempt), not three.

**Acceptance Scenarios**:

1. **Given** a handler that times out and max_retries is 3, **When** the first attempt fails, **Then** the message is requeued silently (no error response published).
2. **Given** a handler that fails on every attempt, **When** the final retry (attempt 3/3) fails, **Then** an error response is published with the timeout/error message.
3. **Given** a handler that fails on attempt 1 but succeeds on attempt 2, **Then** no error response is ever published (normal success response only).
4. **Given** a parse_event failure (no event object), **When** `_retry_or_reject` is called without event/error_text, **Then** the message is rejected without publishing any response.

---

### User Story 2 - Consolidated Error Handling (Priority: P2)

As a developer maintaining the message handler, the error response construction is centralized in `_retry_or_reject` rather than duplicated in every except block — reducing code duplication and ensuring consistent error reporting behavior.

**Why this priority**: The previous code duplicated the `Response(result=...)` + `build_response_envelope` + `_publish_result` pattern in both the TimeoutError and Exception handlers. This made it easy to introduce inconsistencies and harder to change the error reporting strategy.

**Independent Test**: Read the `on_message` function and verify no error response construction exists outside `_retry_or_reject`.

**Acceptance Scenarios**:

1. **Given** a TimeoutError in the handler, **When** caught, **Then** the except block delegates entirely to `_retry_or_reject` with event and error_text.
2. **Given** a general Exception in the handler, **When** caught, **Then** the except block delegates entirely to `_retry_or_reject`.
3. **Given** `_retry_or_reject` is called with `event=None`, **When** on the final attempt, **Then** no error response is published (safe for parse failures).

---

### Edge Cases

- Publishing the terminal error response itself fails: caught and logged, message still rejected.
- `event` is provided but `error_text` is None: no error response published.
- Message has no headers (first attempt): `retry_count` defaults to 0.

## Requirements

### Functional Requirements

- **FR-001**: `_retry_or_reject` MUST accept optional `event` and `error_text` keyword arguments.
- **FR-002**: On intermediate retry attempts, `_retry_or_reject` MUST NOT publish any error response.
- **FR-003**: On the final attempt (retry_count >= max_retries - 1), if both `event` and `error_text` are provided, MUST publish an error response before rejecting.
- **FR-004**: If publishing the terminal error response fails, the failure MUST be logged but MUST NOT prevent message rejection.
- **FR-005**: The `on_message` TimeoutError and Exception handlers MUST NOT construct or publish error responses directly.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Users see exactly one error message per failed query, not one per retry attempt.
- **SC-002**: Zero code duplication of error response construction in `on_message`.
- **SC-003**: Terminal error response is published for 100% of queries that exhaust all retries.

## Assumptions

- The existing `_publish_result` and `router.build_response_envelope` functions work correctly.
- `config.rabbitmq_max_retries` is always >= 1.
- The `x-retry-count` header is correctly incremented by `republish_with_headers`.
