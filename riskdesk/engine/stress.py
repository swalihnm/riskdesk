"""Stress testing: named hypothetical scenarios plus the worst historical windows.

The named scenarios are *analogues* written for this synthetic book. They are not replays of the
real 2008, March 2020 or 2022 price paths. Replace them with real calibrated shocks when you have
licensed data.
"""

from __future__ import annotations

import numpy as np

from riskdesk.engine.instruments import Position
from riskdesk.engine.market import Market
from riskdesk.engine.risk import revalue

NAMED_SCENARIOS = [
    {"name": "Equity crash (2008-style analogue)", "kind": "hypothetical",
     "eq_shock": -0.35, "fx_shock": 0.0, "vol_pts": 25.0},
    {"name": "Liquidity shock (2020-style analogue)", "kind": "hypothetical",
     "eq_shock": -0.30, "fx_shock": -0.05, "vol_pts": 30.0},
    {"name": "Rate and FX shock (2022-style analogue)", "kind": "hypothetical",
     "eq_shock": -0.12, "fx_shock": -0.10, "vol_pts": 8.0},
    {"name": "EUR/USD -10%", "kind": "hypothetical",
     "eq_shock": 0.0, "fx_shock": -0.10, "vol_pts": 0.0, "only_first_fx": True},
    {"name": "Implied vol +15 pts", "kind": "hypothetical",
     "eq_shock": 0.0, "fx_shock": 0.0, "vol_pts": 15.0},
]


def _shock_vectors(market: Market, scen: dict):
    rets = np.zeros((1, len(market.spot_names)))
    dvol = np.zeros((1, len(market.vol_names)))
    only = [list(market.rf)[0]] if scen.get("only_first_fx") else None
    for i, n in enumerate(market.spot_names):
        if only is not None:
            if n in only:
                rets[0, i] = np.log(1 + scen.get("fx_shock", 0.0))
        elif n in market.vol_names:  # equities
            rets[0, i] = np.log(1 + scen.get("eq_shock", 0.0))
        elif n in market.rf:  # FX pairs
            rets[0, i] = np.log(1 + scen.get("fx_shock", 0.0))
    dvol[:, :] = scen.get("vol_pts", 0.0)
    return rets, dvol


def historical_windows(market: Market, n_worst: int = 3, horizon: int = 10) -> list[dict]:
    """Worst cumulative equity-block moves over `horizon` days in the full history."""
    eq_idx = [i for i, n in enumerate(market.spot_names) if n in market.vol_names]
    eq_log = market.rets[:, eq_idx].mean(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(eq_log)])
    window_ret = csum[horizon:] - csum[:-horizon]
    order = np.argsort(window_ret)
    out, used = [], []
    for start in order:
        if any(abs(start - u) < horizon for u in used):
            continue
        used.append(start)
        end = start + horizon
        out.append({
            "name": f"Worst {horizon}-day window, days {start}-{end} of history",
            "kind": "historical",
            "rets_sum": market.rets[start:end].sum(axis=0),
            "dvol_sum": market.dvol[start:end].sum(axis=0),
        })
        if len(out) == n_worst:
            break
    return out


def stress_positions(positions: list[Position], market: Market, include_historical: bool = True) -> list[dict]:
    """Returns one row per scenario with the P&L (negative = loss) for the given positions."""
    # Each shock is run in both directions: a book can be short a factor and lose on a rally.
    results = []
    cases = []
    for scen in NAMED_SCENARIOS:
        rets, dvol = _shock_vectors(market, scen)
        cases.append((scen["name"], scen["kind"], rets, dvol))
    if include_historical:
        for w in historical_windows(market):
            cases.append((w["name"], "historical", w["rets_sum"][None, :], w["dvol_sum"][None, :]))
    for name, kind, rets, dvol in list(cases):
        cases.append((f"{name} [reversed]", kind, -rets, -dvol))
    for name, kind, rets, dvol in cases:
        pnl = sum(revalue(p, market, rets, dvol) for p in positions)
        results.append({"name": name, "kind": kind, "pnl": float(np.asarray(pnl).ravel()[0])})
    return results


def worst_stress_loss(positions, market) -> dict:
    rows = stress_positions(positions, market)
    worst = min(rows, key=lambda r: r["pnl"])
    return {"loss": float(max(-worst["pnl"], 0.0)), "scenario": worst["name"], "all": rows}
