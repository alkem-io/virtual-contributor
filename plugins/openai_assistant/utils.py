"""Utility functions for the OpenAI Assistant plugin."""

from __future__ import annotations

import re


def strip_citations(text: str) -> str:
    """Strip citation annotations from OpenAI assistant responses.

    Removes patterns like 【4:0†source】 from the text.
    """
    return re.sub(r"【[^】]*】", "", text).strip()
