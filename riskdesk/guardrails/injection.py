"""Prompt-injection screen for any free text that reaches an LLM (incident notes, comments, retrieved text).

Flagged text is quarantined: it is never placed in a prompt. The patterns are a first line of defence,
not a complete one, and the test suite records which attacks are caught.
"""

from __future__ import annotations

import re

PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |any )?(previous|prior|above|your) (instructions|rules)",
    r"you are now\b",
    r"system prompt",
    r"reveal (your|the) (prompt|instructions|system)",
    r"approve (this|the) (limit|change|report)",
    r"(set|raise|increase) (the )?limit to",
    r"do not (escalate|report|flag)",
    r"<\s*/?\s*(system|assistant)\s*>",
]
_RX = [re.compile(p, re.IGNORECASE) for p in PATTERNS]


def screen(text: str) -> dict:
    hits = [p for p, rx in zip(PATTERNS, _RX) if rx.search(text)]
    return {"flagged": bool(hits), "matched": hits}
