# Tasks: Ingest Website Result Correlation Fields

**Input**: Design documents from `specs/032-ingest-result-correlation/`
**Organization**: Tasks grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 = correlation, US2 = backward compatibility)
- All tasks below are marked `[X]` because the implementation already exists on this branch.

---

## Phase 1: Foundational

**Purpose**: No foundational scaffolding required — the event model and plugin already exist.

- [X] T001 Confirm `IngestWebsiteResult` exists in `core/events/ingest_website.py` and is wired through `core/router.py`.
- [X] T002 Confirm `IngestWebsitePlugin.handle` returns an `IngestWebsiteResult` on every code path.

**Checkpoint**: Foundation verified — both user stories can proceed.

---

## Phase 2: User Story 1 — Correlate Website Ingest Result to Owning Persona (P1) 🎯 MVP

**Goal**: Deliver enough information in the result envelope for the alkemio-server to correlate the result back to the persona that owns the body of knowledge.

**Independent Test**: Construct `IngestWebsiteResult` from a known `IngestWebsite` event, dump to dict, assert `personaId`, `type`, `purpose` round-trip.

### Tests for User Story 1

- [X] T010 [P] [US1] Add `test_result_with_identification_fields` to `tests/core/test_events.py` asserting explicit values round-trip via `model_dump(by_alias=True)`.
- [X] T011 [P] [US1] Extend `test_pipeline_composition` in `tests/plugins/test_ingest_website.py` to assert `result.persona_id == event.persona_id`, `result.type == event.type`, `result.purpose == event.purpose` on the normal-ingest path.
- [X] T012 [P] [US1] Extend `test_empty_crawl_runs_cleanup` in `tests/plugins/test_ingest_website.py` to assert the same propagation on the cleanup-only path.

### Implementation for User Story 1

- [X] T013 [US1] Add `body_of_knowledge_id`, `type`, `purpose`, `persona_id` fields to `IngestWebsiteResult` in `core/events/ingest_website.py`, with empty-string defaults and `Field(alias=...)` for the multi-word fields.
- [X] T014 [US1] Update the docstring of `IngestWebsiteResult` to explain why `bodyOfKnowledgeId` defaults to empty string for the website plugin.
- [X] T015 [US1] In `plugins/ingest_website/plugin.py`, populate `type=event.type, purpose=event.purpose, persona_id=event.persona_id` in the cleanup-only success/failure return path.
- [X] T016 [US1] In `plugins/ingest_website/plugin.py`, populate the same three kwargs in the normal-ingest success/failure return path.
- [X] T017 [US1] In `plugins/ingest_website/plugin.py`, populate the same three kwargs in the exception handler return path.

**Checkpoint**: User Story 1 fully functional — every result emitted from `IngestWebsitePlugin` carries identification fields populated from the inbound request.

---

## Phase 3: User Story 2 — Backward-Compatible Wire Format (P1)

**Goal**: Existing alkemio-server deployments that do not yet read the new fields continue to deserialize result payloads without error.

**Independent Test**: Construct `IngestWebsiteResult()` with no kwargs; assert `model_dump(by_alias=True)` produces a payload with the new fields defaulting to `""`, and that all pre-existing fields (`result`, `error`, `timestamp`) keep their names and types.

### Tests for User Story 2

- [X] T020 [P] [US2] Extend `test_result_model` in `tests/core/test_events.py` to assert default payload includes `bodyOfKnowledgeId == ""`, `personaId == ""`, `type == ""`, `purpose == ""`.

### Implementation for User Story 2

- [X] T021 [US2] Use empty-string defaults on every new field in `IngestWebsiteResult` (covered by T013 — same edit).
- [X] T022 [US2] Verify pre-existing fields (`timestamp`, `result`, `error`) are unchanged in name and type (covered by `test_result_failure` continuing to pass).

**Checkpoint**: User Story 2 fully functional — the wire format is additive, no consumer migration required.

---

## Phase 4: Polish

- [X] T030 [P] Document the field additions in this spec's `data-model.md` and `contracts/ingest-website-result.md`.
- [X] T031 Run the affected test files locally — `poetry run pytest tests/core/test_events.py tests/plugins/test_ingest_website.py` — and confirm they pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 (Foundational): trivial — verified state of the existing code, no work.
- Phase 2 (US1): depends on Phase 1.
- Phase 3 (US2): may proceed in parallel with Phase 2 because they share the same edit (T013/T021), and US2's test (T020) operates on the same file as US1's (T010).
- Phase 4 (Polish): after Phase 2 and Phase 3.

### Within Each User Story

- Tests (T010–T012, T020) MUST be written before implementation to verify they fail first.
- Schema change (T013) before plugin propagation (T015–T017).
- Plugin propagation tasks (T015–T017) target the same file (`plugin.py`) so cannot be parallelised with each other, but each is a single localised edit.

### Parallel Opportunities

- T010, T011, T012, T020 — different test functions, no shared state — can be drafted in parallel.
- T015, T016, T017 — same file but distinct return sites — can be applied in one edit pass.

---

## Notes

- All tasks `[X]` because the code already exists on this branch (commit `3dedb17`).
- Single PR delivery: the schema change, plugin change, and tests ship together — splitting would yield non-viable specs.
- No ADR required — see plan.md Constitution Check (P8 N/A).
