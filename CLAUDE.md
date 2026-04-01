# virtual-contributor Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-02

## Active Technologies
- Python 3.12 + langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langchain-anthropic (NEW — to add), langgraph ^1.0.4, pydantic ^2.11, pydantic-settings ^2.11.0, aio-pika 9.5.7 (002-multi-provider-llm)
- ChromaDB (vector store via chromadb-client ^1.5.0), RabbitMQ (message transport) (002-multi-provider-llm)
- Python 3.12 + langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, httpx ^0.27.2, aio-pika 9.5.7, chromadb-client ^1.5.0, beautifulsoup4 ^4.14 (003-async-perf-optimize)
- ChromaDB (vector store), RabbitMQ (message transport) (003-async-perf-optimize)

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
- 003-async-perf-optimize: Added Python 3.12 + langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, httpx ^0.27.2, aio-pika 9.5.7, chromadb-client ^1.5.0, beautifulsoup4 ^4.14
- 002-multi-provider-llm: Added Python 3.12 + langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langchain-anthropic (NEW — to add), langgraph ^1.0.4, pydantic ^2.11, pydantic-settings ^2.11.0, aio-pika 9.5.7

- 001-microkernel-engine-impl: Unified microkernel engine with 6 plugins, hexagonal architecture

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
