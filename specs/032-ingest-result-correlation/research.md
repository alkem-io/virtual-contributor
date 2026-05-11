# Research: Ingest Website Result Correlation Fields

**Feature Branch**: `032-ingest-result-correlation`
**Date**: 2026-04-30

## Decisions

### D1 — Add identification fields directly to `IngestWebsiteResult` rather than wrapping the result

**Decision**: Extend the existing `IngestWebsiteResult` Pydantic model with four new fields (`body_of_knowledge_id`, `type`, `purpose`, `persona_id`).

**Rationale**: The result envelope is the wire contract with the alkemio-server. Wrapping the result in an outer correlation object would force a coordinated server release and break every existing consumer. Adding fields directly is purely additive — old consumers ignore the new fields, new consumers read them.

**Alternatives considered**:
- *Wrapper envelope* (`{correlation: {...}, result: {...}}`): rejected — breaking change requiring coordinated server release.
- *Correlation in RabbitMQ message headers*: rejected — separates correlation data from the payload, requires server-side header parsing, and breaks the principle that the event body is self-describing.
- *Server keeps a request → result correlation map keyed by message ID*: rejected — adds stateful complexity to the server for what is fundamentally a request/response shape.

### D2 — Default each new field to empty string

**Decision**: All four fields default to `""` rather than `None` or being required.

**Rationale**: Empty-string default makes the model constructible with no arguments, which keeps the existing call sites (and tests) working without migration. It also produces a stable wire format: the field is always present in the JSON payload, never `null` and never absent, which is the simplest contract for the server to consume. Using `None` (with `Optional[str]`) would force every consumer to handle null, and using a required field would break any caller that doesn't yet pass the value.

**Alternatives considered**:
- *Required fields with no default*: rejected — breaks existing call sites and any future caller that doesn't have the value.
- *Optional with `None` default*: rejected — introduces null-handling on the consumer side for no benefit.

### D3 — `body_of_knowledge_id` defaults to empty string for the website plugin

**Decision**: The website ingest plugin does not populate `body_of_knowledge_id` — the field is left as its empty-string default in every emitted result.

**Rationale**: Websites are identified by their base URL, not by a UUID body-of-knowledge ID. The field is included on the schema so the result envelope is consistent with other ingest result types (and so a future change can populate it without further schema work). Populating it with the URL would conflate two different identifier semantics on the server side.

**Alternatives considered**:
- *Populate with the base URL*: rejected — different semantic from a UUID-keyed body-of-knowledge ID; would mislead the server.
- *Omit the field for the website plugin*: rejected — schema parity across ingest result types is more valuable than the small saving of one field.

### D4 — camelCase aliases for `bodyOfKnowledgeId` and `personaId`, plain names for `type` and `purpose`

**Decision**: Use Pydantic `Field(alias="...")` for the multi-word fields; leave single-word `type` and `purpose` aliasless.

**Rationale**: The wire format is camelCase per the constitution's "Event Schema as Wire Contract" standard. Single-word fields are the same in both snake_case and camelCase, so no alias is needed. This matches the existing pattern in the same file (e.g., `IngestWebsite.base_url` aliased to `baseUrl`, but no aliases on the equally-positional `type` and `purpose`).

**Alternatives considered**:
- *Aliases on every field for consistency*: rejected — adds noise without changing wire format.
- *Rename `type` and `purpose` to camelCase via Pydantic config*: rejected — they are already correct on the wire.

### D5 — Propagate fields at every return site in the plugin handler

**Decision**: Three return statements in `IngestWebsitePlugin.handle` (cleanup-only path, normal success/failure path, exception path) each construct `IngestWebsiteResult(...)` with `type=event.type, purpose=event.purpose, persona_id=event.persona_id` explicitly.

**Rationale**: The handler has three independent return sites, each constructing its own `IngestWebsiteResult`. Centralising the construction in a helper would add indirection for what is three lines of identical kwargs. Tests cover all three sites by exercising the cleanup path (`test_empty_crawl_runs_cleanup`) and the normal path (`test_pipeline_composition`); the exception path is covered indirectly by the same construction pattern.

**Alternatives considered**:
- *Helper `_build_result(event, ...)` method*: rejected — premature abstraction over three call sites; adds indirection without simplifying the code.
- *Post-handle middleware that copies fields onto every result*: rejected — pulls into the core a concern that belongs to the plugin; violates plugin-isolation and would touch the router.

### D6 — Tests assert camelCase aliases in serialised output, not just attribute access

**Decision**: `tests/core/test_events.py` calls `model_dump(...)` and inspects the resulting dict for the camelCase keys (`bodyOfKnowledgeId`, `personaId`).

**Rationale**: The wire contract is the JSON output, not the Python attribute names. Asserting on the dict keys catches alias regressions that attribute-only tests would miss.

**Alternatives considered**:
- *Test only attribute access (`result.persona_id == "..."`)*: rejected — would not catch a missing alias that breaks the wire contract.

## Summary Table

| ID | Decision | Reason in one line |
|----|----------|--------------------|
| D1 | Add fields directly to result model | Additive change; no coordinated release |
| D2 | Empty-string default | Stable wire format, no migration |
| D3 | `bodyOfKnowledgeId` reserved but unpopulated | Schema parity; URL is not a UUID |
| D4 | Aliases only where snake → camel differs | Match existing repo convention |
| D5 | Inline kwargs at all three return sites | No abstraction needed for three call sites |
| D6 | Assert camelCase keys in dumped dict | Wire format is the dict, not the attribute |
