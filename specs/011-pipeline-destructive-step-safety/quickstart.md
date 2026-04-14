# Quickstart: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Feature Branch**: `story/37-pipeline-engine-safety-destructive-step-handling`
**Date**: 2026-04-14

## What This Feature Does

Adds engine-level safety for destructive pipeline steps during ingestion:

1. **Destructive step gating** -- `IngestEngine.run()` automatically skips steps marked `destructive = True` when prior errors exist
2. **OrphanCleanupStep migration** -- Declares itself destructive and removes the fragile string-matching guard

The pipeline is now intrinsically safe: any error in any earlier step prevents destructive operations from running, regardless of error message format.

## Zero Configuration

This feature requires no environment variables, no feature flags, and no configuration changes. It is backward compatible -- existing pipeline behavior is unchanged when all steps succeed.

## Quick Verification

### 1. Run tests

```bash
poetry run pytest tests/core/domain/test_pipeline_steps.py -v -k "destructive"
```

Expected: 9 tests pass (7 new gating tests + 1 property test + 1 updated integration test).

### 2. Verify engine-level gating

When an ingest pipeline encounters an error (e.g., storage write failure), the engine logs:

```text
WARNING: Skipping destructive step 'orphan_cleanup' due to 1 prior error(s)
```

And `IngestResult.errors` contains:

```text
orphan_cleanup: skipped (destructive step gated by 1 prior error(s))
```

### 3. Verify normal operation

When an ingest pipeline succeeds with no errors, `OrphanCleanupStep` runs normally and cleans up orphan chunks.

## Files Changed

| File | Change |
|------|--------|
| `core/domain/pipeline/engine.py` | Add destructive-step gating logic in `IngestEngine.run()` |
| `core/domain/pipeline/steps.py` | Add `destructive` property to `OrphanCleanupStep`; remove string-matching guard |
| `tests/core/domain/test_pipeline_steps.py` | 7 new gating tests, 1 property test, 1 updated integration test |

## Contracts

No external interface changes:
- **PipelineStep protocol**: Unchanged (destructive flag is opt-in via duck typing)
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
- **Port interfaces**: Unchanged
