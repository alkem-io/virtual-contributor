"""Stable, non-secret description of an Expert pipeline composition.

This deliberately describes behaviour, rather than serialising ``BaseConfig``.
The latter made paired evaluation fingerprints depend on dormant settings and
could accidentally grow to include a credential when configuration changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.config import BaseConfig


def _identity(value: object | None) -> str | None:
    """Return a wrapper-independent implementation identity."""
    while value is not None and type(value).__name__ in {
        "TracingKnowledgeStore", "TracedKnowledgeStore",
    }:
        value = getattr(value, "_delegate", None)
    if value is None:
        return None
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def expert_composition_descriptor(
    config: BaseConfig,
    dependencies: dict[str, Any],
    *,
    embeddings: object | None = None,
    llm_config: BaseConfig | None = None,
) -> dict[str, Any]:
    """Return the canonical Expert behaviour descriptor.

    The hierarchy enable flag is intentionally absent: it is the paired-run
    experiment variable. Display-name disclosure is retained because it
    changes the context supplied to the answering model.
    """
    effective_llm = llm_config or config
    descriptor: dict[str, Any] = {
        "expert": {
            "n_results": config.expert_n_results,
            "min_score": config.expert_min_score,
            "max_context_chars": config.max_context_chars,
            "hierarchy_max_branches": config.expert_hierarchy_max_branches,
            "hierarchy_display_names_enabled": (
                config.expert_hierarchy_display_names_enabled
            ),
        },
        "answering": {
            "temperature": config.answering_llm_temperature,
            "chain_of_thought_enabled": config.answering_chain_of_thought_enabled,
        },
        "llm": {
            "provider": effective_llm.llm_provider.value,
            "model": effective_llm.llm_model,
            "temperature": effective_llm.llm_temperature,
            "max_tokens": effective_llm.llm_max_tokens,
            "top_p": effective_llm.llm_top_p,
            "timeout": effective_llm.llm_timeout,
            "adapter": _identity(dependencies.get("llm")),
        },
        "knowledge_store": {
            "distance_fn": config.vector_db_distance_fn,
            "adapter": _identity(dependencies.get("knowledge_store")),
        },
    }
    if embeddings is not None:
        descriptor["embeddings"] = {
            "model": config.embeddings_model_name,
            "query_instruction": config.embeddings_query_instruction,
            "adapter": _identity(embeddings),
        }
    if config.hybrid_retrieval_enabled:
        descriptor["hybrid"] = {
            "dense_weight": config.hybrid_dense_weight,
            "lexical_weight": config.hybrid_lexical_weight,
            "rrf_k": config.hybrid_rrf_k,
            "max_terms": config.hybrid_max_terms,
            "min_term_len": config.hybrid_min_term_len,
            "strategy": "core.domain.hybrid_retrieval.retrieve",
        }
    if config.rerank_enabled:
        descriptor["rerank"] = {
            "candidate_n": config.rerank_candidate_n,
            "top_k": config.rerank_top_k,
            "lexical_weight": config.rerank_lexical_weight,
            "adapter": _identity(dependencies.get("reranker")),
        }
    if config.routing_enabled:
        descriptor["routing"] = {
            "simple_n_results": config.routing_simple_n_results,
            "complex_n_results": config.routing_complex_n_results,
            "complex_context_chars": config.routing_complex_context_chars,
            "router": _identity(dependencies.get("query_router")),
            "table": _identity(dependencies.get("routing_table")),
        }
    if config.faithfulness_validation_enabled:
        descriptor["faithfulness"] = {
            "validator": _identity(dependencies.get("faithfulness_validator")),
        }
    plugin_history = getattr(config, "history_length", None)
    effective_history_turns = (
        min(config.query_rewrite_max_history_turns, plugin_history)
        if plugin_history else config.query_rewrite_max_history_turns
    )
    descriptor["rewrite"] = {
        "gating_enabled": config.query_rewrite_gating_enabled,
        "max_expansion_ratio": config.query_rewrite_max_expansion_ratio,
        "max_history_turns": effective_history_turns,
        "max_history_chars": config.query_rewrite_max_history_chars,
        "policy": _identity(dependencies.get("rewrite_policy")),
    }
    return descriptor


def expert_composition_fingerprint(
    config: BaseConfig,
    dependencies: dict[str, Any],
    *,
    embeddings: object | None = None,
    llm_config: BaseConfig | None = None,
) -> str:
    """Hash the canonical descriptor without credentials, endpoints or data."""
    descriptor = expert_composition_descriptor(
        config, dependencies, embeddings=embeddings, llm_config=llm_config,
    )
    serialized = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def expert_full_composition_fingerprint(invariant: str, mode: str) -> str:
    """Bind a valid invariant composition fingerprint to its experiment mode."""
    if mode not in {"flat", "hierarchical"}:
        raise ValueError("Expert composition mode must be flat or hierarchical")
    if len(invariant) != 64 or any(c not in "0123456789abcdef" for c in invariant):
        raise ValueError("Expert invariant fingerprint must be a SHA-256 hex digest")
    payload = {"schema": "expert-composition/v4", "invariant": invariant, "mode": mode}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
