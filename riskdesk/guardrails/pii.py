"""PII and confidential-data filter.

Presidio (default recognisers, en_core_web_lg) handles personal data such as emails, phone numbers and
person names. Custom recognisers add the synthetic trader and counterparty names used in this project,
since a bank's confidential names are not in any generic model. Set RISKDESK_PII=regex to skip Presidio.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

TRADER_NAMES = ["Okafor", "Lindqvist", "Mbeki", "Ferreira", "Tanaka"]
COUNTERPARTY_NAMES = ["Northwind Capital", "Halcyon Prime", "Meridian Clearing"]

_REGEX_RULES = [
    ("EMAIL_ADDRESS", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PHONE_NUMBER", re.compile(r"\+?\d[\d \-]{8,}\d")),
    ("TRADER_NAME", re.compile(r"\b(?:" + "|".join(TRADER_NAMES) + r")\b")),
    ("COUNTERPARTY", re.compile(r"\b(?:" + "|".join(map(re.escape, COUNTERPARTY_NAMES)) + r")\b")),
]


@lru_cache(maxsize=1)
def _presidio():
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

    engine = AnalyzerEngine()
    engine.registry.add_recognizer(PatternRecognizer(
        supported_entity="TRADER_NAME", name="trader",
        patterns=[Pattern("trader", r"\b(?:" + "|".join(TRADER_NAMES) + r")\b", 0.9)]))
    engine.registry.add_recognizer(PatternRecognizer(
        supported_entity="COUNTERPARTY", name="counterparty",
        patterns=[Pattern("cpty", r"\b(?:" + "|".join(map(re.escape, COUNTERPARTY_NAMES)) + r")\b", 0.9)]))
    return engine


def redact(text: str) -> dict:
    """Returns the redacted text and the entity types found. Redaction is never skipped, even on error."""
    found: list[str] = []
    use_presidio = os.environ.get("RISKDESK_PII", "presidio") == "presidio"
    if use_presidio:
        try:
            from presidio_anonymizer import AnonymizerEngine  # noqa: F401
            results = _presidio().analyze(text=text, language="en")
            spans = sorted(results, key=lambda r: r.start, reverse=True)
            for r in spans:
                found.append(r.entity_type)
                text = text[:r.start] + f"<{r.entity_type}>" + text[r.end:]
        except Exception:
            use_presidio = False
    if not use_presidio:
        for label, pat in _REGEX_RULES:
            if pat.search(text):
                found.append(label)
                text = pat.sub(f"<{label}>", text)
    return {"text": text, "entities": sorted(set(found))}
