# Quickstart: PromptGraph Robustness & Expert Plugin Integration

**Feature Branch**: `023-promptgraph-robustness`
**Date**: 2026-04-17

## What it does

Makes the PromptGraph engine handle real-world Alkemio prompt graph definitions by:
1. **Schema normalization**: Converts the server's list-based property format to standard JSON Schema
2. **Nullable fields**: Widens optional fields to accept LLM null responses
3. **Output recovery**: Attempts to extract expected fields when LLMs produce malformed structured output
4. **State compatibility**: Handles both dict and Pydantic model state throughout the graph
5. **Expert plugin fixes**: Correct state keys, conversation history population, rephrased question retrieval

## New Configuration

None. No new environment variables or settings.

## How to verify

1. Deploy the expert plugin with a prompt graph that uses list-based state schemas (standard Alkemio configuration).
2. Send a query via RabbitMQ and verify the response contains a valid answer (not a schema/parsing error).
3. Send a follow-up question and verify the answer references the conversation context.
4. Check logs for "Structured parse failed ... attempting recovery" messages — these indicate the recovery path is working.

## Files Changed

| File | Change |
|------|--------|
| `core/domain/prompt_graph.py` | Schema normalization, nullable handling, output recovery, state conversion, adapter unwrapping |
| `plugins/expert/plugin.py` | Retrieve node state key fix, conversation history, rephrased question preference |
