# Data Model: Unified Microkernel Virtual Contributor Engine

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30
**Verified against**: Source repository code (2026-03-30)

## 1. Event Models (Wire Contract — `core/events/`)

All event models inherit from a `Base(BaseModel)` that uses `populate_by_name=True`, `use_enum_values=True`, and defaults `model_dump()` to `by_alias=True`.

### 1.1 Input Event

The primary message received from the Alkemio platform for engine queries. Deserialized from the `input` key of the RabbitMQ message body.

```
Input
├── engine: str                              # alias: "engine" — LLM engine name
├── operation: InvocationOperation           # alias: "operation" — default: QUERY (enum: "query"|"ingest")
├── user_id: str                             # alias: "userID"
├── message: str                             # alias: "message" — user's question
├── body_of_knowledge_id: str | None         # alias: "bodyOfKnowledgeID"
├── context_id: str                          # alias: "contextID" — default: ""
├── history: list[HistoryItem]               # alias: "history"
├── external_metadata: ExternalMetadata | None  # alias: "externalMetadata"
├── external_config: ExternalConfig | None   # alias: "externalConfig"
├── display_name: str                        # alias: "displayName"
├── description: str                         # alias: "description" — default: ""
├── persona_id: str                          # alias: "personaID"
├── language: str | None                     # alias: "language" — default: "EN"
├── result_handler: ResultHandler            # alias: "resultHandler"
├── prompt: list[str] | None                 # alias: "prompt" — system prompt messages
└── prompt_graph: dict | None                # alias: "promptGraph" — JSON graph definition
```

### 1.2 HistoryItem

```
HistoryItem
├── content: str               # Message text
└── role: MessageSenderRole    # Enum value
```

### 1.3 MessageSenderRole (Enum)

```
MessageSenderRole
├── HUMAN = "human"            # NOTE: "human" not "user"
└── ASSISTANT = "assistant"
```

### 1.4 InvocationOperation (Enum)

```
InvocationOperation
├── QUERY = "query"
└── INGEST = "ingest"
```

### 1.5 ExternalConfig

Per-request configuration override (used by generic and openai-assistant plugins).

```
ExternalConfig
├── api_key: str | None        # alias: "apiKey" — provider API key override
├── assistant_id: str | None   # alias: "assistantId" — OpenAI assistant ID
└── model: str | None          # alias: "model" — LLM model override
```

### 1.6 ExternalMetadata

```
ExternalMetadata
└── thread_id: str | None      # alias: "threadId" — OpenAI thread ID
```

### 1.7 ResultHandler

Determines how the response is delivered back to the platform.

```
ResultHandler
├── action: ResultHandlerAction   # alias: "action" (enum: "postReply"|"postMessage"|"none")
└── room_details: RoomDetails | None  # alias: "roomDetails"
```

### 1.8 ResultHandlerAction (Enum)

```
ResultHandlerAction
├── POST_REPLY = "postReply"
├── POST_MESSAGE = "postMessage"
└── NONE = "none"
```

### 1.9 RoomDetails

```
RoomDetails
├── room_id: str               # alias: "roomID"
├── actor_id: str              # alias: "actorID"
├── thread_id: str             # alias: "threadID"
└── vc_interaction_id: str     # alias: "vcInteractionID"
```

### 1.10 Response

The response sent back to the Alkemio platform.

```
Response
├── result: str | None         # alias: "result" — response text (NOTE: "result" not "body")
├── human_language: str | None    # alias: "humanLanguage"
├── result_language: str | None   # alias: "resultLanguage"
├── knowledge_language: str | None # alias: "knowledgeLanguage"
├── original_result: str | None   # alias: "originalResult"
├── sources: list[Source]         # default: [] — knowledge sources used
└── thread_id: str | None         # alias: "threadId" — OpenAI thread ID (returned by assistant plugin)
```

### 1.11 Source

