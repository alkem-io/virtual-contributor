"""Prompt templates for the expert plugin."""

from __future__ import annotations

combined_expert_prompt = (
    "You are {vc_name}, an AI expert assistant. "
    "Use the following knowledge to answer the user's question.\n\n"
    "Knowledge:\n{knowledge}\n\n"
    "Question: {question}\n\n"
    "Provide a comprehensive and accurate answer based on the knowledge provided. "
    "If the knowledge doesn't contain enough information, say so clearly."
)

evaluation_prompt = (
    "You are evaluating the quality of an answer. Given the context and knowledge-based "
    "answer, determine if the answer adequately addresses the question.\n\n"
    "Context answer: {context_answer}\n"
    "Knowledge answer: {knowledge_answer}\n"
    "Question: {question}\n\n"
    "Provide a final consolidated answer."
)

input_checker_prompt = (
    "Analyze the following conversation to determine if the latest message is a "
    "follow-up question or a new topic.\n\n"
    "Conversation: {conversation}\n"
    "Latest message: {current_question}\n\n"
    "Respond with 'follow_up' or 'new_topic'."
)
