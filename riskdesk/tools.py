"""Tool layer shared by the agents and the MCP server.

Every function here reads numbers from the risk engine. The LLM never sees a number that did not come
from one of these functions, and each call is written to the hash-chained audit log.
"""

from __future__ import annotations

import functools
import json
import math
import os
from dataclasses import dataclass

from riskdesk import audit
from riskdesk.config import CACHE_PATH, KB_DIR, LIMITS_PATH
from riskdesk.engine import limits as lim
from riskdesk.engine import risk
from riskdesk.engine.backtest import backtest_positions
from riskdesk.engine.book import DESKS, build_book, positions_by_desk
from riskdesk.engine.instruments import Position
from riskdesk.engine.market import Market, load_market
from riskdesk.engine.stress import worst_stress_loss
from riskdesk.guardrails.injection import screen

JUMP_SIGMAS = 6.0


@dataclass
class Session:
    market: Market
    book: list[Position]
    limits: dict

    @classmethod
    def base(cls) -> "Session":
        market = load_market(CACHE_PATH)
        return cls(market=market, book=build_book(market), limits=lim.load_limits(LIMITS_PATH))


_RAG = None


def _index():
    global _RAG
    if _RAG is None:
        from riskdesk.rag.index import HybridIndex, load_chunks
        _RAG = HybridIndex(load_chunks(KB_DIR))
    return _RAG


def audited(name: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(session: Session, *args, **kwargs):
            result = fn(session, *args, **kwargs)
            audit.append(f"tool.{name}", {"args": [str(a) for a in args], "kwargs": kwargs,
                                          "result_digest": _digest(result)})
            return result
        return wrapper
    return deco


def _digest(result) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:16]


@audited("limit_status")
def limit_status(s: Session) -> list[dict]:
    return lim.check_limits(s.book, s.market, s.limits)


@audited("compute_var")
def compute_var(s: Session, desk: str, method: str = "historical") -> dict:
    ps = positions_by_desk(s.book, desk)
    if method == "historical":
        v = risk.historical_var(ps, s.market)
    elif method == "parametric":
        v = risk.parametric_var(ps, s.market)
    elif method == "monte_carlo":
        v, _ = risk.monte_carlo_var(ps, s.market)
    else:
        raise ValueError("method must be historical, parametric or monte_carlo")
    return {"desk": desk, "method": method, "var99_1d": float(v)}


@audited("compute_es")
def compute_es(s: Session, desk: str) -> dict:
    ps = positions_by_desk(s.book, desk)
    return {"desk": desk, "es975_1d": float(risk.historical_es(ps, s.market))}


@audited("attribution")
def attribution(s: Session, desk: str) -> dict:
    ps = positions_by_desk(s.book, desk)
    by_u = risk.component_var_by_underlying(ps, s.market)
    total = sum(by_u.values())
    drivers = [{"underlying": u, "component_var": float(v),
                "share": float(v / total) if total else 0.0} for u, v in by_u.items()]
    top = drivers[0]["component_var"] if drivers else 0.0
    second = drivers[1]["component_var"] if len(drivers) > 1 else 0.0
    margin = float(top / second) if second > 0 else float("inf")
    return {"desk": desk, "total_component_var": float(total), "drivers": drivers,
            "margin_ratio": margin if math.isfinite(margin) else 99.0}


@audited("data_checks")
def data_checks(s: Session, desk: str) -> dict:
    held = sorted({p.underlying for p in positions_by_desk(s.book, desk)})
    flags = []
    for u in held:
        if u in s.market.spots and u in s.market.prev_close:
            move = math.log(s.market.spots[u] / s.market.prev_close[u])
            sig = s.market.daily_sigma[u]
            if abs(move) > JUMP_SIGMAS * sig:
                flags.append({"underlying": u, "flag": "jump_check_failed",
                              "move_sigmas": float(move / sig)})
        for f in s.market.quality_flags.get(u, []):
            flags.append({"underlying": u, "flag": f})
    return {"desk": desk, "underlyings": held, "flags": flags}


@audited("stress")
def stress(s: Session, desk: str) -> dict:
    res = worst_stress_loss(positions_by_desk(s.book, desk), s.market)
    return {"desk": desk, "worst_loss": res["loss"], "worst_scenario": res["scenario"]}


@audited("baseline")
def baseline(s: Session, desk: str) -> dict:
    return {"desk": desk, "baseline_var99": float(s.limits[desk]["baseline"]["var99"]),
            "hard_var99_limit": float(s.limits[desk]["limits"]["var99"])}


@audited("backtest")
def backtest(s: Session, desk: str | None = None) -> dict:
    ps = s.book if desk is None else positions_by_desk(s.book, desk)
    r = backtest_positions(ps, s.market)
    return {"desk": desk or "ALL", "n": r["n"], "exceptions": r["exceptions"],
            "traffic_light": r["traffic_light"], "kupiec_p_value": r["kupiec"]["p_value"]}


@audited("search_policy")
def search_policy(s: Session, query: str, k: int = 5) -> list[dict]:
    hits = _index().search(query, k)
    flagged = [h for h in hits if screen(h["text"])["flagged"]]
    return [{"id": h["id"], "heading": h["heading"], "text": h["text"][:600],
             "quarantined": h in flagged} for h in hits]


@audited("pla_test")
def pla_test(s: Session, desk: str) -> dict:
    from riskdesk.engine.pla import pla_test as _pla
    r = _pla(positions_by_desk(s.book, desk), s.market)
    return {"desk": desk, **r}
