# Research: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Feature Branch**: `develop`
**Date**: 2026-04-08

## Research Tasks

### R1: BoK LLM — three-tier LLM architecture

**Context**: Document summarization and body-of-knowledge summarization have different input size characteristics. Per-document summaries process individual document chunks (small input). BoK summaries aggregate all document summaries (potentially very large input requiring a high-context-window model).

**Findings**:

The existing summarization LLM pattern (synthetic config + `create_llm_adapter`) directly supports adding a third tier. The BoK LLM follows the same creation pattern as the summarize LLM:
1. Check if all 3 required fields are set (provider, model, api_key)
2. Build synthetic config mapping `bok_llm_*` to `llm_*` fields
3. Call `create_llm_adapter()` to create the adapter

The fallback chain in ingest plugins: `self._bok_llm or summary_llm` (where `summary_llm = self._summarize_llm or self._llm`). This gives the 3-tier hierarchy: BoK LLM -> summarize LLM -> main LLM.

**Decision**: Reuse the synthetic-config pattern for BoK LLM. Fallback chain implemented in plugin code.
**Rationale**: Zero factory changes for creation. Consistent with existing summarize LLM pattern. Fallback chain is a simple `or` expression.
**Alternatives considered**: (a) Single "ingest LLM" for both document and BoK — rejected (can't use different context-window models). (b) Configure BoK LLM at the pipeline step level — rejected (would require plumbing config through domain layer, violating Simplicity).

---

### R2: Summarize LLM base URL

**Context**: The summarize LLM was missing `base_url` support, meaning it always inherited the main LLM's endpoint. Operators running local model servers for summarization couldn't point the summarize LLM to a different server.

**Findings**:

The synthetic config approach already supports base URL: just map `summarize_llm_base_url` to `llm_base_url` in the synthetic data dict. The only change needed is adding the config field and the mapping line.

**Decision**: Add `summarize_llm_base_url: str | None = None` to config. Map to `llm_base_url` in synthetic config when set.
**Rationale**: One field, one mapping line. Completes the summarize LLM configuration surface to match main LLM capabilities.
**Alternatives considered**: None — this is the obvious and minimal approach.

---

### R3: disable_thinking for Qwen3 models

**Context**: Qwen3 models (served via vLLM or similar) produce `<think>...</think>` chain-of-thought blocks by default. For summarization tasks, this wastes tokens and pollutes output. The OpenAI-compatible API supports suppressing thinking via `extra_body`.

**Findings**:

The Qwen3 model's thinking mode can be disabled by sending:
```json
{"chat_template_kwargs": {"enable_thinking": false}}
```
via the `extra_body` parameter in the LangChain model constructor kwargs.

This is harmless for models that don't support it — unknown `extra_body` fields are ignored by standard OpenAI-compatible APIs.

**Decision**: Add `disable_thinking: bool = False` parameter to `create_llm_adapter`. When True, inject `extra_body` with `enable_thinking: false`. Apply to summarize and BoK LLM creation (both always pass `disable_thinking=True`).
**Rationale**: Factory-level parameter keeps the concern out of plugin code. Default `False` means no behavioral change for the main LLM.
**Alternatives considered**: (a) Always disable thinking for all LLMs — rejected (main LLM might benefit from thinking in some scenarios). (b) Per-config field `llm_enable_thinking` — rejected (over-engineering; only needed for summarization/BoK models).

---

### R4: Mistral-only httpx keep-alive disabling

**Context**: The factory previously disabled httpx keep-alive for ALL providers when `base_url` was set. This was incorrect: only `ChatMistralAI` uses an httpx-based `async_client`. `ChatOpenAI` uses a different client that doesn't have the same stale-connection issue.

**Findings**:

1. `ChatMistralAI` creates an internal `httpx.AsyncClient` as `self.async_client`. When connecting to local servers, stale keep-alive connections cause timeouts.
2. `ChatOpenAI` creates an `openai.AsyncOpenAI` client, not a raw httpx client. Attempting to replace it with an `httpx.AsyncClient` causes errors.
3. The previous `hasattr(llm, "async_client") and llm.async_client` check was too loose: `ChatOpenAI` also has an `async_client` attribute (the `openai.AsyncOpenAI` instance), but it doesn't have a `headers` attribute compatible with httpx.

**Decision**: Guard with `provider == LLMProvider.mistral` AND `hasattr(llm.async_client, "headers")`.
**Rationale**: Provider check prevents incorrect patching. The `headers` attribute check is a secondary safety net confirming the client is actually httpx-based.
**Alternatives considered**: (a) Only provider check — viable but less safe. (b) Try/except around the patching — rejected (masks real errors).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| BoK LLM creation | Synthetic config + create_llm_adapter | Consistent with summarize LLM pattern |
| BoK fallback chain | bok_llm or summarize_llm or main_llm | Simple `or` expression in plugin |
| Summarize base URL | New config field + synthetic mapping | Completes summarize LLM config surface |
| disable_thinking | Factory parameter, default False | Suppresses Qwen3 CoT for summarization |
| Mistral keepalive | Provider guard + hasattr(headers) | Prevents incorrect patching of non-Mistral clients |
