# Tasks: Space Ingest Context Enrichment & URI Tracking

**Input**: Design documents from `specs/022-space-ingest-context-uri/`
**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: Tasks grouped by user story.

## Phase 1: Foundational

**Purpose**: Data model extension required by both stories

- [X] T001 [US1,US2] Add `uri: str | None = None` field to `DocumentMetadata` in `core/domain/ingest_pipeline.py`
- [X] T002 [US2] Conditionally include `uri` in stored metadata dict in `core/domain/pipeline/steps.py` `StoreStep`

**Checkpoint**: Pipeline can propagate URI metadata end-to-end

---

## Phase 2: User Story 1 - Contextual Knowledge Retrieval (Priority: P1)

**Goal**: Contributions retain parent callout context after chunking

**Independent Test**: Ingest a space and verify stored content includes callout title prefix

- [X] T003 [P] [US1] Add `url` to GraphQL `_CALLOUT_FIELDS` profile selections in `plugins/ingest_space/space_reader.py`
- [X] T004 [P] [US1] Add `url` to `SPACE_TREE_QUERY` profile selections at all 3 depth levels in `plugins/ingest_space/space_reader.py`
- [X] T005 [US1] Build callout context string (title + truncated description) in `_process_callout` in `plugins/ingest_space/space_reader.py`
- [X] T006 [US1] Prepend callout context to post content in `_process_callout` in `plugins/ingest_space/space_reader.py`
- [X] T007 [P] [US1] Prepend callout context to whiteboard content in `_process_callout` in `plugins/ingest_space/space_reader.py`
- [X] T008 [P] [US1] Prepend callout context to link content in `_process_callout` in `plugins/ingest_space/space_reader.py`

**Checkpoint**: Ingested contributions include parent callout context

---

## Phase 3: User Story 2 - Source URI Attribution (Priority: P2)

**Goal**: Entity URLs propagate to vector store for source linking

**Independent Test**: Ingest a space and verify stored metadata contains `uri` fields

- [X] T009 [US2] Add `uri` parameter to `_append_unique` function signature in `plugins/ingest_space/space_reader.py`
- [X] T010 [US2] Pass `uri=space_url` in `_process_space` in `plugins/ingest_space/space_reader.py`
- [X] T011 [US2] Pass `uri=callout_url` in `_process_callout` for callout document in `plugins/ingest_space/space_reader.py`
- [X] T012 [P] [US2] Pass `uri=post_profile.get("url")` for post contributions in `plugins/ingest_space/space_reader.py`
- [X] T013 [P] [US2] Pass `uri=wb_profile.get("url")` for whiteboard contributions in `plugins/ingest_space/space_reader.py`
- [X] T014 [P] [US2] Pass `uri=uri or link_profile.get("url")` for link contributions in `plugins/ingest_space/space_reader.py`

**Checkpoint**: All entity types have URI metadata in the vector store

---

## Dependencies & Execution Order

- **Phase 1**: No dependencies -- foundational model changes
- **Phase 2**: T005 depends on T003/T004 (need url in query results). T006-T008 depend on T005 (need callout_context built).
- **Phase 3**: T010-T014 depend on T009 (need uri parameter). T001 must be done for uri to propagate.

### Parallel Opportunities

- T003 and T004 can run in parallel (different string constants)
- T006, T007, T008 can run in parallel (different contribution types)
- T012, T013, T014 can run in parallel (different contribution types)
