# Tasks: PromptGraph Robustness & Expert Plugin Integration

**Input**: Design documents from `specs/023-promptgraph-robustness/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: Tasks grouped by user story.

## Phase 1: Foundational — Schema Normalization

**Purpose**: Core schema handling that all other changes depend on

- [X] T001 [US1] Add `_normalize_schema` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T002 [US1] Add `_make_nullable` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T003 [US1] Call `_normalize_schema` in `_build_state_model` in `core/domain/prompt_graph.py`
- [X] T004 [US1] Call `_normalize_schema` in `_build_output_model` in `core/domain/prompt_graph.py`

**Checkpoint**: PromptGraph compiles with Alkemio list-based schemas

---

## Phase 2: User Story 1 - Reliable Graph Execution (Priority: P1)

**Goal**: Graph execution handles Pydantic model state and LLMPort adapters

- [X] T005 [US1] Add `_state_to_dict` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T006 [US1] Add `_wrap_special_node` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T007 [US1] Wrap special nodes in `compile()` with `_wrap_special_node` in `core/domain/prompt_graph.py`
- [X] T008 [US1] Unwrap LLMPort adapter in `_make_chain_node` (`runnable_llm`) in `core/domain/prompt_graph.py`
- [X] T009 [US1] Add `_read` helper in `node_fn` for dict/Pydantic state access in `core/domain/prompt_graph.py`
- [X] T010 [US1] Convert `invoke()` result to dict via `_state_to_dict` in `core/domain/prompt_graph.py`

**Checkpoint**: Graph executes end-to-end with Pydantic state model

---

## Phase 3: User Story 2 - Structured Output Recovery (Priority: P2)

**Goal**: Recover expected fields from malformed LLM output

- [X] T011 [US2] Add `_recover_fields` static method to `PromptGraph` in `core/domain/prompt_graph.py`
- [X] T012 [US2] Add try/except with recovery in `_make_chain_node` structured output path in `core/domain/prompt_graph.py`

**Checkpoint**: Malformed LLM output is recovered when possible

---

## Phase 4: User Story 3 - Expert Plugin Integration (Priority: P2)

**Goal**: Expert plugin correctly integrates with PromptGraph

- [X] T013 [US3] Change retrieve node to return `combined_knowledge_docs` in `plugins/expert/plugin.py`
- [X] T014 [US3] Change retrieve node query to prefer `rephrased_question` in `plugins/expert/plugin.py`
- [X] T015 [US3] Build `messages` list from event history in `_handle_with_graph` in `plugins/expert/plugin.py`
- [X] T016 [US3] Build `conversation` string from messages in `_handle_with_graph` in `plugins/expert/plugin.py`
- [X] T017 [US3] Update `initial_state` with populated messages and conversation in `plugins/expert/plugin.py`

**Checkpoint**: Expert plugin graph execution uses correct state keys and conversation context

---

## Dependencies & Execution Order

- **Phase 1** (T001-T004): No dependencies — schema normalization is self-contained
- **Phase 2** (T005-T010): T007 depends on T006. T009 depends on T008.
- **Phase 3** (T011-T012): T012 depends on T011
- **Phase 4** (T013-T017): T016 depends on T015. T017 depends on T015, T016. Independent of Phases 1-3.

### Parallel Opportunities

- T001 and T002 can run in parallel (independent static methods)
- T005 and T006 can run in parallel
- T013 and T014 can run in parallel (different parts of retrieve_node)
- Phase 4 can run in parallel with Phases 1-3 (different files)
