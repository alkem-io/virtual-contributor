# Data Model: Handle Empty Corpus Re-Ingestion

**Feature Branch**: `story/35-handle-empty-corpus-reingestion-cleanup`
**Date**: 2026-04-14

## Overview

This feature is a bug fix that modifies control flow in two plugin files. No new entities, no new fields, no schema changes.

**No data model changes.** All existing domain models (`Document`, `Chunk`, `DocumentMetadata`, `IngestResult`, `PipelineContext`), event schemas, and port interfaces remain unchanged.

## Entities Affected (behavior only)

### IngestSpacePlugin (behavior change)

**File**: `plugins/ingest_space/plugin.py`

- **Before**: When `read_space_tree()` returns `[]`, the plugin returns `result="success"` immediately with no side effects.
- **After**: When `read_space_tree()` returns `[]`, the plugin runs a cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) to delete all previously stored chunks, then returns success/failure based on cleanup result.

No constructor, field, or interface changes.

### IngestWebsitePlugin (behavior change)

**File**: `plugins/ingest_website/plugin.py`

- **Before**: When crawl+extract produces zero documents, the plugin returns `result=IngestionResult.SUCCESS` with `error="No content extracted"`.
- **After**: When crawl+extract produces zero documents, the plugin runs a cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) to delete all previously stored chunks, then returns success/failure based on cleanup result.

No constructor, field, or interface changes.

## Relationships

No relationship changes. The cleanup pipeline uses the same `KnowledgeStorePort` instance already injected into the plugins.

## State Transitions

No state machine changes. The cleanup pipeline is a one-shot operation within the existing `handle()` event processing flow.
