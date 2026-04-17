# Data Model: PromptGraph Robustness & Expert Plugin Integration

**Feature Branch**: `023-promptgraph-robustness`
**Date**: 2026-04-17

## Modified Entities

### PromptGraph (class)

**File**: `core/domain/prompt_graph.py`

No new data fields. The class gains new static methods that operate on existing data structures:

| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `_normalize_schema` | `dict \| None` | `dict \| None` | Convert list-based properties to JSON Schema dict |
| `_make_nullable` | `dict` | `dict` | Widen property type to accept null |
| `_recover_fields` | `str, type[BaseModel]` | `dict \| None` | Extract model fields from malformed JSON |
| `_state_to_dict` | `any` | `dict` | Convert Pydantic model state to dict |
| `_wrap_special_node` | `Callable` | `Callable` | Wrap node fn for dict state compatibility |

### Schema Normalization Transform

Input (Alkemio format):
```json
{
  "properties": [
    {"name": "field1", "type": "string", "description": "...", "optional": false},
    {"name": "field2", "type": "string", "optional": true}
  ]
}
```

Output (JSON Schema format):
```json
{
  "type": "object",
  "properties": {
    "field1": {"type": "string", "description": "..."},
    "field2": {"type": ["string", "null"], "default": null}
  },
  "required": ["field1"]
}
```

## No Persistent Data Changes

All changes are in-memory transformations during graph compilation and execution. No database, vector store, or file system data models are affected.
