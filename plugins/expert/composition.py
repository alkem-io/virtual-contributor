"""Immutable, pre-factory authority for an Expert invocation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, cast

from core.adapters.openai_compatible_embeddings import _resolve_query_instruction
from core.provider_factory import DEFAULT_MODELS

if TYPE_CHECKING:
    from core.config import BaseConfig

Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ExpertSelector:
    """One stable public selector and the concrete object it selects."""

    name: str
    primitive_id: str
    target: Callable[..., object]


@dataclass(frozen=True, slots=True)
class ExpertSelectorRegistry:
    """Closed immutable registry for every Expert dependency selection."""

    entries: tuple[ExpertSelector, ...]

    def entry(self, name: str) -> ExpertSelector:
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise KeyError(f"Unknown Expert selector: {name}")


@dataclass(frozen=True, slots=True)
class ResolvedExpertSelectors:
    """The exact concrete entries selected with one resolved authority."""

    entries: tuple[ExpertSelector, ...]

    def entry(self, name: str) -> ExpertSelector:
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise KeyError(f"Unknown resolved Expert selector: {name}")


@dataclass(frozen=True, slots=True)
class ResolvedExpertComposition:
    """The sole, deeply immutable authority for one Expert construction.

    Both tuples contain only primitives.  ``plumbing`` is intentionally the
    only place credentials/endpoints may occur; it is never serialized.  The
    object does not retain a settings model or a factory adapter.
    """

    behavior: tuple[tuple[str, Scalar], ...]
    dependency_identities: tuple[tuple[str, str], ...]
    mode: Literal["flat", "hierarchical"]

    def value(self, name: str) -> Scalar:
        for key, value in self.behavior:
            if key == name:
                return value
        raise AttributeError(name)

    def __getattr__(self, name: str) -> Scalar:
        # Hybrid retrieval is deliberately structural.  It receives this
        # immutable authority, never a mutable BaseConfig compatibility view.
        return self.value(name)


@dataclass(frozen=True, slots=True)
class ExpertPlumbing:
    """Secret/endpoint-only wiring excluded from the public authority."""

    values: tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class ResolvedExpertWiring:
    """One resolver result; factories share ``authority`` by identity."""

    authority: ResolvedExpertComposition
    plumbing: ExpertPlumbing
    selectors: ResolvedExpertSelectors


def _build_routing_table(
    composition: ResolvedExpertComposition,
    *,
    n_results: int,
    score_threshold: float,
    max_context_chars: int,
) -> dict[object, object]:
    """Build Expert routing profiles from the already-resolved authority."""
    from core.domain.routing import RetrievalProfile
    from core.ports.query_router import RouteClass

    def integer(name: str) -> int:
        value = composition.value(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Resolved Expert routing value {name} must be an integer")
        return value

    return {
        RouteClass.CONVERSATIONAL: RetrievalProfile(False, n_results, score_threshold, max_context_chars),
        RouteClass.SIMPLE: RetrievalProfile(
            True, min(integer("routing_simple_n_results"), n_results),
            score_threshold, max_context_chars,
        ),
        RouteClass.MODERATE: RetrievalProfile(True, n_results, score_threshold, max_context_chars),
        RouteClass.COMPLEX: RetrievalProfile(
            True, max(integer("routing_complex_n_results"), n_results),
            score_threshold, max(integer("routing_complex_context_chars"), max_context_chars),
        ),
    }


def _build_rewrite_policy() -> object | None:
    """Build the optional rewrite gate without changing the disabled path."""
    from main import _build_rewrite_policy as legacy_builder

    return legacy_builder()


def _selector_registry() -> ExpertSelectorRegistry:
    """Construct the sole immutable registry of concrete Expert dependencies."""
    from core.adapters.chromadb import ChromaDBAdapter
    from core.adapters.openai_compatible_embeddings import OpenAICompatibleEmbeddingsAdapter
    from core.domain.faithfulness import ContextSufficiencyValidator
    from core.domain.hybrid_retrieval import retrieve
    from core.domain.rerank import LexicalReranker
    from core.domain.rule_classifier import RuleQueryClassifier
    from core.provider_factory import create_llm_adapter

    return ExpertSelectorRegistry(entries=(
        ExpertSelector("llm", "expert.llm.adapter/v1", create_llm_adapter),
        ExpertSelector("embeddings", "expert.embeddings.adapter/v1", OpenAICompatibleEmbeddingsAdapter),
        ExpertSelector("knowledge_store", "expert.knowledge-store.adapter/v1", ChromaDBAdapter),
        ExpertSelector("hybrid", "expert.hybrid.retrieve/v1", retrieve),
        ExpertSelector("reranker", "expert.reranker.lexical/v1", LexicalReranker),
        ExpertSelector("router", "expert.router.rule-classifier/v1", RuleQueryClassifier),
        ExpertSelector("routing_table", "expert.routing-table.profile-builder/v1", _build_routing_table),
        ExpertSelector("faithfulness", "expert.faithfulness.context-sufficiency/v1", ContextSufficiencyValidator),
        ExpertSelector("rewrite", "expert.rewrite.policy-builder/v1", _build_rewrite_policy),
    ))


EXPERT_SELECTOR_REGISTRY = _selector_registry()


def expert_runtime_config(
    authority: ResolvedExpertComposition, plumbing: ExpertPlumbing,
) -> BaseConfig:
    """Transient adapter compatibility view with every behaviour set explicitly."""
    from core.config import BaseConfig, LLMProvider
    values = dict(authority.behavior) | dict(plumbing.values)
    values["plugin_type"] = "expert"
    values["expert_hierarchical_retrieval_enabled"] = authority.mode == "hierarchical"
    values["llm_provider"] = LLMProvider(str(values["llm_provider"]))
    return BaseConfig(**cast(dict[str, Any], values))


# Everything read by the Expert plugin, its adapters, or its generated helper
# dependencies.  New live knobs belong here in the same change as their use.
_BEHAVIOR_FIELDS = (
    "expert_n_results", "expert_min_score", "max_context_chars",
    "expert_hierarchy_max_branches", "expert_hierarchy_display_names_enabled",
    "answering_llm_temperature", "answering_chain_of_thought_enabled",
    "llm_temperature", "llm_max_tokens", "llm_top_p", "llm_timeout",
    "embeddings_query_max_utf8_bytes", "embeddings_max_attempts",
    "embeddings_attempt_timeout_seconds", "embeddings_total_deadline_seconds",
    "vector_db_distance_fn", "hybrid_retrieval_enabled", "hybrid_dense_weight",
    "hybrid_lexical_weight", "hybrid_rrf_k", "hybrid_max_terms", "hybrid_min_term_len",
    "rerank_enabled", "rerank_candidate_n", "rerank_top_k", "rerank_lexical_weight",
    "routing_enabled", "routing_simple_n_results", "routing_complex_n_results",
    "routing_complex_context_chars", "faithfulness_validation_enabled",
    "query_rewrite_gating_enabled", "query_rewrite_max_expansion_ratio",
    "query_rewrite_max_history_chars", "query_rewrite_max_utf8_bytes",
)
_PLUMBING_FIELDS = (
    "llm_api_key", "llm_base_url", "embeddings_api_key", "embeddings_endpoint",
    "vector_db_host", "vector_db_port", "vector_db_credentials", "tracing_enabled",
)
def resolve_expert_composition(
    config: BaseConfig, *, llm_config: BaseConfig | None = None,
    selector_registry: ExpertSelectorRegistry | None = None,
) -> ResolvedExpertWiring:
    """Resolve config and plugin-LLM defaults exactly once, before factories."""
    selector_registry = selector_registry or EXPERT_SELECTOR_REGISTRY
    effective_llm = llm_config or config
    provider = effective_llm.llm_provider.value
    llm_model = effective_llm.llm_model or DEFAULT_MODELS[effective_llm.llm_provider]
    embedding_model = config.embeddings_model_name or "qwen3-embedding-8b"
    history = getattr(config, "history_length", None)
    values: dict[str, Scalar] = {name: getattr(config, name) for name in _BEHAVIOR_FIELDS}
    values.update({
        "llm_provider": provider,
        "llm_model": llm_model,
        "embeddings_model_name": embedding_model,
        "embeddings_query_instruction": _resolve_query_instruction(
            embedding_model, config.embeddings_query_instruction,
        ),
        "query_rewrite_max_history_turns": min(
            config.query_rewrite_max_history_turns, history,
        ) if history else config.query_rewrite_max_history_turns,
    })
    # Plugin overrides are the live LLM authority, not a later factory choice.
    for name in ("llm_temperature", "llm_max_tokens", "llm_top_p", "llm_timeout"):
        values[name] = getattr(effective_llm, name)
    plumbing = tuple(sorted((name, getattr(effective_llm if name.startswith("llm_") else config, name)) for name in _PLUMBING_FIELDS))
    mode: Literal["flat", "hierarchical"] = (
        "hierarchical" if config.expert_hierarchical_retrieval_enabled else "flat"
    )
    selected = ResolvedExpertSelectors(selector_registry.entries)
    identities = {entry.name: entry.primitive_id for entry in selected.entries}
    for name, enabled in (("reranker", values["rerank_enabled"]), ("router", values["routing_enabled"]), ("routing_table", values["routing_enabled"]), ("faithfulness", values["faithfulness_validation_enabled"]), ("rewrite", values["query_rewrite_gating_enabled"])):
        if not enabled:
            identities[name] = "none"
    authority = ResolvedExpertComposition(
        behavior=tuple(sorted(values.items())),
        dependency_identities=tuple(sorted(identities.items())),
        mode=mode,
    )
    return ResolvedExpertWiring(
        authority=authority,
        plumbing=ExpertPlumbing(plumbing),
        selectors=selected,
    )


def expert_composition_descriptor(composition: ResolvedExpertComposition) -> dict[str, object]:
    """Serialize retained authority directly; mode is the sole exclusion."""
    if not isinstance(composition, ResolvedExpertComposition):
        raise TypeError("Expert descriptor requires ResolvedExpertComposition")
    # The semantic grouping is stable for humans; its leaves are copied
    # directly from the immutable authority, never from BaseConfig.
    values = dict(composition.behavior)
    deps = dict(composition.dependency_identities)
    return {
        "schema": "expert-composition/v7",
        "expert": {key: values[key] for key in (
            "expert_n_results", "expert_min_score", "max_context_chars",
            "expert_hierarchy_max_branches", "expert_hierarchy_display_names_enabled",
        )},
        "answering": {key: values[key] for key in (
            "answering_llm_temperature", "answering_chain_of_thought_enabled",
        )},
        "llm": {key: values[key] for key in (
            "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens", "llm_top_p", "llm_timeout",
        )} | {"adapter": deps["llm"]},
        "embeddings": {key: values[key] for key in (
            "embeddings_model_name", "embeddings_query_instruction", "embeddings_query_max_utf8_bytes",
            "embeddings_max_attempts", "embeddings_attempt_timeout_seconds", "embeddings_total_deadline_seconds",
        )} | {"adapter": deps["embeddings"]},
        "knowledge_store": {"distance_fn": values["vector_db_distance_fn"], "adapter": deps["knowledge_store"]},
        "hybrid": {key: values[key] for key in (
            "hybrid_retrieval_enabled", "hybrid_dense_weight", "hybrid_lexical_weight", "hybrid_rrf_k", "hybrid_max_terms", "hybrid_min_term_len",
        )} | {"strategy": deps["hybrid"]},
        "rerank": {key: values[key] for key in ("rerank_enabled", "rerank_candidate_n", "rerank_top_k", "rerank_lexical_weight")} | {"adapter": deps["reranker"]},
        "routing": {key: values[key] for key in ("routing_enabled", "routing_simple_n_results", "routing_complex_n_results", "routing_complex_context_chars")} | {"router": deps["router"], "table": deps["routing_table"]},
        "faithfulness": {"enabled": values["faithfulness_validation_enabled"], "validator": deps["faithfulness"]},
        "rewrite": {key: values[key] for key in ("query_rewrite_gating_enabled", "query_rewrite_max_expansion_ratio", "query_rewrite_max_history_turns", "query_rewrite_max_history_chars", "query_rewrite_max_utf8_bytes")} | {"policy": deps["rewrite"]},
    }


def expert_composition_fingerprint(composition: ResolvedExpertComposition) -> str:
    """Hash the immutable public authority without plumbing or a re-resolution."""
    serialized = json.dumps(expert_composition_descriptor(composition), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def expert_full_composition_fingerprint(invariant: str, mode: str) -> str:
    if mode not in {"flat", "hierarchical"}:
        raise ValueError("Expert composition mode must be flat or hierarchical")
    if len(invariant) != 64 or any(c not in "0123456789abcdef" for c in invariant):
        raise ValueError("Expert invariant fingerprint must be a SHA-256 hex digest")
    payload = {"schema": "expert-composition/v7", "invariant": invariant, "mode": mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
