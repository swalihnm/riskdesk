"""Limit framework: per desk, a hard limit and a warning level (80% of hard) on VaR, stress loss and vega.

Limits are calibrated from the baseline book (see `calibrate_limits`) with 50% headroom, so the
un-shocked book sits at roughly two-thirds utilisation. Limit changes are proposals only and go
through the approval gate in riskdesk/guardrails/approval.py.
"""

from __future__ import annotations

import json
import os

from riskdesk.engine.book import DESKS, positions_by_desk
from riskdesk.engine.instruments import Position
from riskdesk.engine.market import Market
from riskdesk.engine.risk import desk_risk_summary
from riskdesk.engine.stress import worst_stress_loss

WARNING_LEVEL = 0.8
HEADROOM = 1.5


def calibrate_limits(positions: list[Position], market: Market) -> dict:
    out = {}
    for desk in DESKS:
        ps = positions_by_desk(positions, desk)
        risk = desk_risk_summary(ps, market)
        stress = worst_stress_loss(ps, market)["loss"]
        out[desk] = {
            "baseline": {"var99": risk["var99_hist"], "stress_loss": stress,
                         "vega_pts": abs(risk["vega_pts_total"])},
            "limits": {
                "var99": _round_up(risk["var99_hist"] * HEADROOM),
                "stress_loss": _round_up(stress * HEADROOM),
                "vega_pts": _round_up(max(abs(risk["vega_pts_total"]), 1.0) * HEADROOM, step=100),
            },
        }
    return out


def _round_up(x: float, step: float = 1000.0) -> float:
    return float(-(-x // step) * step)


def load_limits(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_limits(limits: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(limits, f, indent=2)


def _status(util: float) -> str:
    if util > 1.0:
        return "BREACH"
    if util >= WARNING_LEVEL:
        return "WARNING"
    return "OK"


def check_limits(positions: list[Position], market: Market, limits: dict) -> list[dict]:
    rows = []
    for desk in DESKS:
        ps = positions_by_desk(positions, desk)
        risk = desk_risk_summary(ps, market)
        stress = worst_stress_loss(ps, market)["loss"]
        measures = {
            "var99": risk["var99_hist"],
            "stress_loss": stress,
            "vega_pts": abs(risk["vega_pts_total"]),
        }
        for metric, value in measures.items():
            limit = limits[desk]["limits"][metric]
            util = value / limit if limit else float("inf")
            rows.append({"desk": desk, "metric": metric, "value": float(value), "limit": float(limit),
                         "utilisation": float(util), "status": _status(util)})
    return rows


def breaches(rows: list[dict]) -> list[dict]:
    """Breaches ranked by severity (highest utilisation first)."""
    b = [r for r in rows if r["status"] == "BREACH"]
    return sorted(b, key=lambda r: r["utilisation"], reverse=True)
