"""Prompt templates for the generic plugin."""

from __future__ import annotations

condenser_system_prompt = (
    "You are a helpful assistant that condenses conversation history into a single, "
    "clear, self-contained question. Given the conversation history and the latest "
    "question from the user, rephrase the latest question so that it can be understood "
    "without any prior context. Return only the rephrased question, nothing else."
)
