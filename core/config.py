from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings):
    """Shared configuration consumed by every plugin.

    Environment variables are mapped 1-to-1 by field name (upper-cased)
    unless ``validation_alias`` provides an explicit override.
    """

    model_config = {"env_file": ".env", "extra": "ignore"}

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

    # ChromaDB / Vector DB
    vector_db_host: str | None = None
    vector_db_port: int = 8765
    vector_db_credentials: str | None = None

    # LLM
    mistral_api_key: str | None = None
    mistral_model_name: str | None = Field(
        default=None, validation_alias="MISTRAL_SMALL_MODEL_NAME"
    )

    # Embeddings
    embeddings_api_key: str | None = None
    embeddings_endpoint: str | None = None
    embeddings_model_name: str | None = None

    # Ingest pipeline
    chunk_size: int = 2000
    chunk_overlap: int = 400
    batch_size: int = 20
    summary_length: int = 10000

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
