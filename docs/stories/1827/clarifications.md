# Clarifications: Story #1827

## Iteration 1

### Q1: What does `summarize_concurrency=0` mean?
**Answer:** Sequential execution (mapped to concurrency=1).
**Rationale:** The DocumentSummaryStep accepts a concurrency parameter but currently loops sequentially. Mapping 0 to 1 preserves the interface contract while preventing the step from being skipped. This aligns with the issue's proposal.

### Q2: Should `summarize_enabled` be per-plugin or global?
**Answer:** Global, on `BaseConfig`.
**Rationale:** The issue explicitly requests alignment between the two plugins. A single global flag is simpler and sufficient. Per-plugin overrides could be added later via env var prefix conventions if needed.

### Q3: Should config validation reject `summarize_concurrency < 0`?
**Answer:** Yes, add validation that `summarize_concurrency >= 0`.
**Rationale:** Negative concurrency is nonsensical. Adding this guard prevents misconfigurations from silently misbehaving.

### Q4: How should plugins access summarize_enabled and concurrency?
**Answer:** Via constructor injection, not inline `BaseConfig()` instantiation.
**Rationale:** ingest-website currently constructs `BaseConfig()` inside `handle()`. This is inconsistent with the DI pattern used elsewhere (e.g., `chunk_threshold`). Both plugins should receive `summarize_enabled` and effective `summarize_concurrency` as constructor parameters, injected by `main.py`. This removes the inline config dependency.

### Q5: Should we remove the inline `BaseConfig()` instantiation from ingest-website?
**Answer:** Yes.
**Rationale:** It breaks the hexagonal architecture principle of not depending on concrete config inside plugin code. The plugin should receive all needed config via its constructor.
