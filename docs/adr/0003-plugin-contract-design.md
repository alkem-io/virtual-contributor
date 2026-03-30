# ADR 0003: Plugin Contract Design

## Status
Accepted

## Context
The microkernel architecture requires a stable interface between the core system and plugin components. The contract must support diverse plugin types (engine queries, website ingestion, space ingestion) with different event models and port dependencies.

## Decision
Use a Python `Protocol` class (`PluginContract`) with:
- `name: str` — unique plugin identifier
- `event_type: type` — Pydantic model class the plugin handles
- `async startup()` — resource initialization after dependency injection
- `async shutdown()` — graceful teardown
- `async handle(event, **ports)` — process a single event and return a response

Port dependencies are declared via constructor parameters and resolved by the IoC container using type hints introspection (`typing.get_type_hints`).

## Consequences
- **Positive**: Runtime-checkable protocol enables duck typing — plugins don't need to inherit from a base class.
- **Positive**: Constructor injection makes dependencies explicit and testable.
- **Positive**: Lifecycle methods (startup/shutdown) support async resource management.
- **Negative**: Protocol checking doesn't validate method signatures at import time — only at runtime.
