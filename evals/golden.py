"""Golden set: breach scenarios built by injecting a known cause into the synthetic market or limits.

Because the injection is known before the agent runs, scoring is objective. Six scenario types:
  single_position_vol   one underlying's history is shocked (implied-vol jump plus large moves)
  correlated_fx         one FX pair is shocked hard and the others mildly, so FX desk breaches
  data_quality          a bad tick on a held cash equity: must be called a data issue, not a market move
  limit_error           a hard limit set far below baseline: must be called a limit error
  multi_breach          two desks shocked at very different sizes: the larger must rank first
  ambiguous             two underlyings shocked equally: the top two drivers are close, so escalate

Ground truth fields: expected_label, expected_driver (underlying or None), expected_escalate, breach_desk.
"""

from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402
from riskdesk.engine.limits import _round_up  # noqa: E402
from riskdesk.engine.market import EQUITIES, FX, apply_bad_tick, apply_regime_shock  # noqa: E402
from riskdesk.engine.risk import component_var_by_underlying  # noqa: E402
from riskdesk.engine.book import positions_by_desk  # noqa: E402
from riskdesk.tools import Session  # noqa: E402

TYPES = ["single_position_vol", "correlated_fx", "data_quality", "limit_error", "multi_breach", "ambiguous"]


def _desk_vol_underlyings(session: Session, desk: str) -> list[str]:
    """Vol underlyings on the desk, largest component VaR first."""
    ps = positions_by_desk(session.book, desk)
    comp = component_var_by_underlying(ps, session.market)
    return [u for u in comp if u in session.market.vol_names]


def _largest_exposure(session: Session, desk: str, names: list[str]) -> str | None:
    """The desk's largest exposure among `names`. Shocking a small exposure cannot breach the desk."""
    ps = positions_by_desk(session.book, desk)
    comp = component_var_by_underlying(ps, session.market)
    ranked = [u for u in comp if u in names]
    return ranked[0] if ranked else None


def build_scenario(kind: str, i: int, base: Session, rng: random.Random, k: float = 1.0) -> dict:
    """k scales the injection size. generate() raises k until the intended desk actually breaches."""
    eq = list(EQUITIES)
    fx = list(FX)
    if kind == "single_position_vol":
        desk = rng.choice(["DESK_EQ", "DESK_VOL"])
        u = _largest_exposure(base, desk, list(base.market.vol_names)) or rng.choice(eq)
        m = apply_regime_shock(base.market, [u], last_n=20, mult=1 + 3.0 * k, vol_jump_pts=15.0 * k)
        return {"kind": kind, "desk": desk, "shocked": [u], "market": m,
                "expected_label": "market_move", "expected_driver": u, "expected_escalate": False,
                "breach_desk": desk}
    if kind == "correlated_fx":
        pair = _largest_exposure(base, "DESK_FX", fx) or rng.choice(fx)
        m = apply_regime_shock(base.market, [pair], last_n=20, mult=1 + 4.0 * k)
        for other in fx:
            if other != pair:
                m = apply_regime_shock(m, [other], last_n=20, mult=1 + 0.5 * k)
        return {"kind": kind, "desk": "DESK_FX", "shocked": [pair], "market": m,
                "expected_label": "market_move", "expected_driver": pair, "expected_escalate": False,
                "breach_desk": "DESK_FX"}
    if kind == "data_quality":
        desk = rng.choice(["DESK_EQ", "DESK_VOL"])
        cash = [p for p in positions_by_desk(base.book, desk) if p.kind == "cash"]
        u = rng.choice(cash).underlying
        mult = 1 + rng.uniform(0.3, 0.5) * k
        m = apply_bad_tick(base.market, u, mult)
        return {"kind": kind, "desk": desk, "shocked": [u], "market": m,
                "expected_label": "data_issue", "expected_driver": None, "expected_escalate": True,
                "breach_desk": desk}
    if kind == "limit_error":
        desk = rng.choice(["DESK_EQ", "DESK_VOL", "DESK_FX"])
        return {"kind": kind, "desk": desk, "shocked": [], "market": base.market,
                "limit_override": {"desk": desk, "metric": "var99", "factor": rng.uniform(0.3, 0.45)},
                "expected_label": "limit_error", "expected_driver": None, "expected_escalate": True,
                "breach_desk": desk}
    if kind == "multi_breach":
        desk_a = rng.choice(["DESK_EQ", "DESK_VOL"])
        u_a = _largest_exposure(base, desk_a, list(base.market.vol_names)) or rng.choice(eq)
        pair = rng.choice(fx)
        m = apply_regime_shock(base.market, [u_a], last_n=20, mult=1 + 7.0 * k, vol_jump_pts=20.0 * k)
        m = apply_regime_shock(m, [pair], last_n=20, mult=1 + 1.0 * k)
        return {"kind": kind, "desk": desk_a, "shocked": [u_a, pair], "market": m,
                "expected_label": "market_move", "expected_driver": u_a, "expected_escalate": False,
                "breach_desk": desk_a}
    if kind == "ambiguous":
        # Construct the margin between the top two drivers. Even i: about 1.1 (ambiguous, must escalate).
        # Odd i: about 2.5 (negative control, must not escalate). The achieved margin is recorded.
        desk = rng.choice(["DESK_EQ", "DESK_VOL"])
        u1, u2 = rng.sample(eq[:3] if desk == "DESK_EQ" else eq[3:], 2)
        target = 1.1 if i % 2 == 0 else 2.5
        m1 = apply_regime_shock(base.market, [u1], last_n=20, mult=1 + 2.0 * k, vol_jump_pts=10.0 * k)
        best = None
        for m2 in np.geomspace(0.2, 40.0, 60):
            mk = apply_regime_shock(m1, [u2], last_n=20, mult=float(m2), vol_jump_pts=10.0 * k)
            mg = _margin(mk, desk, base)
            if best is None or abs(mg - target) < abs(best[0] - target):
                best = (mg, mk)
        margin, m = best
        return {"kind": kind, "desk": desk, "shocked": [u1, u2], "market": m,
                "designed_margin": float(margin), "target_margin": target,
                "expected_label": "market_move", "expected_driver": None,
                "expected_escalate": target < 1.25, "breach_desk": desk}
    raise ValueError(kind)


