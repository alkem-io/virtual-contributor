"""C-16: Expert composition descriptors are explicit and paired-run safe."""

from __future__ import annotations

import pytest

from core.config import BaseConfig
from plugins.expert.composition import (
    expert_composition_descriptor,
    expert_composition_fingerprint,
    expert_full_composition_fingerprint,
)


class _LLM:
    pass


class _Store:
    pass


class _Embeddings:
    pass


class _Reranker:
    pass


class _Router:
    pass


class _Table:
    pass


class _Validator:
    pass


class _Policy:
    pass


def _dependencies() -> dict:
    return {
        "llm": _LLM(), "knowledge_store": _Store(), "reranker": _Reranker(),
        "query_router": _Router(), "routing_table": _Table(),
        "faithfulness_validator": _Validator(), "rewrite_policy": _Policy(),
    }


def _config(**changes) -> BaseConfig:
    values = {
        "plugin_type": "expert", "llm_model": "model-a",
        "llm_base_url": "http://local",
        "expert_n_results": 8, "expert_min_score": 0.2,
        "expert_hierarchy_max_branches": 2,
        "expert_hierarchy_display_names_enabled": True,
        "answering_llm_temperature": 0.3,
        "hybrid_retrieval_enabled": True, "rerank_enabled": True,
        "routing_enabled": True, "faithfulness_validation_enabled": True,
        "query_rewrite_gating_enabled": True,
        "embeddings_model_name": "embedding-a",
    }
    values.update(changes)
    return BaseConfig(**values)


# This is the canonical enumerated set. Its groups mirror the descriptor:
# Expert retrieval, answering, effective LLM generation, composed embeddings,
# enabled hybrid/rerank/routing/validation strategies, and rewrite bounds.
# Credentials, endpoints, prompt/user data and the hierarchy experiment toggle
# are deliberately absent; adding a new descriptor field requires adding its
# mutation here in the same change.
EFFECTIVE_SETTING_MUTATIONS = [
    ("expert_n_results", 9), ("expert_min_score", 0.25),
    ("max_context_chars", 100_001), ("expert_hierarchy_max_branches", 3),
    ("expert_hierarchy_display_names_enabled", False),
    ("answering_llm_temperature", 0.4),
    ("answering_chain_of_thought_enabled", False),
    ("hybrid_dense_weight", 0.8), ("hybrid_lexical_weight", 0.8),
    ("hybrid_rrf_k", 61), ("hybrid_max_terms", 9), ("hybrid_min_term_len", 4),
    ("rerank_candidate_n", 21), ("rerank_top_k", 6),
    ("rerank_lexical_weight", 0.5), ("routing_simple_n_results", 2),
    ("routing_complex_n_results", 11),
    ("routing_complex_context_chars", 40_001),
    ("query_rewrite_max_expansion_ratio", 9.0),
    ("query_rewrite_max_history_turns", 19),
    ("query_rewrite_max_history_chars", 11_999),
    ("embeddings_query_max_utf8_bytes", 32_767),
    ("query_rewrite_max_utf8_bytes", 4_095),
    ("embeddings_max_attempts", 2),
    ("embeddings_attempt_timeout_seconds", 19),
    ("embeddings_total_deadline_seconds", 44),
    ("llm_provider", "openai"), ("llm_model", "model-b"),
    ("vector_db_distance_fn", "l2"),
    ("llm_temperature", 0.4), ("llm_max_tokens", 512),
    ("llm_top_p", 0.8), ("llm_timeout", 121),
    ("embeddings_model_name", "embedding-b"),
    ("embeddings_query_instruction", "retrieve:"),
    ("hybrid_retrieval_enabled", False), ("rerank_enabled", False),
    ("routing_enabled", False), ("faithfulness_validation_enabled", False),
    ("query_rewrite_gating_enabled", False),
]


@pytest.mark.parametrize(("field", "value"), EFFECTIVE_SETTING_MUTATIONS)
def test_each_effective_setting_mutation_changes_the_fingerprint(field, value) -> None:
    base = _config()
    changed = _config(**{field: value})
    assert expert_composition_fingerprint(base, _dependencies(), embeddings=_Embeddings()) != (
        expert_composition_fingerprint(changed, _dependencies(), embeddings=_Embeddings())
    )


@pytest.mark.parametrize("dependency", [
    "llm", "knowledge_store", "reranker", "query_router", "routing_table",
    "faithfulness_validator", "rewrite_policy",
])
def test_enabled_adapter_and_strategy_identities_affect_fingerprint(dependency) -> None:
    class Replacement:
        pass

    base_deps = _dependencies()
    replacement_deps = _dependencies()
    replacement_deps[dependency] = Replacement()
    assert expert_composition_fingerprint(_config(), base_deps, embeddings=_Embeddings()) != (
        expert_composition_fingerprint(_config(), replacement_deps, embeddings=_Embeddings())
    )


