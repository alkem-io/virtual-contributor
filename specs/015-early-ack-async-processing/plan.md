# Implementation Plan: Early ACK with Async Processing

**Branch**: `story/1824-early-ack-async-processing` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/015-early-ack-async-processing/spec.md`

## Summary

Decouple RabbitMQ message acknowledgment from pipeline completion to eliminate `consumer_timeout` redelivery loops. Ingest messages are ACKed immediately after schema validation, then processed asynchronously as fire-and-forget tasks. An outer pipeline timeout wraps all `plugin.handle()` calls regardless of event type. Engine queries retain the existing late-ACK + retry pattern. Graceful shutdown awaits in-flight tasks.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: aio-pika 9.5.7, pydantic-settings ^2.11.0
**Storage**: N/A (no storage changes)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: Eliminate infinite redelivery loops; 30-minute `consumer_timeout` is safe again
**Constraints**: No changes to `TransportPort`, `PluginContract`, or plugin internals
**Scale/Scope**: 3 files modified + 1 new test file, ~120 lines added

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Automated change, no interactive steps |
| P2 | SOLID Architecture | PASS | Open/Closed: new method on adapter, no port changes. SRP: ACK strategy in application layer, not adapter |
| P3 | No Vendor Lock-in | PASS | aio-pika is the existing RabbitMQ client, no new deps |
| P4 | Optimised Feedback Loops | PASS | Config validation catches invalid timeout at startup |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full spec -> plan -> tasks -> implement |
| P7 | No Filling Tests | PASS | Tests verify actual ACK timing and error behavior |
| P8 | ADR | N/A | No new ports, no new external deps |
| AS:Microkernel | Microkernel Architecture | PASS | Change is in main.py (application wiring) and adapter |
| AS:Hexagonal | Hexagonal Boundaries | PASS | TransportPort unchanged |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged |
| AS:Domain | Domain Logic Isolation | PASS | No domain changes |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal change surface; no job tracking system |
| AS:Async | Async-First Design | PASS | Uses asyncio.create_task, asyncio.wait_for |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/015-early-ack-async-processing/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
core/
├── config.py              # Add pipeline_timeout field with validation
└── adapters/
    └── rabbitmq.py        # Add consume_with_message() method

main.py                    # Rewrite on_message: early ACK for ingest, outer timeout,
                           # fire-and-forget task management, graceful shutdown

tests/
├── core/
│   └── test_early_ack.py  # Unit tests for early ACK, timeout, task tracking
└── test_config_pipeline_timeout.py  # Config validation tests
```

## Complexity Tracking

No constitution violations to justify.
