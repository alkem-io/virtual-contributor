# Research: Configurable Vector DB Distance Function

**Feature Branch**: `develop`
**Date**: 2026-04-08

## Research Tasks

### R1: ChromaDB distance function configuration mechanism

**Context**: ChromaDB collections use HNSW indexes for approximate nearest-neighbor search. The distance metric affects how similarity scores are computed.

**Findings**:

ChromaDB supports three distance functions via the `hnsw:space` metadata key on collections:
- `cosine` — cosine similarity (default). Best for normalized embeddings.
- `l2` — Euclidean (L2) distance. Suitable for models that optimize for absolute vector distances.
- `ip` — inner product. Used by some embedding models optimized for dot-product similarity.

The metadata is passed to `get_or_create_collection(name, metadata={"hnsw:space": value})`. For existing collections, the metadata is applied at creation time; subsequent calls with different metadata do not change the index.

**Decision**: Pass `distance_fn` as constructor parameter to `ChromaDBAdapter`, apply to all `get_or_create_collection` calls via metadata.
**Rationale**: Consistent distance metric across all collection operations (query, ingest, get). Constructor injection follows existing adapter patterns.
**Alternatives considered**: (a) Per-collection distance function — rejected (over-engineering, no use case for mixed metrics). (b) Pass through as query parameter — rejected (ChromaDB requires it at collection creation time).

---

### R2: Validation approach for distance function

**Context**: Invalid distance function values would cause silent ChromaDB errors or unexpected behavior.

**Findings**:

Using a set-based validation in the pydantic `model_validator` is consistent with how other config fields are validated (e.g., LLM temperature ranges, retrieval score thresholds). A string field with set-membership validation is simpler than introducing an enum, since the valid values are a small fixed set and ChromaDB expects a raw string.

**Decision**: Validate via set membership (`{"cosine", "l2", "ip"}`) in the existing `model_validator`, raising `ValueError` for invalid values.
**Rationale**: Fail-fast at startup. Consistent with existing validation patterns. No new types needed.
**Alternatives considered**: (a) Python `Enum` — rejected (adds a type for 3 strings, ChromaDB expects raw string). (b) Pydantic `Literal["cosine", "l2", "ip"]` — viable but less consistent with existing validator-based pattern.

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Configuration mechanism | Constructor param + collection metadata | Consistent across all operations |
| Validation | Set-membership in model_validator | Fail-fast, consistent pattern |
| Default value | `cosine` | Matches ChromaDB default, backward compatible |