def _margin(market, desk: str, base: Session) -> float:
    comp = component_var_by_underlying(positions_by_desk(base.book, desk), market)
    vals = [v for v in comp.values() if v > 0]
    if len(vals) < 2:
        return 99.0
    return float(vals[0] / vals[1])


INTENSITIES = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]


def _breaches_on(sc: dict, base: Session) -> bool:
    from riskdesk.engine.limits import check_limits
    s = to_session(sc, base)
    rows = check_limits(base.book, s.market, s.limits)
    return any(r["desk"] == sc["breach_desk"] and r["status"] == "BREACH" for r in rows)


def generate(n: int = 100, seed: int = 2026) -> list[dict]:
    """Each scenario uses the smallest injection size (from INTENSITIES) that breaches its desk.

    Scenarios that cannot breach even at the largest size are kept and marked, so the miss is measured
    rather than hidden.
    """
    base = Session.base()
    rng = random.Random(seed)
    scenarios = []
    for i in range(n):
        kind = TYPES[i % len(TYPES)]
        state = rng.getstate()
        chosen = None
        for k in INTENSITIES:
            rng.setstate(state)
            sc = build_scenario(kind, i, base, rng, k=k)
            if kind == "limit_error" or _breaches_on(sc, base):
                chosen = (k, sc)
                break
        if chosen is None:
            rng.setstate(state)
            k = INTENSITIES[-1]
            chosen = (k, build_scenario(kind, i, base, rng, k=k))
            chosen[1]["injection_not_breaching"] = True
        k, sc = chosen
        sc["intensity"] = k
        sc["id"] = f"S{i:03d}-{kind}"
        scenarios.append(sc)
    return scenarios


def to_session(sc: dict, base: Session) -> Session:
    """Session for one scenario: the same book and limits, with the injected market or limit."""
    limits = json.loads(json.dumps(base.limits))
    lo = sc.get("limit_override")
    if lo:
        ref = limits[lo["desk"]]["limits"][lo["metric"]]
        limits[lo["desk"]]["limits"][lo["metric"]] = float(_round_up(
            limits[lo["desk"]]["baseline"][lo["metric"]] * lo["factor"]))
    return Session(market=sc["market"], book=base.book, limits=limits)


def serialisable(sc: dict) -> dict:
    return {k: v for k, v in sc.items() if k != "market"}


if __name__ == "__main__":
    from riskdesk.config import GOLDEN_PATH
    scs = generate()
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        for sc in scs:
            f.write(json.dumps(serialisable(sc)) + "\n")
    print("golden scenarios:", len(scs), "->", GOLDEN_PATH)
