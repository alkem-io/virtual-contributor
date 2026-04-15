from __future__ import annotations

from enum import Enum

import logging

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


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

    # Pipeline timeout (seconds) — outer timeout wrapping plugin.handle()
    pipeline_timeout: int = 3600

    # ChromaDB / Vector DB
    vector_db_host: str | None = None
    vector_db_port: int = 8765
    vector_db_credentials: str | None = None
    vector_db_distance_fn: str = "cosine"  # cosine, l2, or ip

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
        if self.rabbitmq_heartbeat < 0:
            raise ValueError(
                f"RABBITMQ_HEARTBEAT must be >= 0, got {self.rabbitmq_heartbeat}"
            )
        if self.rabbitmq_max_retries < 1:
            raise ValueError(
                f"RABBITMQ_MAX_RETRIES must be >= 1, got {self.rabbitmq_max_retries}"
            )
        if self.pipeline_timeout <= 0:
            raise ValueError(
                f"PIPELINE_TIMEOUT must be greater than 0, got {self.pipeline_timeout}"
            )

        # Vector DB distance function validation
        valid_distance_fns = {"cosine", "l2", "ip"}
        if self.vector_db_distance_fn not in valid_distance_fns:
            raise ValueError(
                f"VECTOR_DB_DISTANCE_FN must be one of {valid_distance_fns}, "
                f"got '{self.vector_db_distance_fn}'"
            )

        # Summarize concurrency validation
        if self.summarize_concurrency < 0:
            raise ValueError(
                f"SUMMARIZE_CONCURRENCY must be >= 0, got {self.summarize_concurrency}"
            )

        # Summarization LLM validation
        if self.summarize_llm_temperature is not None and not (
            0.0 <= self.summarize_llm_temperature <= 2.0
        ):
            raise ValueError(
                f"SUMMARIZE_LLM_TEMPERATURE must be between 0.0 and 2.0, "
                f"got {self.summarize_llm_temperature}"
            )
        if self.summarize_llm_timeout is not None and self.summarize_llm_timeout <= 0:
            raise ValueError(
                f"SUMMARIZE_LLM_TIMEOUT must be greater than 0, "
                f"got {self.summarize_llm_timeout}"
            )

        # Per-plugin retrieval validation
        if self.expert_n_results <= 0:
            raise ValueError(
                f"EXPERT_N_RESULTS must be greater than 0, got {self.expert_n_results}"
            )
        if self.guidance_n_results <= 0:
            raise ValueError(
                f"GUIDANCE_N_RESULTS must be greater than 0, got {self.guidance_n_results}"
            )
        if not (0.0 <= self.expert_min_score <= 1.0):
            raise ValueError(
                f"EXPERT_MIN_SCORE must be between 0.0 and 1.0, got {self.expert_min_score}"
            )
        if not (0.0 <= self.guidance_min_score <= 1.0):
            raise ValueError(
                f"GUIDANCE_MIN_SCORE must be between 0.0 and 1.0, got {self.guidance_min_score}"
            )

        # Context budget validation
        if self.max_context_chars <= 0:
            raise ValueError(
                f"MAX_CONTEXT_CHARS must be greater than 0, got {self.max_context_chars}"
            )
        if self.max_context_chars < 1000:
            logger.warning(
                "MAX_CONTEXT_CHARS=%d is very low — may cause excessive chunk dropping",
                self.max_context_chars,
            )

        # Chunk threshold validation
        if self.summary_chunk_threshold <= 0:
            raise ValueError(
                f"SUMMARY_CHUNK_THRESHOLD must be greater than 0, "
                f"got {self.summary_chunk_threshold}"
            )

        # Partial summarize config warning
        summarize_fields = [
            self.summarize_llm_provider,
            self.summarize_llm_model,
            self.summarize_llm_api_key,
        ]
        set_count = sum(1 for f in summarize_fields if f is not None)
        if 0 < set_count < 3:
            missing = []
            if self.summarize_llm_provider is None:
                missing.append("SUMMARIZE_LLM_PROVIDER")
            if self.summarize_llm_model is None:
                missing.append("SUMMARIZE_LLM_MODEL")
            if self.summarize_llm_api_key is None:
                missing.append("SUMMARIZE_LLM_API_KEY")
            logger.warning(
                "Partial summarization LLM config — missing: %s. "
                "Falling back to main LLM for summarization.",
                ", ".join(missing),
            )

        # BoK LLM validation
        if self.bok_llm_temperature is not None and not (
            0.0 <= self.bok_llm_temperature <= 2.0
        ):
            raise ValueError(
                f"BOK_LLM_TEMPERATURE must be between 0.0 and 2.0, "
                f"got {self.bok_llm_temperature}"
            )
        if self.bok_llm_timeout is not None and self.bok_llm_timeout <= 0:
            raise ValueError(
                f"BOK_LLM_TIMEOUT must be greater than 0, "
                f"got {self.bok_llm_timeout}"
            )

        # Partial BoK config warning
        bok_fields = [
            self.bok_llm_provider,
            self.bok_llm_model,
            self.bok_llm_api_key,
        ]
        bok_set_count = sum(1 for f in bok_fields if f is not None)
        if 0 < bok_set_count < 3:
            missing = []
            if self.bok_llm_provider is None:
                missing.append("BOK_LLM_PROVIDER")
            if self.bok_llm_model is None:
                missing.append("BOK_LLM_MODEL")
            if self.bok_llm_api_key is None:
                missing.append("BOK_LLM_API_KEY")
            logger.warning(
                "Partial BoK LLM config — missing: %s. "
                "Falling back to summarize/main LLM for BoK summarization.",
                ", ".join(missing),
            )

        return self

    # Embeddings
    embeddings_api_key: str | None = None
    embeddings_endpoint: str | None = None
    embeddings_model_name: str | None = None

    # Summarization LLM — optional separate model for summarization tasks
    summarize_llm_provider: LLMProvider | None = None
    summarize_llm_model: str | None = None
    summarize_llm_api_key: str | None = None
    summarize_llm_base_url: str | None = None
    summarize_llm_temperature: float | None = None
    summarize_llm_timeout: int | None = None

    # BoK LLM — optional separate model for body-of-knowledge summarization
    # (needs large context window; falls back to summarize LLM, then main LLM)
    bok_llm_provider: LLMProvider | None = None
    bok_llm_model: str | None = None
    bok_llm_api_key: str | None = None
    bok_llm_base_url: str | None = None
    bok_llm_temperature: float | None = None
    bok_llm_timeout: int | None = None

    # Retrieval — per-plugin parameters
    expert_n_results: int = 5
    expert_min_score: float = 0.3
    guidance_n_results: int = 5
    guidance_min_score: float = 0.3

    # Context budget
    max_context_chars: int = 20000

    # Summarization threshold
    summary_chunk_threshold: int = 4

    # Retrieval — deprecated global fields (kept for backward compat)
    retrieval_n_results: int = 5
    retrieval_score_threshold: float = 0.3

    # Ingest pipeline
    chunk_size: int = 2000
    chunk_overlap: int = 400
    ingest_batch_size: int = 5
    summary_length: int = 10000
    summarize_concurrency: int = 8
    summarize_enabled: bool = True

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
