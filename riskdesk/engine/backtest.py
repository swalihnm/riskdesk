"""VaR backtesting: Kupiec proportion-of-failures test and Basel traffic-light zones.

Hypothetical P&L is the current book revalued under each actual daily move (the Basel convention),
compared with a 99% VaR forecast from the 250 days before that move.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import chi2

from riskdesk.engine.instruments import Position
from riskdesk.engine.market import Market
from riskdesk.engine.risk import WINDOW, portfolio_pnl, var_from_pnl


def kupiec_pof(n: int, x: int, p: float = 0.01) -> dict:
    """Kupiec (1995) likelihood-ratio test. n = observations, x = exceptions, p = expected exception rate."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    phat = x / n
    def _ll(q: float) -> float:
        if q in (0.0, 1.0):
            return 0.0
        return (n - x) * np.log(1 - q) + x * np.log(q)
    ll_null = (n - x) * np.log(1 - p) + (x * np.log(p) if x > 0 else 0.0)
    ll_alt = _ll(phat)
    lr = -2.0 * (ll_null - ll_alt)
    return {"n": n, "exceptions": x, "lr": float(lr), "p_value": float(chi2.sf(lr, df=1)),
            "reject_model_at_5pct": bool(chi2.sf(lr, df=1) < 0.05)}


def traffic_light(exceptions: int, n: int = 250) -> str:
    """Basel zones for 250 observations at 99%: green 0-4, amber 5-9, red 10+ (MAR32 Table 1)."""
    if n != 250:
        raise ValueError("Basel traffic-light thresholds are defined for 250 observations")
    if exceptions <= 4:
        return "green"
    if exceptions <= 9:
        return "amber"
    return "red"


def backtest_positions(positions: list[Position], market: Market, window: int = WINDOW,
                       alpha: float = 0.99) -> dict:
    total_days = len(market.rets)
    days = range(total_days - window, total_days)
    exceptions = 0
    rows = []
    for t in days:
        est_rets = market.rets[t - window:t]
        est_dvol = market.dvol[t - window:t]
        var_fc = var_from_pnl(portfolio_pnl(positions, market, est_rets, est_dvol), alpha)
        actual = float(portfolio_pnl(positions, market, market.rets[t:t + 1], market.dvol[t:t + 1])[0])
        is_exc = actual < -var_fc
        exceptions += int(is_exc)
        rows.append((t, var_fc, actual, is_exc))
    kupiec = kupiec_pof(len(days), exceptions, 1 - alpha)
    return {
        "n": len(days),
        "exceptions": exceptions,
        "traffic_light": traffic_light(exceptions, len(days)),
        "kupiec": kupiec,
    }
