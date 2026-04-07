"""RAGAS metric configuration with LangChain LLM/Embeddings wrappers."""

from __future__ import annotations

from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics import (
    AnswerRelevancy,
    Faithfulness,
    LLMContextPrecisionWithoutReference,
    LLMContextRecall,
)


def create_evaluator_llm(langchain_chat_model) -> LangchainLLMWrapper:
    """Wrap the pipeline's own LangChain chat model for RAGAS evaluation."""
    return LangchainLLMWrapper(langchain_chat_model)


def create_evaluator_embeddings(langchain_embeddings) -> LangchainEmbeddingsWrapper:
    """Wrap the pipeline's own LangChain embeddings for RAGAS AnswerRelevancy."""
    return LangchainEmbeddingsWrapper(langchain_embeddings)


def create_metrics(
    langchain_chat_model,
    langchain_embeddings,
) -> list:
    """Create the four core RAGAS metrics using the pipeline's own LLM as judge.

    Returns: [Faithfulness, AnswerRelevancy, LLMContextPrecisionWithoutReference, LLMContextRecall]
    """
    evaluator_llm = LangchainLLMWrapper(langchain_chat_model)
    evaluator_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

    return [
        Faithfulness(llm=evaluator_llm),
        AnswerRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),
        LLMContextPrecisionWithoutReference(llm=evaluator_llm),
        LLMContextRecall(llm=evaluator_llm),
    ]
