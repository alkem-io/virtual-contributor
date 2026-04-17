# Tasks: Retry Error Reporting

**Input**: Design documents from `specs/024-retry-error-reporting/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: Tasks grouped by user story.

## Phase 1: User Story 1 - Silent Retries with Final Error (Priority: P1)

**Goal**: Error response only published on final retry attempt

- [X] T001 [US1] Extend `_retry_or_reject` signature with `event` and `error_text` keyword-only params in `main.py`
- [X] T002 [US1] Update `_retry_or_reject` docstring to document the silent-retry behavior in `main.py`
- [X] T003 [US1] Add terminal error publishing block (guarded by `event is not None and error_text`) before `message.reject` in `main.py`
- [X] T004 [US1] Add try/except around terminal error publishing to log and continue on failure in `main.py`

**Checkpoint**: `_retry_or_reject` publishes error only on final attempt

---

## Phase 2: User Story 2 - Consolidated Error Handling (Priority: P2)

**Goal**: Error response construction removed from except blocks

- [X] T005 [US2] Replace TimeoutError except block to delegate to `_retry_or_reject(message, body, event=event, error_text=...)` in `main.py`
- [X] T006 [US2] Replace general Exception except block to delegate to `_retry_or_reject(message, body, event=event, error_text=...)` in `main.py`
- [X] T007 [US2] Remove `from core.events.response import Response` and `build_response_envelope`/`_publish_result` calls from except blocks in `main.py`

**Checkpoint**: on_message except blocks are clean, delegation-only

---

## Dependencies & Execution Order

- **Phase 1**: T003 depends on T001 (needs the new params). T004 is part of T003.
- **Phase 2**: T005 and T006 can run in parallel. Both depend on Phase 1 (need the new signature).
- T007 is implicit in T005/T006 — removing the old code is part of replacing it.

### Parallel Opportunities

- T005 and T006 can run in parallel (different except blocks)
