# Feature Specification: PromptGraph Field Recovery

**Feature Branch**: `029-promptgraph-field-recovery`
**Created**: 2026-04-23
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Responses Survive When Small LLMs Drop Auxiliary Required Fields (Priority: P1)

As a virtual contributor user querying through a small LLM (e.g. Mistral-Small), when the model produces a correct primary answer but omits an auxiliary required field (e.g. `answer_language`), the system fills the missing field with a safe default and delivers my response instead of silently discarding the entire answer.

**Why this priority**: Small and terse LLMs frequently produce valid structured output for the primary fields but drop auxiliary required fields. Previously, `_recover_fields` returned `None` when any required field was missing, causing the entire response to be lost and the user to receive an error or empty reply for what was an otherwise correct answer.

**Independent Test**: Send a query via a PromptGraph node whose output schema requires `knowledge_answer`, `answer_language`, and `source_scores`. Use Mistral-Small or simulate its behavior by providing JSON with `answer_language` omitted. Verify the response is delivered with `answer_language` set to `""`.

**Acceptance Scenarios**:

1. **Given** an LLM response containing `knowledge_answer` and `source_scores` but missing `answer_language`, **When** `_recover_fields` processes it, **Then** it returns a valid dict with `answer_language` set to `""`.
2. **Given** an LLM response where the only required `str` field is present, **When** no other fields are missing, **Then** `_recover_fields` returns the validated model without any default filling.
3. **Given** an LLM response where all required fields are missing (no recognized keys at all), **When** `_recover_fields` processes it, **Then** it returns `None` (no data to recover).
4. **Given** an LLM response missing a required `bool` field, **When** `_recover_fields` processes it, **Then** the field is filled with `False`.

---

### User Story 2 - Type-Appropriate Defaults for All Common Python Types (Priority: P2)

As a developer defining PromptGraph output schemas, when the recovery mechanism fills a missing field, it uses a sensible type-appropriate default (empty string, zero, empty list, etc.) rather than a generic `None` that would fail Pydantic validation for non-optional fields.

**Why this priority**: Using `None` as a universal fill-in would cause Pydantic validation to reject non-optional `str`, `int`, `bool`, `list`, and `dict` fields. Type-aware defaults ensure the model validates successfully and the response flows through the pipeline.

**Independent Test**: Create Pydantic models with required fields of each supported type (`str`, `bool`, `int`, `float`, `list`, `dict`, nested `BaseModel`, `Optional[str]`). Call `_default_for_annotation` for each and verify the expected default.

**Acceptance Scenarios**:

1. **Given** annotation `str`, **When** `_default_for_annotation` is called, **Then** returns `""`.
2. **Given** annotation `bool`, **When** `_default_for_annotation` is called, **Then** returns `False`.
3. **Given** annotation `int` or `float`, **When** `_default_for_annotation` is called, **Then** returns `0`.
4. **Given** annotation `list` or `list[str]`, **When** `_default_for_annotation` is called, **Then** returns `[]`.
5. **Given** annotation `dict` or `dict[str, int]`, **When** `_default_for_annotation` is called, **Then** returns `{}`.
6. **Given** a nested `BaseModel` subclass, **When** `_default_for_annotation` is called, **Then** returns `{}`.
7. **Given** `Optional[str]` (i.e., `Union[str, None]`), **When** `_default_for_annotation` is called, **Then** unwraps to `str` and returns `""`.
8. **Given** an unknown/unrecognized annotation, **When** `_default_for_annotation` is called, **Then** returns `None`.

---

### User Story 3 - Warning Logging When Defaults Are Applied (Priority: P3)

As a developer monitoring production logs, when `_recover_fields` fills missing required fields with defaults, a warning-level log message is emitted listing the field names that were filled, so I can identify which LLMs are dropping fields and adjust prompts or models accordingly.

**Why this priority**: Silent default-filling would mask model quality issues. Warning logs provide observability without blocking the response.

**Independent Test**: Trigger `_recover_fields` with a missing required field and verify that a WARNING log is emitted containing the field name.

**Acceptance Scenarios**:

1. **Given** `_recover_fields` fills one missing field, **When** the fill occurs, **Then** a WARNING log is emitted with the field name.
2. **Given** `_recover_fields` fills multiple missing fields, **When** the fill occurs, **Then** the WARNING log lists all filled field names sorted alphabetically.
3. **Given** no fields are missing, **When** `_recover_fields` completes, **Then** no warning log is emitted.

---

### Edge Cases

- **All fields missing**: When `_walk` finds zero matching keys in the JSON payload, `_recover_fields` returns `None` before attempting any default filling.
- **Nested BaseModel field**: A required field typed as a `BaseModel` subclass is filled with `{}`, which Pydantic will attempt to coerce into the nested model using its own defaults.
- **Optional unwrapping**: `Optional[str]` is unwrapped to `str` before determining the default, so the default for `Optional[str]` is `""`, not `None`.
- **Null values for required fields**: Null values found during walk are dropped before the fill step, so they do not prevent default filling.
- **Pydantic validation failure after fill**: If the filled defaults still fail Pydantic validation (e.g., a custom validator rejects empty strings), `_recover_fields` returns `None`.

## Requirements

### Functional Requirements

- **FR-001**: `_default_for_annotation` MUST return `""` for `str`, `False` for `bool`, `0` for `int`/`float`, `[]` for `list`, `{}` for `dict`, `{}` for `BaseModel` subclasses, and `None` for unknown types.
- **FR-002**: `_default_for_annotation` MUST unwrap `Optional[X]` / `Union[X, None]` to the inner type before selecting the default.
- **FR-003**: `_recover_fields` MUST fill missing required fields with type-appropriate defaults from `_default_for_annotation` instead of returning `None`.
- **FR-004**: `_recover_fields` MUST emit a WARNING-level log listing all field names that were filled with defaults.
- **FR-005**: `_recover_fields` MUST still return `None` when no recognized fields are found in the JSON payload (the walk finds nothing).
- **FR-006**: `_recover_fields` MUST still return `None` if Pydantic `model_validate` fails after filling defaults.
- **FR-007**: `_default_for_annotation` MUST be a `@staticmethod` on `PromptGraph`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Queries that previously returned errors due to dropped auxiliary fields now deliver valid responses with filled defaults.
- **SC-002**: All 7 new tests pass, covering each type default and the real-world Mistral-Small regression case.
- **SC-003**: Warning logs identify which fields were filled, enabling prompt/model tuning.
- **SC-004**: No existing tests regress.

## Assumptions

- The primary required field (e.g., `knowledge_answer`) is always present in the LLM output; only auxiliary fields are dropped.
- Type-appropriate defaults (empty string, zero, false, empty collections) are acceptable for auxiliary fields in the domain context.
- Pydantic models used as PromptGraph output schemas do not have custom validators that reject empty/zero defaults for auxiliary fields.
- The `model.model_fields` API (Pydantic v2) correctly reports field annotations and required status.
