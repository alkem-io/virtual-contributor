# Data Model: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Feature Branch**: `story/37-pipeline-engine-safety-destructive-step-handling`
**Date**: 2026-04-14

## Overview

This feature does not introduce new database tables, event schemas, or domain entities. All changes are behavioral modifications to existing classes. No data model changes.

## Entity: PipelineStep Protocol (unchanged)

**File**: `core/domain/pipeline/engine.py`

The `PipelineStep` protocol is NOT modified. It retains only:

| Member | Type | Description |
|--------|------|-------------|
| `name` | `property -> str` | Step identifier |
| `execute` | `async method(context: PipelineContext) -> None` | Step execution |

The `destructive` flag is opt-in via duck typing, not a protocol requirement.

## Entity: OrphanCleanupStep (modified)

**File**: `core/domain/pipeline/steps.py`

### New Property

| Property | Type | Value | Description |
|----------|------|-------|-------------|
| `destructive` | `bool` | `True` | Declares this step as destructive for engine-level gating |

### Removed Behavior

- The `if any(e.startswith("StoreStep:") for e in context.errors)` guard and associated error append + early return are removed from `execute()`.

## Entity: IngestEngine (modified behavior)

**File**: `core/domain/pipeline/engine.py`

### New Behavior in `run()`

Before calling `step.execute(context)`, the engine checks:
- `getattr(step, 'destructive', False)` AND `len(context.errors) > 0`
- If both are true: skip execution, log warning, append skip message, record metrics

No new fields or constructor parameters.

## Relationships

```text
IngestEngine.run()
  ├── iterates → [PipelineStep, ...]
  ├── checks → getattr(step, 'destructive', False)
  ├── if destructive + errors → skip + log + metrics
  └── else → step.execute(context)

OrphanCleanupStep
  ├── satisfies → PipelineStep protocol (unchanged)
  └── declares → destructive = True (new, opt-in)
```

## State Transitions

No state machines affected. The destructive gating is a runtime per-step check within the existing sequential execution loop.
