# Plan: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** alkem-io/virtual-contributor#36
**Date:** 2026-04-08

## Architecture

No architectural changes. This is a targeted bug fix within existing pipeline steps.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | `DocumentSummaryStep.execute()` -- add stale summary detection; `BodyOfKnowledgeSummaryStep.execute()` -- add empty-corpus BoK cleanup |
| `tests/core/domain/test_pipeline_steps.py` | Add test cases for both edge cases |

## Data Model Deltas

None. Uses existing `PipelineContext.orphan_ids` set and `PipelineContext.changed_document_ids` set.

## Interface Contracts

No changes. Both steps already conform to the `PipelineStep` protocol. The only change is internal behavior within `execute()`.

## Detailed Design

### 1. DocumentSummaryStep -- Stale summary cleanup

**Location**: `DocumentSummaryStep.execute()`, after computing `chunks_by_doc` and `docs_to_summarize`.

**Logic**: After computing `docs_to_summarize`, iterate over all documents in `chunks_by_doc`. For each document where:
- `context.change_detection_ran` is True
- `doc_id` is in `context.changed_document_ids`
- `len(doc_chunks) < self._chunk_threshold`

Add `f"{doc_id}-summary-0"` to `context.orphan_ids`.

**Rationale**: A changed document that no longer meets the threshold had a prior ingest cycle where it did meet the threshold. Its summary entry `{doc_id}-summary-0` is now stale. Adding it to `orphan_ids` lets the existing `OrphanCleanupStep` handle deletion.

### 2. BodyOfKnowledgeSummaryStep -- Empty corpus cleanup

**Location**: `BodyOfKnowledgeSummaryStep.execute()`, before the early return on empty `seen_doc_ids`.

**Logic**: After computing `seen_doc_ids`, check:
- `not seen_doc_ids` (no content chunks remain)
- `context.removed_document_ids` is non-empty (documents were actively removed)

When both conditions hold, add `"body-of-knowledge-summary-0"` to `context.orphan_ids` and return early.

**Rationale**: When the entire corpus is empty due to removal, the BoK summary is stale. Adding it to orphan_ids lets OrphanCleanupStep handle deletion consistently.

## Test Strategy

| Test | Covers |
|------|--------|
| `test_stale_summary_added_to_orphans` | AC-1: changed doc drops below threshold, summary ID added to orphan_ids |
| `test_no_stale_summary_for_unchanged_doc` | Guard: unchanged doc below threshold does NOT get orphaned |
| `test_no_stale_summary_when_above_threshold` | Guard: changed doc still above threshold does NOT get orphaned |
| `test_empty_corpus_bok_orphaned` | AC-2: all docs removed, BoK summary ID added to orphan_ids |
| `test_non_empty_corpus_bok_not_orphaned` | Guard: partial removal does NOT orphan BoK |
| Existing tests | AC-4: all existing tests still pass |

## Rollout Notes

- No configuration changes.
- No migration needed.
- The fix is purely additive to orphan_ids; OrphanCleanupStep already handles deletion.
- Risk: minimal. The change only adds IDs to the orphan set under very specific conditions.

## Clarifications Applied

1. Stale summary detection only fires when change_detection_ran is True.
2. Only documents in changed_document_ids are candidates for stale summary cleanup.
3. The empty-corpus BoK check is placed before the existing early return on empty seen_doc_ids.
4. Partial removal (some docs removed) does NOT trigger BoK cleanup.
