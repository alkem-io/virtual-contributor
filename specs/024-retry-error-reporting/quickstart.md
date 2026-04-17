# Quickstart: Retry Error Reporting

**Feature Branch**: `024-retry-error-reporting`
**Date**: 2026-04-17

## What it does

Changes the engine's error reporting behavior: instead of publishing an error response on every failed handler attempt (spamming the chat), the system now retries silently and only publishes a single error response when all retries are exhausted.

## New Configuration

None. Uses the existing `RABBITMQ_MAX_RETRIES` setting.

## How to verify

1. Set `RABBITMQ_MAX_RETRIES=3` (default).
2. Trigger a query that causes a handler timeout (e.g., set `PIPELINE_TIMEOUT` very low).
3. Observe the RabbitMQ result queue:
   - Retries 1 and 2: no error response published.
   - Retry 3 (final): one error response with "Error: handler timed out after Ns".
4. Check logs for "Message failed (attempt N/3), requeuing" on intermediate attempts.

## Files Changed

| File | Change |
|------|--------|
| `main.py` | Refactored `_retry_or_reject` to accept event/error_text; moved error publishing from except blocks into final-attempt logic |
