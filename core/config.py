from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class LLMProvider(str, Enum):
    """Supported LLM provider backends."""

    mistral = "mistral"
    openai = "openai"
    anthropic = "anthropic"


class BaseConfig(BaseSettings):
    """Shared configuration consumed by every plugin.

    Environment variables are mapped 1-to-1 by field name (upper-cased)
    unless ``validation_alias`` provides an explicit override.
    """

    model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}

    plugin_type: str = ""
    log_level: str = "INFO"

    # RabbitMQ
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_user: str = "alkemio-admin"
    rabbitmq_password: str = "alkemio!"
    rabbitmq_port: int = 5672
    rabbitmq_input_queue: str = Field(default="", validation_alias="RABBITMQ_QUEUE")
    rabbitmq_result_queue: str = ""
    rabbitmq_exchange: str = Field(
        default="event-bus", validation_alias="RABBITMQ_EVENT_BUS_EXCHANGE"
    )
    rabbitmq_result_routing_key: str = "invoke-engine-result"
    rabbitmq_heartbeat: int = 300
    rabbitmq_max_retries: int = 3

    # ChromaDB / Vector DB
    vector_db_host: str | None = None
    vector_db_port: int = 8765
    vector_db_credentials: str | None = None

    # LLM — provider-agnostic configuration
    llm_provider: LLMProvider = LLMProvider.mistral
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    llm_top_p: float | None = None
    llm_timeout: int = 120

    # LLM — backward compatibility aliases (FR-009)
    mistral_api_key: str | None = None
    mistral_model_name: str | None = Field(
        default=None, validation_alias="MISTRAL_SMALL_MODEL_NAME"
    )

    @model_validator(mode="after")
    def _resolve_backward_compat_and_validate(self) -> BaseConfig:
        # Backward compatibility: fall back to legacy Mistral env vars
        if self.llm_provider == LLMProvider.mistral:
            if not self.llm_api_key and self.mistral_api_key:
                self.llm_api_key = self.mistral_api_key
            if not self.llm_model and self.mistral_model_name:
                self.llm_model = self.mistral_model_name

        # API key required unless base_url is set (local models)
        if not self.llm_api_key and not self.llm_base_url:
            raise ValueError(
                f"LLM_API_KEY is required for provider '{self.llm_provider.value}'. "
                "Set LLM_API_KEY or provide LLM_BASE_URL for local models."
            )

        # Validate generation parameters
        if self.llm_temperature is not None and not (0.0 <= self.llm_temperature <= 2.0):
            raise ValueError(
                f"LLM_TEMPERATURE must be between 0.0 and 2.0, got {self.llm_temperature}"
            )
        if self.llm_max_tokens is not None and self.llm_max_tokens <= 0:
            raise ValueError(
                f"LLM_MAX_TOKENS must be greater than 0, got {self.llm_max_tokens}"
            )
        if self.llm_top_p is not None and not (0.0 <= self.llm_top_p <= 1.0):
            raise ValueError(
                f"LLM_TOP_P must be between 0.0 and 1.0, got {self.llm_top_p}"
            )
        if self.llm_timeout <= 0:
            raise ValueError(
                f"LLM_TIMEOUT must be greater than 0, got {self.llm_timeout}"
            )

        return self

    # Embeddings
    embeddings_api_key: str | None = None
    embeddings_endpoint: str | None = None
    embeddings_model_name: str | None = None

    # Retrieval
    retrieval_n_results: int = 5
    retrieval_score_threshold: float = 0.3

    # Ingest pipeline
    chunk_size: int = 2000
    chunk_overlap: int = 400
    batch_size: int = 20
    summary_length: int = 10000
    summarize_concurrency: int = 8

    # Health
    health_port: int = 8080


class IngestSpaceConfig(BaseConfig):
    """Configuration for the ingest-space plugin."""

    api_endpoint_private_graphql: str = ""
    auth_kratos_public_url: str = Field(
        default="", validation_alias="AUTH_ORY_KRATOS_PUBLIC_BASE_URL"
    )
    auth_admin_email: str = ""
    auth_admin_password: str = ""
    chunk_size: int = 9000
    chunk_overlap: int = 500


class IngestWebsiteConfig(BaseConfig):
    """Configuration for the ingest-website plugin."""

    process_pages_limit: int = 20


class OpenAIAssistantConfig(BaseConfig):
    """Configuration for the openai-assistant plugin."""

    run_poll_timeout_seconds: int = 300
    history_length: int = 20


class ExpertConfig(BaseConfig):
    """Configuration for the expert plugin."""

    history_length: int = 10
