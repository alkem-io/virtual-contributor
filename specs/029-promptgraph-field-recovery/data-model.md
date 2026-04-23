# Data Model: PromptGraph Field Recovery

**Feature Branch**: `029-promptgraph-field-recovery`
**Date**: 2026-04-23

## No New Pydantic Models

This feature modifies the internal recovery behavior of `PromptGraph._recover_fields`. No new Pydantic models, event schemas, or persistent data structures are introduced.

## Default Mapping Table

The new `_default_for_annotation` static method maps Python type annotations to fill-in defaults for missing required fields:

| Annotation | Default Value | Rationale |
|---|---|---|
| `str` | `""` | Empty string passes str validation; safe for text fields |
| `bool` | `False` | Conservative boolean default |
| `int` | `0` | Numeric zero-value |
| `float` | `0` | Numeric zero-value |
| `list` / `list[T]` | `[]` | Empty collection |
| `dict` / `dict[K, V]` | `{}` | Empty mapping |
| `BaseModel` subclass | `{}` | Pydantic coerces to nested model using its own field defaults |
| `Optional[X]` / `X \| None` | Default of `X` | Unwrapped to inner type before lookup |
| Unknown / unrecognized | `None` | Fallback; may cause validation failure for non-optional fields |

## Behavior Change in `_recover_fields`

**Before**: If any required field was missing after the JSON walk, `_recover_fields` returned `None`, discarding the entire recovery attempt.

**After**: Missing required fields are filled with type-appropriate defaults from the table above. A WARNING log lists the filled field names. `model_validate` is then attempted with the filled data. If validation still fails (e.g., a custom validator rejects the default), `_recover_fields` returns `None` as before.

The change is localized to the `missing_required` handling block in `_recover_fields` (lines 150-170 of `core/domain/prompt_graph.py`).
