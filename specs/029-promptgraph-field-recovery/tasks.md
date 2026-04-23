# Tasks: PromptGraph Field Recovery

**Input**: Design documents from `specs/029-promptgraph-field-recovery/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: Tasks grouped by user story.

## Phase 1: User Story 1 - Responses Survive Dropped Fields (Priority: P1)

**Goal**: `_recover_fields` fills missing required fields instead of returning None

- [X] T001 [US1] Add `_default_for_annotation` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T002 [US1] Implement type mapping: str->""  bool->False  int/float->0  list->[]  dict->{}  BaseModel->{}  unknown->None in `core/domain/prompt_graph.py`
- [X] T003 [US1] Add Optional[X] / Union[X, None] unwrapping logic before type lookup in `core/domain/prompt_graph.py`
- [X] T004 [US1] Replace the `return None` for missing required fields with default-fill loop in `_recover_fields` in `core/domain/prompt_graph.py`
- [X] T005 [US1] Add test `test_fills_missing_str_with_empty_string` (Mistral-Small drop case) in `tests/core/domain/test_prompt_graph.py`
- [X] T006 [US1] Add test `test_real_world_answer_response_shape` (full Mistral-Small regression) in `tests/core/domain/test_prompt_graph.py`

**Checkpoint**: Recovery fills defaults; str and real-world regression tests pass

---

## Phase 2: User Story 2 - Type-Appropriate Defaults (Priority: P2)

**Goal**: All common Python types have correct defaults

- [X] T007 [US2] Add test `test_fills_missing_dict_with_empty_dict` in `tests/core/domain/test_prompt_graph.py`
- [X] T008 [US2] Add test `test_fills_missing_list_with_empty_list` in `tests/core/domain/test_prompt_graph.py`
- [X] T009 [US2] Add test `test_fills_missing_bool_with_false` in `tests/core/domain/test_prompt_graph.py`
- [X] T010 [US2] Add test `test_fills_missing_int_with_zero` in `tests/core/domain/test_prompt_graph.py`

**Checkpoint**: All type-default tests pass

---

## Phase 3: User Story 3 - Warning Logging (Priority: P3)

**Goal**: Filled fields produce a warning log

- [X] T011 [US3] Add `logger.warning` call listing sorted filled field names in `_recover_fields` in `core/domain/prompt_graph.py`

**Checkpoint**: Warning log emitted when defaults are applied

---

## Dependencies & Execution Order

- **Phase 1**: T004 depends on T001-T003 (needs the default method). T005-T006 depend on T004.
- **Phase 2**: T007-T010 depend on T001-T004 (need the default-fill infrastructure). Can run in parallel with each other.
- **Phase 3**: T011 is independent of tests but logically part of T004's implementation.
- T001-T003 can be implemented as a single atomic change (one static method).

### Parallel Opportunities

- T005, T006, T007, T008, T009, T010 can all run in parallel (independent test functions).