```
Source
├── chunk_index: int | None       # alias: "chunkIndex"
├── embedding_type: str | None    # alias: "embeddingType"
├── document_id: str | None       # alias: "documentId"
├── source: str | None            # Source identifier
├── title: str | None             # Document title
├── type: str | None              # Document type
├── score: float | None           # Relevance score
└── uri: str | None               # Source URI
```

### 1.12 IngestWebsite Event

Deserialized from the top-level RabbitMQ message body (not nested in `input`). Discriminated by `eventType == "IngestWebsite"`.

```
IngestWebsite
├── base_url: str                 # alias: "baseUrl" — target URL to crawl (NOTE: "baseUrl" not "url")
├── type: str                     # alias: "type" — event type discriminator
├── purpose: str                  # alias: "purpose" — e.g., "knowledge"
├── persona_id: str               # alias: "personaId"
└── summarization_model: SummarizationModel  # alias: "summarizationModel" — default: "mistral-medium"
```

### 1.13 IngestWebsiteResult Event

```
IngestWebsiteResult
├── timestamp: int                # alias: "timestamp" — default: current time in ms
├── result: IngestionResult       # alias: "result" — default: SUCCESS (enum: "success"|"failure")
└── error: str                    # alias: "error" — default: "" — error message if failed
```

### 1.14 IngestBodyOfKnowledge Event (from ingest-space TypeScript service)

```
IngestBodyOfKnowledge
├── body_of_knowledge_id: str     # alias: "bodyOfKnowledgeId"
├── type: str                     # enum: "alkemio-space" | "alkemio-knowledge-base"
├── purpose: str                  # enum: "knowledge" | "context"
└── persona_id: str               # alias: "personaId"
```

### 1.15 IngestBodyOfKnowledgeResult Event

```
IngestBodyOfKnowledgeResult
├── body_of_knowledge_id: str     # alias: "bodyOfKnowledgeId"
├── type: str                     # Same as input event type
├── purpose: str                  # Same as input event purpose
├── persona_id: str               # alias: "personaId"
├── timestamp: int                # Current time in ms
├── result: str                   # "success" | "failure"
└── error: ErrorDetail | None     # Error details if failed

ErrorDetail
├── code: str | None              # Error code
└── message: str | None           # Error message
```

## 2. Core System Entities

### 2.1 PluginContract (Protocol)

The stable interface between core and plugins. Runtime-checkable via `typing.runtime_checkable`.

```
PluginContract (Protocol)
├── name: str                  # Plugin identifier (e.g., "expert", "generic")
├── event_type: type           # Pydantic model class this plugin handles
├── async startup() → None     # Resource initialization (called after DI, before consuming)
├── async shutdown() → None    # Graceful teardown (drain in-flight work, release connections)
└── async handle(event, **ports) → Response | IngestWebsiteResult | IngestBodyOfKnowledgeResult
```

**Lifecycle state transitions**:
```
CREATED → startup() → READY → handle(event) → READY → ... → shutdown() → STOPPED
                                  ↓ (error)
                              ERROR → (container exits non-zero)
```

### 2.2 Port Interfaces (Protocols)

#### LLMPort
```
LLMPort (Protocol)
├── async invoke(messages: list[dict]) → str           # Single completion
└── async stream(messages: list[dict]) → AsyncIterator  # Streaming completion
```

#### EmbeddingsPort
```
EmbeddingsPort (Protocol)
└── async embed(texts: list[str]) → list[list[float]]  # Batch embedding
```

#### KnowledgeStorePort
```
KnowledgeStorePort (Protocol)
├── async query(collection: str, query_texts: list[str], n_results: int = 10) → QueryResult
├── async ingest(collection: str, documents: list[str], metadatas: list[dict], ids: list[str]) → None
└── async delete_collection(collection: str) → None
```

#### TransportPort
```
TransportPort (Protocol)
├── async consume(queue: str, callback: Callable) → None  # Start consuming messages
├── async publish(exchange: str, routing_key: str, message: bytes) → None
└── async close() → None                                   # Close connection
```

### 2.3 Plugin Registry

