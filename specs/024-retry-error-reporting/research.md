# Research: Retry Error Reporting

**Feature Branch**: `024-retry-error-reporting`
**Date**: 2026-04-17

## Decision Summary

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Publish error only on final attempt | Avoid spamming chat with intermediate failures |
| D2 | Centralize in `_retry_or_reject` | Eliminate duplication in except blocks |
| D3 | Optional event/error_text params | Support both parseable and unparseable message failures |

## Decisions

### D1: Publish error response only on final retry attempt

**Decision**: Intermediate retry attempts are silent. Only when `retry_count >= max_retries - 1` (the last attempt) is an error response published.

**Rationale**: The previous implementation published an error response on every handler failure, then retried the message. With `max_retries=3`, a single transient failure produced 3 error messages in the chat. Users reported confusion seeing multiple identical errors. The new approach gives the system a chance to recover silently, and only notifies the user when recovery is impossible.

**Alternatives considered**:
- Publish on first failure only (suppress subsequent): Rejected because the first failure might be transient, and publishing immediately doesn't give the system a chance to recover.
- Never publish error responses: Rejected because users need closure — a message that silently disappears is worse than an explicit error.

### D2: Centralize error publishing in `_retry_or_reject`

**Decision**: Moved error response construction from the `on_message` except blocks into `_retry_or_reject`.

**Rationale**: The previous code duplicated the `Response(result=...)` → `build_response_envelope` → `_publish_result` pattern in both the TimeoutError and Exception handlers. This made the retry-vs-publish logic unclear and error-prone. Centralization makes the policy explicit: "publish only on final attempt" is implemented in one place.

### D3: Optional event/error_text parameters

**Decision**: `_retry_or_reject` accepts `event: object | None = None` and `error_text: str | None = None` as keyword-only arguments.

**Rationale**: For parse failures (where `router.parse_event()` throws), there is no event object and no meaningful error text to publish. The function must still handle requeue/reject in this case. Making the params optional with `None` defaults allows the same function to handle both cases without conditional callers.
