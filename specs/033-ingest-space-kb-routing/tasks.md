# Tasks: Ingest Space Knowledge-Base Routing

**Input**: Design documents from `specs/033-ingest-space-kb-routing/`
**Organization**: Tasks grouped by user story to enable independent verification of each story's behaviour.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project (microkernel + plugins). Paths anchored at repository root.

---

## Phase 1: Foundational (Shared Infrastructure)

**Purpose**: Module-level scaffolding that every user story depends on.

- [X] T001 [P] Add `BOK_TYPE_SPACE` and `BOK_TYPE_KNOWLEDGE_BASE` constants to `plugins/ingest_space/space_reader.py`
- [X] T002 [P] Add `KNOWLEDGE_BASE_QUERY` GraphQL document to `plugins/ingest_space/space_reader.py`, reusing the existing `_CALLOUT_FIELDS` fragment

**Checkpoint**: Constants and query string are defined; nothing depends on them yet.

---

## Phase 2: User Story 1 — Knowledge-Base-Backed VCs Ingest (Priority: P1) 🎯 MVP

**Goal**: Route `alkemio-knowledge-base` events to `lookup.knowledgeBase()` and produce the same kind of documents the space path would produce, so the ~29 % of VCs previously stuck with empty collections start ingesting real content.

**Independent Test**: Publish an `IngestBodyOfKnowledge` with `type="alkemio-knowledge-base"` and verify the resulting collection contains chunks derived from the KB's callouts; assert no `Unable to find Space` error in the plugin logs.

### Tests for User Story 1

- [X] T003 [P] [US1] `TestKnowledgeBaseReader.test_walks_callouts` — verify KB callouts produce post documents in `tests/plugins/test_ingest_space.py`
- [X] T004 [P] [US1] `TestKnowledgeBaseReader.test_empty_knowledge_base_returns_empty_list` — verify `null` payload returns `[]` without raising
- [X] T005 [P] [US1] `TestKnowledgeBaseReader.test_issues_knowledge_base_query` — assert the GraphQL query string contains `knowledgeBase(ID:` and NOT `space(ID:`, and variables are `{"kbId": …}`
- [X] T006 [P] [US1] `TestBodyOfKnowledgeDispatcher.test_routes_alkemio_space_to_space_reader` — patch both readers, dispatcher calls only `read_space_tree`
- [X] T007 [P] [US1] `TestBodyOfKnowledgeDispatcher.test_routes_alkemio_knowledge_base_to_kb_reader` — patch both readers, dispatcher calls only `read_knowledge_base_tree`
- [X] T008 [P] [US1] `TestBodyOfKnowledgeDispatcher.test_unknown_type_defaults_to_space_reader` — unknown `bok_type` falls back to space reader
- [X] T009 [P] [US1] `TestIngestSpacePluginDispatchesOnType.test_plugin_uses_knowledge_base_reader_for_alkemio_knowledge_base` — end-to-end propagation from `event.type` into the dispatcher
- [X] T010 [P] [US1] `TestIngestSpacePluginDispatchesOnType.test_plugin_uses_space_reader_for_alkemio_space` — symmetric assertion for the space path

### Implementation for User Story 1

- [X] T011 [US1] Add `read_knowledge_base_tree(graphql_client, kb_id)` in `plugins/ingest_space/space_reader.py`: issue `KNOWLEDGE_BASE_QUERY`, return `[]` on missing payload, reshape response into `_process_space`-compatible dict, delegate traversal
- [X] T012 [US1] Add `read_body_of_knowledge(graphql_client, bok_id, bok_type)` dispatcher in `plugins/ingest_space/space_reader.py`: select reader based on `bok_type`, fall back to `read_space_tree` on unknown types
- [X] T013 [US1] Replace `read_space_tree(self._graphql_client, bok_id)` with `read_body_of_knowledge(self._graphql_client, bok_id, event.type)` in `plugins/ingest_space/plugin.py`