def test_composed_embeddings_adapter_identity_affects_fingerprint() -> None:
    class Replacement:
        pass

    assert expert_composition_fingerprint(
        _config(), _dependencies(), embeddings=_Embeddings(),
    ) != expert_composition_fingerprint(
        _config(), _dependencies(), embeddings=Replacement(),
    )


def test_independently_composed_runs_match_and_hierarchy_is_excluded() -> None:
    production = _dependencies()
    evaluation = _dependencies()
    flat = _config(expert_hierarchical_retrieval_enabled=False)
    hierarchy = _config(expert_hierarchical_retrieval_enabled=True)
    assert expert_composition_descriptor(flat, production, embeddings=_Embeddings()) == (
        expert_composition_descriptor(flat, evaluation, embeddings=_Embeddings())
    )
    assert expert_composition_fingerprint(flat, production, embeddings=_Embeddings()) == (
        expert_composition_fingerprint(hierarchy, evaluation, embeddings=_Embeddings())
    )


def test_credentials_endpoints_and_prompt_data_never_enter_descriptor() -> None:
    config = _config(
        llm_api_key="llm-secret", llm_base_url="https://user:pass@private.invalid",
        embeddings_api_key="embedding-secret", embeddings_endpoint="https://private.invalid",
    )
    rendered = repr(expert_composition_descriptor(config, _dependencies(), embeddings=_Embeddings()))
    assert "secret" not in rendered and "private.invalid" not in rendered


def test_dormant_embeddings_do_not_affect_the_fingerprint() -> None:
    assert expert_composition_fingerprint(
        _config(embeddings_model_name="dormant-a"), _dependencies(),
    ) == expert_composition_fingerprint(
        _config(embeddings_model_name="dormant-b"), _dependencies(),
    )


def test_rewrite_bounds_remain_effective_when_the_skip_gate_is_off() -> None:
    base = _config(query_rewrite_gating_enabled=False)
    changed = _config(
        query_rewrite_gating_enabled=False, query_rewrite_max_history_chars=11_999,
    )
    assert expert_composition_fingerprint(base, _dependencies()) != (
        expert_composition_fingerprint(changed, _dependencies())
    )


def test_effective_plugin_llm_override_changes_the_fingerprint() -> None:
    raw = _config(llm_model="global-model")
    effective = _config(llm_model="expert-override", llm_temperature=0.4)
    assert expert_composition_fingerprint(raw, _dependencies(), llm_config=raw) != (
        expert_composition_fingerprint(raw, _dependencies(), llm_config=effective)
    )


def test_invariant_fingerprint_excludes_only_hierarchy_mode() -> None:
    assert expert_composition_fingerprint(
        _config(expert_hierarchical_retrieval_enabled=False), _dependencies(), embeddings=_Embeddings(),
    ) == expert_composition_fingerprint(
        _config(expert_hierarchical_retrieval_enabled=True), _dependencies(), embeddings=_Embeddings(),
    )


def test_full_fingerprint_includes_hierarchy_mode() -> None:
    invariant = expert_composition_fingerprint(_config(), _dependencies(), embeddings=_Embeddings())
    assert expert_full_composition_fingerprint(invariant, "flat") != expert_full_composition_fingerprint(invariant, "hierarchical")


def test_v5_invariant_descriptor_contains_all_five_embedding_safety_controls() -> None:
    descriptor = expert_composition_descriptor(_config(), _dependencies(), embeddings=_Embeddings())
    assert set(descriptor["embeddings"]) >= {"query_max_utf8_bytes", "max_attempts", "attempt_timeout_seconds", "total_deadline_seconds"}
    assert "max_utf8_bytes" in descriptor["rewrite"]


@pytest.mark.parametrize(("field", "value"), [
    ("embeddings_query_max_utf8_bytes", 32_767), ("query_rewrite_max_utf8_bytes", 4_095),
    ("embeddings_max_attempts", 2), ("embeddings_attempt_timeout_seconds", 19),
    ("embeddings_total_deadline_seconds", 44),
])
def test_each_embedding_safety_control_mutation_changes_the_invariant_fingerprint(field, value) -> None:
    assert expert_composition_fingerprint(_config(), _dependencies(), embeddings=_Embeddings()) != expert_composition_fingerprint(_config(**{field: value}), _dependencies(), embeddings=_Embeddings())
