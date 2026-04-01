# Plugin Contract

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30
**Stability**: Stable — changes require constitution version bump + ADR

## Protocol Definition

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class PluginContract(Protocol):
    """Microkernel: Plugin Contract.

    Each plugin declares its name, the event type it handles,
    and lifecycle + handler methods. Plugins receive port
    dependencies via constructor injection.
    """

    name: str          # Unique plugin identifier (e.g., "expert", "generic")
    event_type: type   # Pydantic model class: Input | IngestWebsite | IngestBodyOfKnowledge

    async def startup(self) -> None:
        """Initialize resources after dependency injection, before message consumption.

        Called once by the core system after the plugin is constructed with
        its port dependencies. Use for: connection warmup, cache priming,
        model loading, or any async initialization.

        Raises on failure — core system will not start consuming messages.
        """
        ...

    async def shutdown(self) -> None:
        """Graceful teardown on SIGTERM/SIGINT.

        Called by the core system during shutdown. Use for: draining
        in-flight work, releasing connections, flushing buffers.

        Must complete within the Kubernetes terminationGracePeriodSeconds.
        """
        ...

    async def handle(self, event, **ports) -> Response:
        """Process a single event and return a response.

        Args:
            event: Deserialized Pydantic model matching self.event_type
            **ports: Injected port instances (e.g., llm=LLMPort, knowledge_store=KnowledgeStorePort)

        Returns:
            Response model with body and optional sources

        Raises:
            Any exception — core system catches, returns error Response,
            and NACKs the message for dead-letter handling.
        """
        ...
```

## Plugin Registration

Plugins are discovered by the registry at startup based on the `PLUGIN_TYPE` environment variable:

1. Core reads `PLUGIN_TYPE` (e.g., `"expert"`)
2. Registry imports `plugins.{plugin_type}.plugin` module
3. Registry finds the class implementing `PluginContract` in that module
4. Core resolves the plugin's port dependencies from the IoC container
5. Core constructs the plugin instance with injected ports
6. Core calls `plugin.startup()`
7. Core starts consuming messages from the plugin's RabbitMQ queue

## Plugin Directory Convention

```
plugins/{plugin_name}/
├── __init__.py
├── plugin.py          # MUST contain exactly one class implementing PluginContract
├── prompts.py         # Optional: prompt templates
└── ...                # Optional: plugin-specific modules
```

## Port Dependency Declaration

Plugins declare their port dependencies via constructor parameters. The IoC container resolves only the ports the plugin requires.

### Example: Expert Plugin

```python
class ExpertPlugin:
    name = "expert"
    event_type = Input

    def __init__(self, llm: LLMPort, knowledge_store: KnowledgeStorePort):
        self._llm = llm
        self._knowledge_store = knowledge_store
```

### Example: Generic Plugin (minimal ports)

```python
class GenericPlugin:
    name = "generic"
    event_type = Input

    def __init__(self, llm: LLMPort):
        self._llm = llm
```

### Example: OpenAI Assistant Plugin (non-standard port)

```python
class OpenAIAssistantPlugin:
    name = "openai-assistant"
    event_type = Input

    def __init__(self, openai_assistant: OpenAIAssistantAdapter):
        self._assistant = openai_assistant
```

## Plugin-to-Port Mapping

| Plugin | LLMPort | EmbeddingsPort | KnowledgeStorePort | OpenAIAssistantAdapter |
|--------|---------|----------------|--------------------|-----------------------|
| expert | Required | - | Required | - |
| generic | Required | - | - | - |
| guidance | Required | - | Required | - |
| openai-assistant | - | - | - | Required |
| ingest-website | Required | Required | Required | - |
| ingest-space | Required | Required | Required | - |

## Adding a New Plugin

Per constitution (SC-006), adding a new plugin requires zero modifications to core code:

1. Create `plugins/{new_name}/` directory
2. Create `plugin.py` with a class implementing `PluginContract`
3. Declare port dependencies via constructor parameters
4. Set `PLUGIN_TYPE={new_name}` at container start
5. The registry discovers and loads the plugin automatically

**Required deliverables for a new plugin** (per constitution Engineering Workflow):
- `plugin.py` implementing `PluginContract`
- At least one meaningful test (Constitution P7)
- Configuration section in README
- Added to CI matrix

## Error Handling Contract

1. **Plugin raises exception during `handle()`**: Core catches the exception, constructs an error `Response(result="Error: {message}", sources=[])`, publishes it to the result queue, and NACKs the original message.
2. **Plugin raises exception during `startup()`**: Core logs the error and exits with non-zero code (fail-fast per FR-023).
3. **Plugin `shutdown()` exceeds timeout**: Core forcefully terminates after Kubernetes `terminationGracePeriodSeconds`.