**Checkpoint**: Knowledge-base BoKs route through `lookup.knowledgeBase()` and produce populated collections.

---

## Phase 3: User Story 2 — Operator Sees Resolved Routing in Logs (Priority: P2)

**Goal**: Make the routing decision visible to operators reading pod logs.

**Independent Test**: Trigger any ingest run; grep logs for a single INFO line containing the BoK id and type.

### Implementation for User Story 2

- [X] T014 [US2] Add `logger.info("Ingesting BoK %s (type=%s, purpose=%s)", bok_id, event.type, event.purpose)` at the top of `IngestSpacePlugin.handle()` (after the graphql_client null-check, before the reader call) in `plugins/ingest_space/plugin.py`

**Checkpoint**: Every `handle()` call emits one INFO line capturing the routing-relevant fields.

---

## Phase 4: User Story 3 — KB Root Documents Tagged `knowledge` (Priority: P3)

**Goal**: Tag depth-0 documents emitted from the knowledge-base path with `DocumentType.KNOWLEDGE`, not `DocumentType.SPACE`.

**Independent Test**: Run the KB reader against a payload with a populated profile description; assert the root document's `metadata.type == "knowledge"`.

### Tests for User Story 3

- [X] T015 [P] [US3] `TestKnowledgeBaseReader.test_top_doc_type_is_knowledge` — root document type assertion

### Implementation for User Story 3

- [X] T016 [US3] Add kw-only `top_doc_type: str | None = None` to `_process_space` in `plugins/ingest_space/space_reader.py`; override the depth-0 type when set
- [X] T017 [US3] Pass `top_doc_type=DocumentType.KNOWLEDGE.value` from `read_knowledge_base_tree` into `_process_space`

**Checkpoint**: Root documents are tagged accurately; space-path tagging unchanged.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T018 Run `poetry run ruff check core/ plugins/ tests/` and `poetry run pyright core/ plugins/` — both clean (no new errors)
- [X] T019 Run `poetry run pytest tests/plugins/test_ingest_space.py -q` — full ingest_space suite green (37 tests)
- [X] T020 Run `poetry run pytest --ignore=tests/evaluation -q` — full suite green to confirm no regression elsewhere (528 tests)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately.
- **User Story 1 (Phase 2)**: Depends on Foundational.
- **User Story 2 (Phase 3)**: Independent of US1 — could be done first, but easier to add the log line once the routing exists.
- **User Story 3 (Phase 4)**: Depends on Foundational; the implementation step T016 modifies the same function (`_process_space`) that US1 calls, so US1 and US3 must coordinate the diff but their tests are independent.
- **Polish (Phase 5)**: After all user stories.

### Within Each User Story

- Tests written alongside the implementation (test-first not required for this single-author bug fix, but every behavioural change has a corresponding test before the PR is opened).
- T013 (plugin route swap) depends on T011 and T012 being merged into the same module.
- T017 (passing `top_doc_type`) depends on T016 (adding the parameter).

### Parallel Opportunities

- T001 and T002 are both module-level scaffolding in the same file, but their patches do not overlap — can be written in parallel.
- T003–T010 are all test functions in different methods — fully parallel.

---

## Implementation Strategy

**MVP scope**: Phase 1 + Phase 2 deliver the routing fix that unblocks the
69 knowledge-base-backed VCs. US2 and US3 are quality-of-life improvements
that ride along in the same PR because they touch the same files.

**Sequencing the diff**: All tasks land in a single commit on
`fix/ingest-space-knowledge-base` (PR #98). The retrospec spec is captured
on this `033-ingest-space-kb-routing` branch.

---

## Notes

- All tasks marked `[X]` because the implementation already shipped on `fix/ingest-space-knowledge-base` (PR #98) and this retrospec records the spec post-hoc.
- The test suite includes a guardrail (T005) that asserts the GraphQL query string explicitly — so an accidental future revert to `lookup.space()` on the KB path is caught at test time, not in production.
