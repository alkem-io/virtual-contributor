# virtual-contributor Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-30

## Active Technologies

- Python 3.12 + aio-pika 9.5.7, pydantic ^2.11, langchain ^1.1.0 + langgraph ^1.0.4, openai ^1.109, chromadb-client ^1.5.0, httpx ^0.27.2, beautifulsoup4 ^4.14

## Project Structure

```text
core/
plugins/
tests/
```

## Commands

```bash
poetry run pytest                          # Run tests
poetry run ruff check core/ plugins/ tests/  # Lint
poetry run pyright core/ plugins/           # Type check
```

## Code Style

Python 3.12: Follow standard conventions

## Recent Changes

- 001-microkernel-engine-impl: Unified microkernel engine with 6 plugins, hexagonal architecture

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
