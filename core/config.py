from __future__ import annotations

from enum import Enum

import logging
import math

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM provider backends."""

    mistral = "mistral"
    openai = "openai"
    anthropic = "anthropic"


# Ceiling for ingest chunk sizing. Well above any benchmarked optimum
# (512-1024 tokens ~= 2000-4000 chars) but low enough that a mistyped value
# fails at startup rather than during a multi-hour ingest run.
MAX_CHUNK_SIZE = 100_000


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

    # Tracing — intentionally separate from standard OTEL_* environment names.
    # The exporter is configured only from these explicit service settings.
    tracing_enabled: bool = False
    tracing_otlp_endpoint: str | None = None
    tracing_otlp_headers: str | None = None
    tracing_service_name: str | None = None
    tracing_sample_ratio: float = 1.0
    tracing_capture_content: bool = True
    tracing_content_max_chars: int = 1000

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
        if not 0.0 <= self.tracing_sample_ratio <= 1.0:
            raise ValueError(
                "TRACING_SAMPLE_RATIO must be between 0.0 and 1.0, "
                f"got {self.tracing_sample_ratio}"
            )
        if self.tracing_content_max_chars <= 0:
            raise ValueError(
                "TRACING_CONTENT_MAX_CHARS must be greater than 0, "
                f"got {self.tracing_content_max_chars}"
            )
        if self.tracing_otlp_headers:
            valid_headers = 0
            for item in self.tracing_otlp_headers.split(","):
                key, separator, _ = item.partition("=")
                if separator and key.strip():
                    valid_headers += 1
            if valid_headers == 0:
                raise ValueError(
                    "TRACING_OTLP_HEADERS must contain at least one key=value pair"
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

        # Hybrid retrieval validation — rejected at startup rather than
        # degrading retrieval quietly at query time.
        if self.hybrid_rrf_k <= 0:
            raise ValueError(
                f"HYBRID_RRF_K must be greater than 0, got {self.hybrid_rrf_k}"
            )
        if not math.isfinite(self.hybrid_dense_weight) or not math.isfinite(
            self.hybrid_lexical_weight
        ):
            # NaN compares false against everything, so it would slip past the
            # bounds below and then make every ordering comparison arbitrary.
            raise ValueError(
                "HYBRID_DENSE_WEIGHT and HYBRID_LEXICAL_WEIGHT must be finite "
                f"numbers, got {self.hybrid_dense_weight} and "
                f"{self.hybrid_lexical_weight}"
            )
        if self.hybrid_dense_weight < 0:
            raise ValueError(
                f"HYBRID_DENSE_WEIGHT must not be negative, "
                f"got {self.hybrid_dense_weight}"
            )
        if self.hybrid_lexical_weight < 0:
            raise ValueError(
                f"HYBRID_LEXICAL_WEIGHT must not be negative, "
                f"got {self.hybrid_lexical_weight}"
            )
        if self.hybrid_dense_weight == 0 and self.hybrid_lexical_weight == 0:
            raise ValueError(
                "HYBRID_DENSE_WEIGHT and HYBRID_LEXICAL_WEIGHT must not both "
                "be 0 — every result would score 0 and ordering would be "
                "arbitrary"
            )
        if self.hybrid_max_terms <= 0:
            raise ValueError(
                f"HYBRID_MAX_TERMS must be greater than 0, "
                f"got {self.hybrid_max_terms}"
            )
        if self.hybrid_min_term_len <= 0:
            raise ValueError(
                f"HYBRID_MIN_TERM_LEN must be greater than 0, "
                f"got {self.hybrid_min_term_len}"
            )

        # Re-ranking validation. Fail at startup naming the variable: a bad
        # value here would otherwise surface as quietly worse answers, with
        # nothing in the logs to connect them to a config change.
        if self.rerank_top_k <= 0:
            raise ValueError(
                f"RERANK_TOP_K must be greater than 0, got {self.rerank_top_k}"
            )
        if self.rerank_candidate_n <= 0:
            raise ValueError(
                f"RERANK_CANDIDATE_N must be greater than 0, "
                f"got {self.rerank_candidate_n}"
            )
        if self.rerank_candidate_n < self.rerank_top_k:
            # Keeping fewer candidates than we keep results is incoherent —
            # re-ranking would have nothing to choose between.
            raise ValueError(
                f"RERANK_CANDIDATE_N ({self.rerank_candidate_n}) must be at "
                f"least RERANK_TOP_K ({self.rerank_top_k})"
            )
        # NaN and inf are covered by this same check, not by a separate
        # isfinite guard: every comparison against NaN is False, so `not
        # (0.0 <= nan <= 1.0)` is True and NaN is rejected here. Both are
        # asserted in the config tests so this stays true.
        if not (0.0 <= self.rerank_lexical_weight <= 1.0):
            raise ValueError(
                f"RERANK_LEXICAL_WEIGHT must be between 0.0 and 1.0, "
                f"got {self.rerank_lexical_weight}"
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

        # Ingest sizing validation
        if self.chunk_size <= 0:
            raise ValueError(
                f"CHUNK_SIZE must be greater than 0, got {self.chunk_size}"
            )
        if self.chunk_overlap < 0:
            raise ValueError(
                f"CHUNK_OVERLAP must be greater than or equal to 0, "
                f"got {self.chunk_overlap}"
            )
        if self.chunk_overlap > self.chunk_size // 2:
            # Not just `>= chunk_size`: overlap approaching the chunk size
            # amplifies embedding volume super-linearly (overlap 2499 against
            # size 2500 embeds ~238x the corpus), and startup is the only
            # place that can catch it — the ingest run itself has a 3h budget.
            raise ValueError(
                f"CHUNK_OVERLAP must not exceed half of CHUNK_SIZE, got "
                f"{self.chunk_overlap} > {self.chunk_size // 2} "
                f"(CHUNK_SIZE={self.chunk_size})"
            )
        if self.chunk_size > MAX_CHUNK_SIZE:
            raise ValueError(
                f"CHUNK_SIZE must not exceed {MAX_CHUNK_SIZE}, "
                f"got {self.chunk_size}"
            )
        if self.summary_length <= 0:
            raise ValueError(
                f"SUMMARY_LENGTH must be greater than 0, got {self.summary_length}"
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

        # Answering generation validation. This setting is intentionally
        # separate from LLM_TEMPERATURE: it applies only at answer call sites
        # and is opt-in so existing deployments retain provider defaults.
        if self.answering_llm_temperature is not None and not (
            0.0 <= self.answering_llm_temperature <= 2.0
        ):
            raise ValueError(
                "ANSWERING_LLM_TEMPERATURE must be between 0.0 and 2.0, "
                f"got {self.answering_llm_temperature}"
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
    # Query-side instruction prefix for retrieval. If None, adapters auto-apply
    # the Qwen3 retrieval prompt when the model name starts with
    # "qwen3-embedding"; any explicit value (including "") is used verbatim.
    embeddings_query_instruction: str | None = None

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

    # Answering generation — opt-in per-call override for retrieval-backed
    # answering only. Unset preserves the shared LLM adapter's existing
    # provider defaults for answering, ingestion, and summarization.
    answering_llm_temperature: float | None = None
    answering_chain_of_thought_enabled: bool = True

    # Retrieval — per-plugin parameters
    expert_n_results: int = 5
    expert_min_score: float = 0.3
    guidance_n_results: int = 5
    guidance_min_score: float = 0.3

    # Hybrid retrieval — a lexical arm alongside the embedding arm, fused by
    # reciprocal rank. Off by default: it changes what every answer is grounded
    # in, so it is opted into rather than inherited.
    hybrid_retrieval_enabled: bool = False
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3

    # Context budget
    max_context_chars: int = 20000

    # Summarization threshold
    summary_chunk_threshold: int = 4

    # Retrieval — deprecated global fields (kept for backward compat)
    retrieval_n_results: int = 5
    retrieval_score_threshold: float = 0.3

    # Re-ranking — off by default. It changes what every answer is grounded
    # in, so it is opted into rather than inherited. Disabling it restores
    # prior behaviour exactly: the same n_results is requested and no
    # re-ranking code runs at all.
    rerank_enabled: bool = False
    #: Candidates fetched when re-ranking is on. Re-ranking can only reorder
    #: what retrieval returned, so it needs a wider pool than it will keep.
    rerank_candidate_n: int = 20
    #: Candidates surviving re-ranking, into context assembly.
    rerank_top_k: int = 5
    #: Lexical share of the blend. Accepted range is 0.0–1.0 inclusive; 0.0
    #: provably reproduces vector order and is the fine-grained rollback.
    #:
    #: Between those ends the value is not free: to promote a worst-on-vector
    #: passage the weight must exceed ``1 / (2 - L0)``, which is 0.5 when the
    #: incumbent shares none of the query's wording. At exactly 0.5 the two
    #: tie and the stable sort keeps the incumbent, so a weight in (0.0, 0.5]
    #: is a validated setting that cannot do the thing re-ranking is for.
    #: See LexicalReranker.DEFAULT_LEXICAL_WEIGHT for the derivation.
    rerank_lexical_weight: float = 0.6

    # Ingest pipeline
    chunk_size: int = 2000
    chunk_overlap: int = 400
    ingest_batch_size: int = 5
    summary_length: int = 2500
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
    chunk_size: int = 2500
    chunk_overlap: int = 300


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
