# ADR 0002: TypeScript-to-Python Port for ingest-space

## Status
Accepted

## Context
The ingest-space service is the only TypeScript/Node.js service among 7 repositories. It uses `@alkemio/client-lib`, `amqplib`, and npm file parsers (pdf-parse, mammoth, xlsx). Maintaining a separate language ecosystem prevents code sharing with the other 6 Python services and requires separate CI/CD infrastructure.

## Decision
Port ingest-space from TypeScript to Python, replacing:
- `@alkemio/client-lib` → `httpx` + manual GraphQL queries with Kratos authentication
- `amqplib` → `aio-pika` (shared transport adapter)
- `pdf-parse` → `pypdf`
- `mammoth` → `python-docx`
- `xlsx` → `openpyxl`
- `@langchain/text-splitters` → `langchain-text-splitters`

The 19.8K LOC of generated GraphQL types are replaced by a lightweight `httpx` GraphQL client.

## Consequences
- **Positive**: Single language ecosystem (Python 3.12) for all 6 plugins.
- **Positive**: Shared ingest pipeline between ingest-space and ingest-website.
- **Positive**: Single Docker image, unified CI/CD.
- **Negative**: One-time porting effort with risk of regression.
- **Mitigation**: Comprehensive tests for GraphQL client, space traversal, and file parsing.