```
PluginRegistry
├── _plugins: dict[str, type[PluginContract]]   # name → plugin class
├── register(plugin_class: type[PluginContract]) → None
├── get(name: str) → type[PluginContract] | None
└── list_plugins() → list[str]                  # Available plugin names
```

### 2.4 Content-Based Router

```
Router
├── _registry: PluginRegistry
├── route(message_body: dict) → tuple[PluginContract, BaseModel]
└── _parse_event(body: dict) → BaseModel
```

**Routing logic** (verified from base engine `invoke_handler`):
- If `body.get("eventType") == "IngestWebsite"`: construct `IngestWebsite(**body)`, route to ingest-website plugin
- If `PLUGIN_TYPE == "ingest-space"`: construct `IngestBodyOfKnowledge(**body)`, route to ingest-space plugin (note: ingest-space messages have no `eventType` field — routing is by plugin type, not message content)
- Else: construct `Input(**body["input"])`, route by plugin name (from `PLUGIN_TYPE` config)

**Published result format**:
```json
{"response": {<Response/Result fields>}, "original": {<Input/Event fields>}}
```

### 2.5 IoC Container

```
Container
├── _bindings: dict[type[Protocol], Any]  # port protocol → adapter instance
├── register(port: type[Protocol], adapter: Any) → None
├── resolve(port: type[Protocol]) → Any
└── resolve_for_plugin(plugin: PluginContract) → dict[str, Any]  # Resolve only declared ports
```

### 2.6 Configuration (Pydantic Settings)

```
BaseConfig (BaseSettings)
├── plugin_type: str              # PLUGIN_TYPE
├── log_level: str = "INFO"       # LOG_LEVEL
├── rabbitmq_host: str            # RABBITMQ_HOST
├── rabbitmq_user: str            # RABBITMQ_USER
├── rabbitmq_password: str        # RABBITMQ_PASSWORD
├── rabbitmq_port: int = 5672     # RABBITMQ_PORT (note: ingest-space uses explicit port)
├── rabbitmq_input_queue: str     # RABBITMQ_QUEUE (per-plugin input queue)
├── rabbitmq_result_queue: str    # RABBITMQ_RESULT_QUEUE (per-plugin result queue)
├── rabbitmq_exchange: str        # RABBITMQ_EVENT_BUS_EXCHANGE
├── rabbitmq_result_routing_key: str  # RABBITMQ_RESULT_ROUTING_KEY
├── vector_db_host: str | None    # VECTOR_DB_HOST
├── vector_db_port: int = 8765    # VECTOR_DB_PORT (NOTE: default 8765, not 8000)
├── vector_db_credentials: str | None  # VECTOR_DB_CREDENTIALS (token auth)
├── mistral_api_key: str | None   # MISTRAL_API_KEY
├── mistral_model_name: str | None # MISTRAL_SMALL_MODEL_NAME
├── embeddings_api_key: str | None    # EMBEDDINGS_API_KEY
├── embeddings_endpoint: str | None   # EMBEDDINGS_ENDPOINT
├── embeddings_model_name: str | None # EMBEDDINGS_MODEL_NAME
├── chunk_size: int = 2000        # CHUNK_SIZE
├── chunk_overlap: int = 400      # CHUNK_OVERLAP (ingest-space uses 500)
├── batch_size: int = 20          # BATCH_SIZE
├── summary_length: int = 10000   # SUMMARY_LENGTH
└── health_port: int = 8080       # HEALTH_PORT (per health-endpoints.md)
```

Plugin-specific config extensions:

