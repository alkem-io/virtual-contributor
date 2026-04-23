# Research: PromptGraph Field Recovery

**Feature Branch**: `029-promptgraph-field-recovery`
**Date**: 2026-04-23

## Decision Summary

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Fill missing fields with type-appropriate defaults vs. return None | Preserves valid responses when only auxiliary fields are missing |
| D2 | Type-based defaults vs. generic None | Non-optional fields reject None; type-aware defaults pass Pydantic validation |
| D3 | Unwrap Optional before selecting default | Optional[str] should default to "" not None, since the field was required |
| D4 | Log warning vs. silent filling | Provides observability for model quality without blocking the response |
| D5 | Static method on PromptGraph vs. standalone function | Co-locates with the only caller; avoids module-level function clutter |

## Decisions

### D1: Fill missing required fields with type-appropriate defaults

**Decision**: When `_recover_fields` finds some but not all required fields in the LLM output, fill the missing ones with type-appropriate defaults and proceed with validation.

**Rationale**: The previous behavior returned `None` when any required field was missing, discarding the entire response -- including correctly extracted primary fields. This was triggered in production by Mistral-Small dropping the `answer_language` field while correctly providing `knowledge_answer` and `source_scores`. The user received an error for what was a valid answer.

**Alternatives considered**:
- Return None (previous behavior): Rejected because it kills valid responses over cosmetic fields.
- Fill all missing fields with None: Rejected because Pydantic rejects None for non-optional required fields like `str` or `int`.
- Make all fields optional in the schema: Rejected because that weakens the schema contract for well-behaved LLMs and shifts the problem downstream.

### D2: Type-based defaults instead of generic None

**Decision**: Map each Python type annotation to a sensible zero-value: `""` for str, `False` for bool, `0` for int/float, `[]` for list, `{}` for dict and BaseModel.

**Rationale**: Pydantic v2 strictly validates field types. A `str` field receiving `None` raises `ValidationError`. Each type has a natural "empty" or "zero" value that passes validation and is semantically safe for auxiliary fields (e.g., empty string for a language hint, empty dict for source scores).

**Alternatives considered**:
- Use `field.default` from the model: Rejected because these are *required* fields -- they have no default.
- Use `field.default_factory`: Same problem -- required fields don't have factories.

### D3: Unwrap Optional[X] / Union[X, None] before selecting default

**Decision**: If the annotation is `Optional[str]` (i.e., `Union[str, None]`), extract `str` and return its default (`""`).

**Rationale**: A required field can be typed as `Optional[str]` in Pydantic v2 (meaning it accepts None but has no default). Since we are filling in for a missing *required* field, we want the most useful value -- the unwrapped type's zero-value -- rather than None. This also handles Python 3.10+ `str | None` union syntax via `types.UnionType`.

### D4: Log a warning when defaults are applied

**Decision**: Emit a WARNING-level log listing the field names filled with defaults.

**Rationale**: Silent filling would mask LLM quality issues. Operators need to know which models are dropping fields to tune prompts or switch providers. WARNING level is appropriate because the response still flows (no data loss) but the behavior is unexpected and actionable.

**Alternatives considered**:
- DEBUG level: Rejected because this is actionable operational information, not diagnostic noise.
- ERROR level: Rejected because the response is successfully recovered -- it is not an error.
- No logging: Rejected because it makes model regression invisible.

### D5: Static method placement on PromptGraph

**Decision**: `_default_for_annotation` is a `@staticmethod` on the `PromptGraph` class.

**Rationale**: Its only caller is `_recover_fields`, also a static method on `PromptGraph`. Co-locating keeps the recovery logic self-contained. A module-level utility function would be equally valid but adds no benefit and separates related logic.
