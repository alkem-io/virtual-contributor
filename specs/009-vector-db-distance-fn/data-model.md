# Data Model: Configurable Vector DB Distance Function

**Feature Branch**: `develop`
**Date**: 2026-04-08

## Entity: BaseConfig (modified)

**File**: `core/config.py`

### New Field

| Field | Type | Default | Env Var | Validation | Description |
|-------|------|---------|---------|------------|-------------|
| `vector_db_distance_fn` | `str` | `"cosine"` | `VECTOR_DB_DISTANCE_FN` | Must be one of `{"cosine", "l2", "ip"}` | Distance metric for ChromaDB HNSW index |

### Validation Rule

In `model_validator`: if `vector_db_distance_fn` is not in `{"cosine", "l2", "ip"}`, raise `ValueError` with the invalid value and the set of valid options.

## Entity: ChromaDBAdapter (modified)

**File**: `core/adapters/chromadb.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `distance_fn` | `str` | `"cosine"` | Distance metric passed as `hnsw:space` metadata to all collection operations |

### Changed Behavior

All `get_or_create_collection` calls now include `metadata={"hnsw:space": self._distance_fn}`:
- `query()` — collection access for similarity search
- `ingest()` — collection access for upserting documents
- `get()` — collection access for retrieving documents by ID/filter

The `delete()` method is unchanged (does not use `get_or_create_collection` with metadata).

## Relationships

```text
BaseConfig
  └── injects → ChromaDBAdapter(distance_fn=config.vector_db_distance_fn)
          └── passes → get_or_create_collection(metadata={"hnsw:space": distance_fn})
```

## State Transitions

No state machines affected. Configuration is applied at startup.
