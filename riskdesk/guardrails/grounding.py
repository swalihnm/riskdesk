"""Numeric grounding: every number in a draft must appear in a tool output (or be a whitelisted constant).

This is the check that makes "the LLM never computes a risk number" enforceable. It is deliberately strict:
numbers are matched after rounding to the precision the draft used, and percentages are matched as x100.
"""

from __future__ import annotations

import re

# Constants that describe method, not results (confidence levels, window length, zone thresholds, etc.)
WHITELIST = {97.5, 99.0, 250.0, 80.0, 100.0, 10.0, 5.0, 4.0, 9.0, 0.0, 1.0, 2.0, 3.0, 6.0, 60.0, 20.0, 7.0}

# Tokens that are identifiers, not quantities: INC-0001, SS1/23, SR 26-2, 2026-11-12, etc.
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9]*[-/]\d[\w/.\-]*|\d{4}-\d{2}-\d{2}")  # no space: "is 107" must not be eaten
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")


def extract_numbers(text: str) -> list[tuple[str, float, int, bool]]:
    """Returns (raw token, value as written, decimals as written, is_percent) for every quantity in the text."""
    cleaned = _IDENT.sub(" ", text)
    out = []
    for m in _NUM.finditer(cleaned):
        raw = m.group(0)
        is_pct = raw.endswith("%")
        core = raw.rstrip("%").replace(",", "")
        decimals = len(core.split(".")[1]) if "." in core else 0
        out.append((raw, float(core), decimals, is_pct))
    return out


def allowed_values(tool_outputs: list) -> list[float]:
    """Flatten every numeric value a tool returned, plus its percentage form."""
    vals: list[float] = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            vals.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(tool_outputs)
    vals += [v * 100.0 for v in list(vals)]
    return vals


def _matches(value: float, decimals: int, pool: list[float]) -> bool:
    # Compare as written: "85%" is matched against 85 (a tool value of 0.85 is also offered as 85).
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(value - p) <= tol or abs(abs(value) - abs(p)) <= tol for p in pool)


def check_grounding(text: str, tool_outputs: list) -> dict:
    pool = allowed_values(tool_outputs) + list(WHITELIST)
    found = extract_numbers(text)
    unsupported = [raw for raw, value, dec, _pct in found if not _matches(value, dec, pool)]
    return {"numbers": len(found), "unsupported": unsupported, "ok": not unsupported}
