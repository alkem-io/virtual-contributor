# Tasks: Configurable Vector DB Distance Function

**Input**: Design documents from `specs/009-vector-db-distance-fn/`
**Prerequisites**: plan.md (required), spec.md (required), data-model.md
**Organization**: Tasks grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Config + Validation)

**Purpose**: Add the configuration field and validation.

- [X] T001 Add `vector_db_distance_fn: str = "cosine"` field to BaseConfig in core/config.py
- [X] T002 Add set-membership validation for `vector_db_distance_fn` in the model_validator in core/config.py, rejecting values not in `{"cosine", "l2", "ip"}`

**Checkpoint**: Configuration field and validation in place.

---

## Phase 2: User Story 1 — Configure Vector Similarity Distance Metric (Priority: P1)

**Goal**: Pass the configured distance function through to all ChromaDB collection operations.

**Independent Test**: Set `VECTOR_DB_DISTANCE_FN=l2`, start the service, and verify ChromaDB collections use L2 distance.

### Implementation for User Story 1

- [X] T003 [P] [US1] Add `distance_fn: str = "cosine"` constructor parameter to ChromaDBAdapter in core/adapters/chromadb.py, store as `self._distance_fn`
- [X] T004 [US1] Pass `metadata={"hnsw:space": self._distance_fn}` to `get_or_create_collection` in `query()`, `ingest()`, and `get()` methods in core/adapters/chromadb.py
- [X] T005 [US1] Pass `distance_fn=config.vector_db_distance_fn` to ChromaDBAdapter constructor in main.py `_create_adapters()`

**Checkpoint**: Distance function is fully configurable and applied to all collection operations.

---

## Phase 3: Polish & Cross-Cutting Concerns

- [X] T006 [P] Add `VECTOR_DB_DISTANCE_FN=cosine` with description to .env.example

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately
- **User Story 1 (Phase 2)**: Depends on Phase 1 (config field must exist)
- **Polish (Phase 3)**: Independent of other phases

### Parallel Opportunities

- T003 can run in parallel with T001/T002 (different file)
- T006 can run in parallel with any other task (different file)
- T004 depends on T003 (same file)
- T005 depends on T003 (needs adapter to accept the param)
