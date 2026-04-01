"""Prompt templates for the guidance plugin."""

from __future__ import annotations

condense_prompt = (
    "Given the following conversation and a follow-up question, rephrase the "
    "follow-up question to be a standalone question.\n\n"
    "Chat History:\n{chat_history}\n\n"
    "Follow Up Question: {question}\n\n"
    "Standalone question:"
)

retrieve_prompt = (
    "Use the following pieces of context to answer the question. "
    "If you don't know the answer, just say that you don't know.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\n"
    "Answer in {language}. Respond in JSON format with keys: "
    "'answer' (string), 'sources' (list of objects with 'title', 'uri', 'score')."
)

generate_prompt = (
    "You are a helpful guidance assistant for the Alkemio platform. "
    "Based on the retrieved context, provide a helpful answer.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n\n"
    "Provide a clear, helpful answer."
)