```
IngestSpaceConfig (BaseConfig)
├── api_endpoint_private_graphql: str   # API_ENDPOINT_PRIVATE_GRAPHQL
├── auth_kratos_public_url: str         # AUTH_ORY_KRATOS_PUBLIC_BASE_URL
├── auth_admin_email: str               # AUTH_ADMIN_EMAIL
├── auth_admin_password: str            # AUTH_ADMIN_PASSWORD
├── chunk_size: int = 9000              # Override: ingest-space uses 9000
└── chunk_overlap: int = 500            # Override: ingest-space uses 500

IngestWebsiteConfig (BaseConfig)
└── process_pages_limit: int = 20       # PROCESS_PAGES_LIMIT

OpenAIAssistantConfig (BaseConfig)
├── run_poll_timeout_seconds: int = 300  # RUN_POLL_TIMEOUT_SECONDS
└── history_length: int = 20             # HISTORY_LENGTH

ExpertConfig (BaseConfig)
└── history_length: int = 10             # HISTORY_LENGTH
```

## 3. Domain Objects (`core/domain/`)

### 3.1 Document (Ingest Pipeline)

Internal representation of content to be ingested.

```
Document
├── content: str               # Raw text content
├── metadata: DocumentMetadata # Source metadata
└── chunks: list[Chunk] | None # Populated after chunking

DocumentMetadata
├── document_id: str           # alias: "documentId" — unique document identifier
├── source: str                # Source URL or space identifier
├── type: str                  # See DocumentType enum below
├── title: str                 # Document title
└── embedding_type: str        # "knowledge" (default)

DocumentType (from ingest-space, applicable to all ingest plugins)
├── KNOWLEDGE
├── SPACE
├── SUBSPACE
├── CALLOUT
├── PDF_FILE
├── SPREADSHEET
├── DOCUMENT
├── LINK
├── MEMO
├── WHITEBOARD
├── COLLECTION
├── POST
└── NONE

Chunk
├── content: str               # Chunk text
├── summary: str | None        # LLM-generated summary (if summarization applied)
├── metadata: ChunkMetadata    # Inherited document metadata + chunk index
└── embedding: list[float] | None  # Populated after embedding

ChunkMetadata (extends DocumentMetadata)
└── chunk_index: int           # alias: "chunkIndex" — position in document (0-based)
```

### 3.2 IngestResult

```
IngestResult
├── collection_name: str       # ChromaDB collection name
├── documents_processed: int   # Number of source documents
├── chunks_stored: int         # Total chunks stored
├── errors: list[str]          # Non-fatal errors (skipped files, etc.)
└── success: bool              # Overall success
```

### 3.3 PromptGraph (Domain)

Graph-based LLM workflow execution engine (ported from base engine, 368 LOC).

```
PromptGraph
├── nodes: dict[str, Node]     # Keyed by node name
├── edges: list[Edge]          # Directed connections
├── start_node: str            # alias: "start" — default: "START"
├── end_node: str              # alias: "end" — default: "END"
├── state_model: type[BaseModel] | None  # Built dynamically from state schema
├── compile(llm, special_nodes: dict) → CompiledGraph  # LangGraph StateGraph
└── stream(state: dict, stream_mode: str) → AsyncIterator

Node
├── name: str                  # Unique identifier
├── input_variables: list[str] # State variable names to pull
├── prompt: str                # Prompt template with {variable} placeholders
├── output_schema: dict        # alias: "output" — JSON schema for structured output
└── output_model: type[BaseModel] | None  # Dynamically built from output_schema

Edge
├── from_node: str             # alias: "from" — source node name, or "START"
└── to_node: str               # alias: "to" — destination node name, or "END"
```

**State Model**: Built dynamically from a JSON schema using `json_schema_to_pydantic.create_model()` with custom schema transformation for list-to-dict property conversion and optional field handling.

**Compilation**: Non-special nodes use `ChatPromptTemplate` + `PydanticOutputParser` chain. Special nodes (like `"retrieve"`) are injected as raw callables.

### 3.4 QueryResult (Knowledge Store)

```
QueryResult
├── documents: list[list[str]]     # Retrieved document texts
├── metadatas: list[list[dict]]    # Retrieved document metadata
├── distances: list[list[float]]   # Similarity distances
└── ids: list[list[str]]          # Document IDs
```

### 3.5 Summarization Graph State (Ingest Domain)

