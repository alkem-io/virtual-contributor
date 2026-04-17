# OpenAI Assistant Plugin

Wraps the OpenAI Assistants API with thread and run management for stateful conversations.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `openai-assistant` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-openai-assistant` |
| **Ports** | `OpenAIAssistantAdapter` |

## How It Works

Manages OpenAI Assistant threads for conversation continuity. Each request creates or resumes a thread, adds the user message, triggers a run, and polls until completion.

```
Input event (with external_config: api_key + assistant_id)
  → Create per-request OpenAI client
  → Resume thread (if thread_id in external_metadata) or create new thread
  → Add user message to thread
  → Create and poll run until completion
  → Extract assistant response
  → Strip OpenAI citation markers
  → Response (with thread_id for session continuity)
```

The `thread_id` is returned in the response metadata, enabling subsequent requests to continue the same conversation.

## Configuration

No environment variables. Configuration is per-request via the event's `external_config`:

| Field | Required | Description |
|-------|----------|-------------|
| `api_key` | Yes | OpenAI API key |
| `assistant_id` | Yes | OpenAI Assistant ID to invoke |

Thread continuity is managed via `external_metadata.thread_id` on the input event.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — thread management, run polling, response extraction |
| `utils.py` | `strip_citations()` helper to remove OpenAI citation markers from responses |

## Testing

```bash
poetry run pytest tests/plugins/test_openai_assistant.py
```
