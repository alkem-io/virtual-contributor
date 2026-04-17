# Research: PromptGraph Robustness & Expert Plugin Integration

**Feature Branch**: `023-promptgraph-robustness`
**Date**: 2026-04-17

## Decision Summary

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Normalize list-based schemas to JSON Schema dicts | Alkemio GraphQL cannot express dict-keyed objects |
| D2 | Widen optional fields to accept null | LLMs frequently return null for unused fields |
| D3 | Best-effort field recovery from malformed JSON | Small LLMs ignore format instructions |
| D4 | Unwrap LLMPort adapter to get BaseChatModel | LCEL pipe operator requires Runnable, not Protocol |
| D5 | Wrap special nodes for dict state | Plugin code expects dicts, StateGraph uses Pydantic models |
| D6 | Return `combined_knowledge_docs` from retrieve | Matches the graph's state schema field name |
| D7 | Build conversation from event history | Graph nodes need formatted conversation context |

## Decisions

### D1: Normalize list-based schemas to JSON Schema dicts

**Decision**: Add `_normalize_schema` that recursively converts `properties: [{name, type, ...}]` to `properties: {name: {type, ...}}`.

**Rationale**: The Alkemio server serializes prompt graph state schemas through GraphQL, which cannot represent dicts with dynamic keys. The result is a list of `{name, type, description, optional}` entries. `json_schema_to_pydantic.create_model` expects standard JSON Schema with dict-keyed properties. Without normalization, the model creation either crashes or produces a model with no fields.

**Alternatives considered**:
- Fix on the server side: Rejected — GraphQL's type system fundamentally cannot express `Record<string, SchemaProperty>`. The normalization must happen client-side.
- Use a different model generation library: Rejected — `json_schema_to_pydantic` is already a dependency and works correctly with standard schemas.

### D2: Widen optional fields to accept null

**Decision**: `_make_nullable` converts `type: "string"` to `type: ["string", "null"]` with `default: None`.

**Rationale**: When `json_schema_to_pydantic` sees `type: "string"`, it generates a non-nullable `str` field. LLMs frequently return `null` for unused optional fields, causing Pydantic validation to fail. Widening the type at schema level is cleaner than post-processing the LLM output.

### D3: Best-effort field recovery from malformed JSON

**Decision**: `_recover_fields` finds the JSON body in raw LLM output, walks the tree, and plucks any keys matching model field names (including `_text` aliases).

**Rationale**: Small/local LLMs (Mistral, etc.) often wrap the required JSON fields under extra objects, add unexpected wrapper keys, or rename fields. Rather than failing the entire graph, we attempt recovery. The method validates the recovered data against the Pydantic model, so invalid data is still rejected.

**Alternatives considered**:
- Retry with stronger format instructions: Rejected — adds latency and cost for a problem that's inherent to smaller models.
- Use function calling / tool use: Rejected — not all LLM providers support this, and the PromptGraph engine must be provider-agnostic.

### D4: Unwrap LLMPort adapter to get BaseChatModel

**Decision**: `runnable_llm = getattr(llm, "_llm", None) or llm`

**Rationale**: The LCEL pipe operator (`prompt | llm | parser`) requires a LangChain `Runnable`. Our `LangChainLLMAdapter` implements `LLMPort` (a Protocol) but wraps a `BaseChatModel`. The pipe operator fails on the Protocol object. Unwrapping via `_llm` gives us the underlying Runnable while maintaining the port abstraction at the plugin level.

### D5: Wrap special nodes for dict state

**Decision**: `_wrap_special_node` converts Pydantic model state to dict before calling user-supplied node functions.

**Rationale**: When `StateGraph` is compiled with a Pydantic model schema, LangGraph passes model instances to nodes. Plugin code (like the expert's `retrieve_node`) was written against dict state with `state.get(...)`. Rather than changing all plugin code, we normalize at the boundary.

### D6: Return `combined_knowledge_docs` from retrieve

**Decision**: Changed from `{"knowledge": ..., "sources": ...}` to `{"combined_knowledge_docs": knowledge}`.

**Rationale**: The prompt graph's state schema defines `combined_knowledge_docs` as the field that the `answer_question` node reads. Returning `knowledge` meant the data was dropped on state merge (unrecognized key). Returning `sources` (a QueryResult object) also failed because it's not in the schema. The correct key is `combined_knowledge_docs`.

### D7: Build conversation from event history

**Decision**: Construct `messages` list and `conversation` string from `event.history` entries.

**Rationale**: The graph's `check_input` node uses the `conversation` variable to detect follow-ups and rephrase questions. Previously, `conversation` was set to empty string and `messages` to empty list, making multi-turn conversations impossible.