```
SummarizeState
├── chunks: list[Document]     # Document chunks to summarize
├── index: int                 # Current chunk index (iteration counter)
└── summary: str               # Running summary (refine pattern)
```

Two graph instances:
- `document_graph`: Summarize individual documents (progressive length budget: 40% → 100%)
- `bok_graph`: Summarize entire body of knowledge

## 4. Entity Relationships

```
Container ──registers──→ Adapter ──implements──→ Port (Protocol)
                                                    ↑
Plugin (PluginContract) ──depends on──────────────┘
    │
    ├── expert ──uses──→ LLMPort (mistral_small), KnowledgeStorePort
    ├── generic ──uses──→ LLMPort (per-request via external_config)
    ├── guidance ──uses──→ LLMPort (mistral_medium), KnowledgeStorePort
    ├── openai_assistant ──uses──→ OpenAIAssistantAdapter (AsyncOpenAI, per-request client)
    ├── ingest_website ──uses──→ LLMPort, EmbeddingsPort, KnowledgeStorePort
    └── ingest_space ──uses──→ LLMPort, EmbeddingsPort, KnowledgeStorePort

PluginRegistry ──discovers──→ Plugin
Router ──queries──→ PluginRegistry
TransportAdapter (RabbitMQ) ──delivers──→ Router ──dispatches──→ Plugin.handle()

RabbitMQ Message Flow:
  Query:  {"input": {Input fields}} → Input(**body["input"]) → Plugin.handle() → {"response": {...}, "original": {...}}
  Ingest: {"eventType": "IngestWebsite", ...fields} → IngestWebsite(**body) → Plugin.handle() → {"response": {...}}

Ingest Pipeline (domain)
    ├── uses: EmbeddingsPort (embed chunks)
    ├── uses: KnowledgeStorePort (store chunks)
    ├── uses: LLMPort (summarize chunks)
    └── produces: IngestResult

PromptGraph (domain)
    ├── uses: LLMPort (execute nodes)
    ├── uses: KnowledgeStorePort (special "retrieve" node)
    └── produces: Response
```

## 5. Collection Naming Conventions

| Plugin | Collection Name Pattern | Example |
|--------|------------------------|---------|
| expert | `{bodyOfKnowledgeId}-knowledge` | `abc123-knowledge` |
| guidance | Hardcoded: `alkem.io-knowledge`, `welcome.alkem.io-knowledge`, `www.alkemio.org-knowledge` | (fixed) |
| ingest-website | `{netloc}-knowledge` (colons replaced with hyphens) | `example.com-knowledge` |
| ingest-space | Determined by embedSpace/embedKnowledgeBase functions | `{bokId}-{purpose}` |

## 6. Validation Rules

| Entity | Field | Rule |
|--------|-------|------|
| Input | message | Required, non-empty string |
| Input | engine | Required string (used for LLM provider selection in generic plugin) |
| Input | persona_id | Required string |
| Input | result_handler | Required (determines response delivery) |
| Input | prompt_graph | Required for expert plugin, must be valid graph JSON |
| Input | external_config.assistant_id | Required for openai-assistant plugin |
| Input | external_config.api_key | Required for openai-assistant and generic (when using external provider) |
| Response | result | String or None (main response text) |
| Response | sources | Required list (empty list allowed for plugins without knowledge retrieval) |
| IngestWebsite | base_url | Required, valid URL format |
| IngestWebsite | purpose | Required string |
| IngestBodyOfKnowledge | body_of_knowledge_id | Required, non-empty string |
| IngestBodyOfKnowledge | type | Required, enum: "alkemio-space" or "alkemio-knowledge-base" |
| BaseConfig | plugin_type | Required, must match a registered plugin name |
| BaseConfig | rabbitmq_host | Required for all plugins |
| Document | content | Required, non-empty string |
| DocumentMetadata | document_id | Required, unique within collection |
| PromptGraph | nodes | Required, at least one node |
| PromptGraph | edges | Required, must form valid directed graph |
| PromptGraph | start_node | Must reference existing node or "START" |
