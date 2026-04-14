# Research: Consistent Summarization Behavior Between Ingest Plugins

**Feature Branch**: `story/1827-consistent-summarization-behavior`
**Date**: 2026-04-14

## Research Tasks

### R1: Root cause of inconsistent summarization behavior

**Context**: ingest-website and ingest-space handle `summarize_concurrency=0` differently. ingest-website treats it as "skip summarization" while ingest-space always includes summarization steps. This leads to silent data-quality regression.

**Findings**:

In `plugins/ingest_website/plugin.py`, the `handle()` method instantiated `BaseConfig()` inline and used `config.summarize_concurrency > 0` as the guard for including summary steps. When `summarize_concurrency=0`, the condition evaluated to `False`, silently skipping all summarization.

In `plugins/ingest_space/plugin.py`, the pipeline was constructed with summary steps unconditionally -- `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` were always included regardless of `summarize_concurrency`.

Additionally, ingest-website instantiated `BaseConfig()` inside the `handle()` method rather than receiving config via constructor injection, which violated the hexagonal architecture pattern used by the rest of the codebase.

**Decision**: Add an explicit `summarize_enabled` boolean flag (default `true`) and reinterpret `concurrency=0` as sequential execution (`max(1, concurrency)`).
**Rationale**: Separating the "should summarize" decision from the "how many in parallel" decision eliminates the semantic overloading that caused the bug. The boolean is explicit and unambiguous.
**Alternatives considered**: (a) Make ingest-website always include summary steps like ingest-space -- rejected (removes the ability to disable summarization when needed). (b) Use `summarize_concurrency=None` to mean "disabled" -- rejected (overly implicit, still overloads a numeric parameter).

---

### R2: Constructor injection pattern for ingest plugins

**Context**: ingest-website instantiated `BaseConfig()` inside `handle()`, while ingest-space received config via constructor injection. This inconsistency made ingest-website harder to test and violated the Dependency Inversion principle.

**Findings**:

The existing pattern in `main.py` already supports constructor injection for ingest plugins. The `_run()` function inspects the plugin class constructor signature and injects matching dependencies. The `chunk_threshold` parameter is already injected this way:

```python
if "chunk_threshold" in sig.parameters:
    deps["chunk_threshold"] = config.summary_chunk_threshold
```

Adding `summarize_enabled` and `summarize_concurrency` follows the exact same pattern. The plugin constructor declares the parameter with a default, `main.py` checks if it's in the signature, and injects the config value.

**Decision**: Use the existing `sig.parameters` pattern in `main.py` to inject `summarize_enabled` and `summarize_concurrency` into any plugin that accepts them.
**Rationale**: Zero new patterns introduced. Consistent with existing code. Removes the inline `BaseConfig()` dependency from ingest-website.
**Alternatives considered**: (a) Pass entire config object to plugins -- rejected (violates Interface Segregation; plugins should receive only what they need). (b) Add a shared base class for ingest plugins -- rejected (the project uses duck-typed protocols, not inheritance).

---

### R3: Concurrency zero semantics

**Context**: The `DocumentSummaryStep` accepts a `concurrency` parameter. What should `concurrency=0` mean?

**Findings**:

The `DocumentSummaryStep` uses the concurrency parameter to control parallel summarization. A value of 0 is semantically ambiguous -- it could mean "no summarization" or "run without parallelism." Since the step already loops sequentially by default, mapping 0 to 1 preserves the interface contract while preventing the step from being incorrectly skipped.

The mapping `max(1, summarize_concurrency)` is applied in the plugin constructor, so the step always receives a positive integer. This is done at plugin construction time, not at each `handle()` invocation.

**Decision**: Map `concurrency=0` to `concurrency=1` using `max(1, summarize_concurrency)` in the plugin constructor.
**Rationale**: Aligns with the issue's proposal. Sequential execution is a valid concurrency mode. The explicit `summarize_enabled` flag (R1) handles the disable case.
**Alternatives considered**: (a) Raise an error for concurrency=0 -- rejected (0 is a reasonable value meaning "sequential"). (b) Map in main.py instead of plugin constructor -- rejected (the mapping is a plugin concern, and the constructor default should be self-documenting).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Summarization toggle | Add `summarize_enabled: bool = True` to BaseConfig | Explicit, unambiguous control |
| Concurrency semantics | `max(1, concurrency)` in plugin constructor | 0 means sequential, not disabled |
| Config injection | `sig.parameters` pattern in main.py | Consistent with existing `chunk_threshold` injection |
| Inline config removal | Remove `BaseConfig()` from ingest-website handle() | Hexagonal compliance, testability |
| Concurrency validation | Reject negative values at config load | Nonsensical value caught early |
