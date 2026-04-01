# ADR 0001: Microkernel + Hexagonal Architecture

## Status
Accepted

## Context
Seven standalone repositories (engine-expert, engine-generic, engine-guidance, engine-openai-assistant, ingest-website, ingest-space, and the base engine library) share significant code duplication in RabbitMQ transport, configuration, and LLM orchestration. Each repository maintains its own CI/CD pipeline, resulting in 28 workflow files.

## Decision
Adopt a **Microkernel Architecture** with **Hexagonal (Ports and Adapters)** internal structure:

- **Core system** (`core/`): Plugin registry, content-based router, IoC container, event schemas, and domain logic (ingest pipeline, PromptGraph, summarization).
- **Plugin components** (`plugins/`): Six plugins implementing `PluginContract` protocol — each handles one event type with domain-specific logic.
- **Port interfaces** (`core/ports/`): Technology-agnostic protocols (LLMPort, EmbeddingsPort, KnowledgeStorePort, TransportPort).
- **Adapter implementations** (`core/adapters/`): Concrete implementations (Mistral, OpenAI, ChromaDB, RabbitMQ, Scaleway).

## Consequences
- **Positive**: Single codebase, shared infrastructure, consistent testing, ~5 CI workflows instead of 28.
- **Positive**: Plugins can be developed and tested independently with mock ports.
- **Positive**: New plugins require zero core code changes (validated by echo plugin integration test).
- **Negative**: All plugins share the same dependency set, increasing image size.
- **Negative**: A core bug can affect all plugins simultaneously.
