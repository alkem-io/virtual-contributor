# Feature Specification: Configurable Vector DB Distance Function

**Feature Branch**: `develop`
**Created**: 2026-04-08
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure Vector Similarity Distance Metric (Priority: P1)

As a platform operator, I want to configure the distance function used by the vector database for similarity search so that I can optimize retrieval quality for different embedding models without code changes.

**Why this priority**: Different embedding models produce vectors optimized for different distance metrics. Using cosine distance with an L2-optimized embedding model (or vice versa) degrades retrieval quality. This is the only change in this spec and directly impacts answer quality.

**Independent Test**: Set `VECTOR_DB_DISTANCE_FN=l2`, restart the service, ingest content, and verify that ChromaDB collections are created with `hnsw:space=l2` metadata. Query results should reflect L2 distance scoring instead of cosine.

**Acceptance Scenarios**:

1. **Given** `VECTOR_DB_DISTANCE_FN=cosine` (or unset), **When** any ChromaDB operation creates or accesses a collection, **Then** the collection uses cosine distance (default, backward-compatible behavior).
2. **Given** `VECTOR_DB_DISTANCE_FN=l2`, **When** a collection is created or accessed, **Then** the collection uses L2 (Euclidean) distance.
3. **Given** `VECTOR_DB_DISTANCE_FN=ip`, **When** a collection is created or accessed, **Then** the collection uses inner product distance.
4. **Given** `VECTOR_DB_DISTANCE_FN=hamming` (invalid value), **When** the application starts, **Then** configuration validation rejects the value with a clear error message listing valid options.

---

### Edge Cases

- What happens when the distance function is changed after data has already been ingested with a different metric? ChromaDB applies the metadata on `get_or_create_collection`; existing collections retain their original HNSW index. A full re-ingestion is required for the new metric to take effect on existing data.
- What happens when `VECTOR_DB_DISTANCE_FN` is set to an empty string? Pydantic uses the default value `"cosine"` for empty env vars, preserving backward compatibility.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support configuring the ChromaDB distance function via the `VECTOR_DB_DISTANCE_FN` environment variable, accepting values `cosine`, `l2`, or `ip`.
- **FR-002**: System MUST default to `cosine` distance when `VECTOR_DB_DISTANCE_FN` is not set, preserving existing behavior.
- **FR-003**: System MUST validate the distance function value at configuration load time and reject unsupported values with a clear error message.
- **FR-004**: System MUST pass the configured distance function as `hnsw:space` metadata to every `get_or_create_collection` call in the ChromaDB adapter (query, ingest, and get operations).
- **FR-005**: The `.env.example` file MUST document the `VECTOR_DB_DISTANCE_FN` variable with its valid values and default.

### Key Entities

- **Vector DB Distance Configuration**: A string parameter (`cosine`, `l2`, `ip`) that controls the HNSW similarity metric used by ChromaDB collections. Stored in `BaseConfig` and injected into the `ChromaDBAdapter` at construction time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can switch the vector similarity metric by changing a single environment variable, with the change taking effect on the next service restart.
- **SC-002**: Invalid distance function values are caught at startup, preventing misconfigured deployments from running.
- **SC-003**: The default value `cosine` reproduces current system behavior exactly when the variable is unset.

## Assumptions

- ChromaDB's `get_or_create_collection` applies `hnsw:space` metadata correctly when creating new collections.
- Changing the distance function on an existing collection requires re-ingestion; the system does not handle automatic migration.
- The three supported distance functions (`cosine`, `l2`, `ip`) cover the needs of all embedding models currently in use.
