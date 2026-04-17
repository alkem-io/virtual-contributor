# Feature Specification: PromptGraph Robustness & Expert Plugin Integration

**Feature Branch**: `023-promptgraph-robustness`
**Created**: 2026-04-17
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Reliable Graph Execution with Server Schemas (Priority: P1)

As an operator deploying the expert plugin with Alkemio-defined prompt graphs, the PromptGraph engine correctly handles the server's list-based property schemas, LLM null outputs, and Pydantic model state — so graph execution completes without crashing on real-world graph definitions.

**Why this priority**: The Alkemio server serialises JSON Schema `properties` as a list of `{name, type, optional}` entries (GraphQL cannot express dict-keyed objects). Without normalization, `json_schema_to_pydantic` crashes or produces incorrect models. This is a hard blocker for any graph-based expert query.

**Independent Test**: Compile a PromptGraph with a list-based state schema and invoke it with a mock LLM — verify it completes without errors.

**Acceptance Scenarios**:

1. **Given** a graph definition with `properties` as a list of `{name, type, description, optional}` entries, **When** the graph is compiled, **Then** `_build_state_model` produces a valid Pydantic model with correct field types and defaults.
2. **Given** a node with an output schema containing optional fields, **When** the LLM returns `null` for those fields, **Then** the Pydantic parser accepts the output without validation errors.
3. **Given** a graph with special nodes (e.g., `retrieve`), **When** the graph executes with a Pydantic state model, **Then** special node functions receive a plain dict (not a Pydantic instance).
4. **Given** a graph invocation completes, **When** `invoke()` returns, **Then** the result is a plain dict regardless of whether the internal state used a Pydantic model.

---

### User Story 2 - Structured Output Recovery (Priority: P2)

As a virtual contributor user, when the LLM ignores format instructions and wraps required fields under extra JSON keys, the system recovers the expected fields instead of returning an error — so my question still gets answered.

**Why this priority**: Small/local LLMs (e.g., Mistral models) frequently produce valid JSON that doesn't match the exact schema shape. Without recovery, the entire graph execution fails and the user gets no answer. Recovery is a resilience feature, not a correctness feature.

**Independent Test**: Feed a deliberately malformed LLM response through `_recover_fields` and verify fields are extracted.

**Acceptance Scenarios**:

1. **Given** a node expects `{"answer": "..."}` but the LLM returns `{"result": {"answer": "..."}}`, **When** the structured parser fails, **Then** `_recover_fields` walks the JSON and extracts the `answer` field.
2. **Given** a node expects `{"summary": "..."}` but the LLM returns `{"summary_text": "..."}`, **When** recovery runs, **Then** the `_text` alias maps to the correct field.
3. **Given** recovery fails (required fields missing), **When** `_recover_fields` returns None, **Then** the original exception is re-raised.

---

### User Story 3 - Conversational Expert with History (Priority: P2)

As a virtual contributor user, when I ask a follow-up question in a conversation, the expert plugin passes my conversation history to the prompt graph — so the LLM's check_input and answer_question nodes have full context.

**Why this priority**: Without conversation history, the graph's `check_input` node cannot detect follow-up questions or rephrase them, and the `answer_question` node lacks conversational context. This breaks multi-turn conversations.

**Independent Test**: Send an Input event with history entries and verify the initial state's `messages` and `conversation` fields are populated.

**Acceptance Scenarios**:

1. **Given** an Input event with 3 history entries, **When** the expert plugin handles it, **Then** `initial_state["messages"]` contains 4 entries (3 history + 1 current).
2. **Given** an Input event with history, **When** the graph executes, **Then** the `conversation` state variable contains formatted `role:\ncontent` turns.
3. **Given** the retrieve node executes, **When** the state contains a `rephrased_question`, **Then** the retrieval query uses the rephrased question instead of the original.

---

### Edge Cases

- Schema with nested object properties (properties-within-properties): `_normalize_schema` must recurse.
- Schema with `anyOf`/`oneOf`/`allOf` combinators: normalization must recurse into each variant.
- LLM returns non-JSON text: `_recover_fields` returns None gracefully.
- Empty history on Input event: messages list has only the current message, conversation is single-entry.
- LLMPort adapter without `_llm` attribute: falls back to using the adapter directly.

## Requirements

### Functional Requirements

- **FR-001**: `_normalize_schema` MUST convert list-based `properties` to dict-keyed JSON Schema form, recursively.
- **FR-002**: Optional fields (marked with `optional: true`) MUST be widened to accept `null` with a `None` default.
- **FR-003**: `_recover_fields` MUST walk nested JSON to find model field names, including `_text` aliases.
- **FR-004**: `_make_chain_node` MUST unwrap `LLMPort` adapters to access the underlying `BaseChatModel` for LCEL piping.
- **FR-005**: All node functions MUST handle both dict and Pydantic model state transparently.
- **FR-006**: `invoke()` MUST return a plain dict, converting Pydantic model state if needed.
- **FR-007**: Expert plugin retrieve node MUST return `combined_knowledge_docs` (not `knowledge`/`sources`).
- **FR-008**: Expert plugin MUST populate `messages` and `conversation` from event history.
- **FR-009**: Expert plugin retrieve node MUST prefer `rephrased_question` over `current_question` for retrieval.

### Key Entities

- **PromptGraph**: Core domain class — extended with schema normalization, output recovery, and state conversion.
- **Node**: Unchanged — but output schemas are now normalized before model creation.

## Success Criteria

### Measurable Outcomes

- **SC-001**: PromptGraph compiles and executes successfully with Alkemio's list-based state schemas.
- **SC-002**: Structured output parsing failures are recovered at least 80% of the time when the LLM returns valid JSON with mismatched structure.
- **SC-003**: Multi-turn expert conversations receive contextually aware answers (conversation history is present in graph state).

## Assumptions

- The Alkemio server's prompt graph definitions use the `{name, type, description, optional}` list format for properties.
- `json_schema_to_pydantic.create_model` accepts standard JSON Schema dict format.
- LLMPort adapters that wrap LangChain models expose the underlying model via a `_llm` attribute.
- The expert plugin's prompt graph always includes a `check_input` node that reads the `conversation` state variable.
