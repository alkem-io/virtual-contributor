# Quickstart: PromptGraph Field Recovery

**Feature Branch**: `029-promptgraph-field-recovery`
**Date**: 2026-04-23

## What it does

Improves the PromptGraph's structured output recovery so that missing required fields from small/terse LLMs (e.g., Mistral-Small) are filled with type-appropriate defaults instead of aborting the entire response. Users who previously received errors when an auxiliary field was dropped now receive their answer with the missing field set to a safe default.

## New Configuration

None. No new environment variables, settings, or configuration changes.

## How to verify

1. Deploy with a small LLM (e.g., Mistral-Small) configured as the provider.
2. Send a query through a PromptGraph node whose output schema requires multiple fields (e.g., `knowledge_answer`, `answer_language`, `source_scores`).
3. If the LLM drops an auxiliary field:
   - **Before**: Response lost, user receives error or empty reply.
   - **After**: Response delivered with the missing field set to its type default.
4. Check logs for: `WARNING ... Recovery filled missing required fields with defaults: answer_language`
5. Run the test suite to confirm:
   ```bash
   poetry run pytest tests/core/domain/test_prompt_graph.py -v -k "recover"
   ```

## Files Changed

| File | Change |
|------|--------|
| `core/domain/prompt_graph.py` | Added `_default_for_annotation` static method; updated `_recover_fields` to fill missing required fields with type defaults and log a warning |
| `tests/core/domain/test_prompt_graph.py` | Added 6 new tests: `test_fills_missing_str_with_empty_string`, `test_fills_missing_dict_with_empty_dict`, `test_fills_missing_list_with_empty_list`, `test_fills_missing_bool_with_false`, `test_fills_missing_int_with_zero`, `test_real_world_answer_response_shape` |
