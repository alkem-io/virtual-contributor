# Feature Specification: Consistent Summarization Behavior Between Ingest Plugins

**Feature Branch**: `story/1827-consistent-summarization-behavior`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story alkemio#1827

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Explicit Summarization Toggle (Priority: P1)

As a platform operator, I want a single `SUMMARIZE_ENABLED` flag that controls whether summarization steps are included in the ingest pipeline, so that the system behaves identically for both ingest-website and ingest-space and I have a clear, explicit way to disable summarization.

**Why this priority**: The root cause of the inconsistency is that ingest-website overloaded `summarize_concurrency=0` to mean "skip summarization" while ingest-space always summarized. An explicit boolean toggle is the most direct fix and is the prerequisite for all other changes.

**Independent Test**: Set `SUMMARIZE_ENABLED=false`, run both ingest-website and ingest-space pipelines, and verify that neither includes DocumentSummaryStep or BodyOfKnowledgeSummaryStep. Then set `SUMMARIZE_ENABLED=true` (or leave unset) and verify both include the summary steps.

**Acceptance Scenarios**:

1. **Given** `SUMMARIZE_ENABLED=true` (default) and `SUMMARIZE_CONCURRENCY=8`, **When** ingest-website or ingest-space runs, **Then** both include DocumentSummaryStep and BodyOfKnowledgeSummaryStep with concurrency=8.
2. **Given** `SUMMARIZE_ENABLED=false`, **When** ingest-website or ingest-space runs, **Then** neither includes DocumentSummaryStep or BodyOfKnowledgeSummaryStep.
3. **Given** `SUMMARIZE_ENABLED` is not set, **When** either plugin runs, **Then** it defaults to true and includes summary steps (backward compatible).

---

### User Story 2 -- Concurrency Zero Means Sequential (Priority: P2)

As a platform operator, I want `SUMMARIZE_CONCURRENCY=0` to mean "run summarization sequentially" rather than "skip summarization", so that the concurrency parameter has a single, predictable meaning across both plugins.

**Why this priority**: This resolves the semantic confusion that caused the original bug. Once US1 provides the explicit toggle, concurrency can be purely about parallelism.

**Independent Test**: Set `SUMMARIZE_ENABLED=true` and `SUMMARIZE_CONCURRENCY=0`. Verify that both plugins include DocumentSummaryStep with effective concurrency=1 (sequential).

**Acceptance Scenarios**:

1. **Given** `SUMMARIZE_ENABLED=true` and `SUMMARIZE_CONCURRENCY=0`, **When** either plugin constructs the pipeline, **Then** DocumentSummaryStep is included with concurrency=1.
2. **Given** `SUMMARIZE_CONCURRENCY=5`, **When** either plugin constructs the pipeline, **Then** DocumentSummaryStep uses concurrency=5.
3. **Given** `SUMMARIZE_CONCURRENCY=-1`, **When** config is loaded, **Then** a validation error is raised.

---

### User Story 3 -- Remove Inline Config from Ingest-Website (Priority: P3)

As a developer, I want ingest-website to receive its summarization configuration via constructor injection rather than instantiating `BaseConfig()` inline, so that both ingest plugins follow the same dependency injection pattern and are testable in isolation.

**Why this priority**: This is a code hygiene improvement that enables US1 and US2 to work consistently. It aligns ingest-website with the hexagonal architecture pattern already used by ingest-space.

**Independent Test**: Verify that `from core.config import BaseConfig` is no longer called inside `IngestWebsitePlugin.handle()`. Verify that `summarize_enabled` and `summarize_concurrency` are received as constructor parameters.

**Acceptance Scenarios**:

1. **Given** the IngestWebsitePlugin class, **When** inspecting its constructor, **Then** it accepts `summarize_enabled: bool` and `summarize_concurrency: int` parameters.
2. **Given** the IngestWebsitePlugin.handle() method, **When** inspecting its imports, **Then** it does not import or instantiate `BaseConfig`.
3. **Given** `main.py` wires the plugin, **When** `summarize_enabled` and `summarize_concurrency` are in the constructor signature, **Then** `main.py` injects both values from the global config.

---

### Edge Cases

- When `SUMMARIZE_ENABLED` is not set, the default value `true` preserves current ingest-space behavior and fixes ingest-website.
- When `SUMMARIZE_CONCURRENCY=0` and `SUMMARIZE_ENABLED=true`, effective concurrency is `max(1, 0) = 1`, ensuring sequential execution rather than disabling.
- When `SUMMARIZE_CONCURRENCY` is negative, Pydantic validation rejects the config at startup with a clear error message.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a `SUMMARIZE_ENABLED` boolean config field (default `true`) that controls whether summarization steps are included in ingest pipelines.
- **FR-002**: Both ingest-website and ingest-space MUST honor `SUMMARIZE_ENABLED` identically: when true, include DocumentSummaryStep and BodyOfKnowledgeSummaryStep; when false, skip both.
- **FR-003**: System MUST treat `SUMMARIZE_CONCURRENCY=0` as sequential execution (effective concurrency=1), not as a summarization disable toggle.
- **FR-004**: System MUST validate that `SUMMARIZE_CONCURRENCY >= 0` at config load time, rejecting negative values.
- **FR-005**: IngestWebsitePlugin MUST receive `summarize_enabled` and `summarize_concurrency` via constructor injection, not via inline `BaseConfig()` instantiation.
- **FR-006**: `main.py` MUST inject `summarize_enabled` and `summarize_concurrency` into any plugin whose constructor accepts those parameters, following the existing `chunk_threshold` injection pattern.

### Key Entities

- **summarize_enabled**: A boolean config field on `BaseConfig` controlling whether summarization pipeline steps are included.
- **summarize_concurrency**: An existing integer config field whose value `0` now maps to effective concurrency `1` (sequential) rather than disabling summarization.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Both ingest-website and ingest-space produce identical pipeline step compositions for the same `summarize_enabled` and `summarize_concurrency` values.
- **SC-002**: Existing deployments without `SUMMARIZE_ENABLED` set behave identically to current ingest-space behavior (summarization always runs).
- **SC-003**: The `summarize_concurrency` parameter has a single, unambiguous meaning: parallel summarization concurrency level.
- **SC-004**: All three scenarios (enabled+concurrent, enabled+sequential, disabled) are tested for both plugins.

## Assumptions

- Existing deployments do not intentionally rely on `summarize_concurrency=0` to disable summarization in ingest-website. If they do, they must switch to `SUMMARIZE_ENABLED=false`.
- The `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` are always added or removed together; there is no use case for including one without the other.
- The `IngestEngine` and `PipelineStep` protocol are not modified; changes are confined to plugin pipeline construction.
