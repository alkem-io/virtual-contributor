"""Tests for evaluation/metrics.py — RAGAS metric configuration and LLM wrapper setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from evaluation.metrics import create_metrics, create_evaluator_llm, create_evaluator_embeddings


class TestCreateEvaluatorLlm:
    def test_returns_langchain_llm_wrapper(self):
        mock_chat_model = MagicMock()
        wrapper = create_evaluator_llm(mock_chat_model)
        # LangchainLLMWrapper should wrap the provided chat model
        assert wrapper is not None

    def test_wraps_any_object(self):
        # LangchainLLMWrapper is permissive at construction time;
        # errors surface at invocation. Verify wrapper is created.
        wrapper = create_evaluator_llm(MagicMock())
        assert wrapper is not None


class TestCreateEvaluatorEmbeddings:
    def test_returns_langchain_embeddings_wrapper(self):
        mock_embeddings = MagicMock()
        wrapper = create_evaluator_embeddings(mock_embeddings)
        assert wrapper is not None


class TestCreateMetrics:
    def test_returns_four_metrics(self):
        mock_llm = MagicMock()
        mock_embeddings = MagicMock()

        with patch("evaluation.metrics.LangchainLLMWrapper") as MockLLMWrapper, \
             patch("evaluation.metrics.LangchainEmbeddingsWrapper") as MockEmbWrapper:
            MockLLMWrapper.return_value = MagicMock()
            MockEmbWrapper.return_value = MagicMock()
            metrics = create_metrics(mock_llm, mock_embeddings)

        assert len(metrics) == 4
        metric_names = {type(m).__name__ for m in metrics}
        assert "Faithfulness" in metric_names
        assert "AnswerRelevancy" in metric_names
        assert "LLMContextPrecisionWithoutReference" in metric_names
        assert "LLMContextRecall" in metric_names

    def test_metrics_use_provided_llm(self):
        mock_llm = MagicMock()
        mock_embeddings = MagicMock()

        with patch("evaluation.metrics.LangchainLLMWrapper") as MockLLMWrapper, \
             patch("evaluation.metrics.LangchainEmbeddingsWrapper") as MockEmbWrapper:
            mock_wrapper = MagicMock()
            MockLLMWrapper.return_value = mock_wrapper
            MockEmbWrapper.return_value = MagicMock()
            metrics = create_metrics(mock_llm, mock_embeddings)

        # Verify LLM wrapper was called with our model
        MockLLMWrapper.assert_called_once_with(mock_llm)
