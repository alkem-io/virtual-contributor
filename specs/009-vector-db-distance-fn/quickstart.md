# Quickstart: Configurable Vector DB Distance Function

**Feature Branch**: `develop`
**Date**: 2026-04-08

## What This Feature Does

Adds a `VECTOR_DB_DISTANCE_FN` environment variable to configure the distance metric used by ChromaDB for vector similarity search. Supported values: `cosine` (default), `l2`, `ip`.

## New Environment Variables

```env
# Distance function for vector similarity: cosine, l2, or ip
VECTOR_DB_DISTANCE_FN=cosine
```

## Quick Verification

### 1. Verify default behavior (cosine)

```bash
# Start without setting VECTOR_DB_DISTANCE_FN (or set to cosine)
export PLUGIN_TYPE=expert
poetry run python main.py

# Collections will use cosine distance — identical to previous behavior
```

### 2. Verify L2 distance

```bash
export VECTOR_DB_DISTANCE_FN=l2
export PLUGIN_TYPE=ingest-website
poetry run python main.py

# Ingest content — collections created with hnsw:space=l2
```

### 3. Verify invalid value rejection

```bash
export VECTOR_DB_DISTANCE_FN=hamming
poetry run python main.py

# Expected: startup failure with error:
# ValueError: VECTOR_DB_DISTANCE_FN must be one of {'cosine', 'l2', 'ip'}, got 'hamming'
```

## Files Changed

| File | Change |
|------|--------|
| `core/config.py` | Add `vector_db_distance_fn` field with validation |
| `core/adapters/chromadb.py` | Accept `distance_fn` param, pass to collection metadata |
| `main.py` | Pass `distance_fn` from config to ChromaDBAdapter |
| `.env.example` | Document `VECTOR_DB_DISTANCE_FN` |

## Contracts

No external interface changes. `KnowledgeStorePort` is unchanged. This is an adapter-internal configuration change.
