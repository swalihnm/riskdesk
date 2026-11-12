"""VaR, Expected Shortfall, component VaR and Monte Carlo VaR.

Sign convention: losses are positive numbers. P&L arrays are positive for gains.

Methods
- historical: 1-day P&L from full revaluation of today's book under the last 250 daily moves
- parametric: delta-normal (linear, using analytic Greeks and the sample covariance of factor moves)
- monte_carlo: correlated normal shocks (Cholesky) with every option fully repriced
- component VaR: Euler allocation on the parametric model; contributions sum exactly to VaR
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from riskdesk.engine.instruments import Position, sensitivities, value
from riskdesk.engine.market import Market

WINDOW = 250
ALPHA_VAR = 0.99
ALPHA_ES = 0.975
MC_PATHS = 10_000


def _sigma_for(pos: Position, market: Market, dvol: np.ndarray) -> np.ndarray | None:
    if pos.kind != "option":
        return None
    j = market.vol_index(pos.underlying)
    return np.clip(market.vols[pos.underlying] + dvol[:, j] / 100.0, 0.01, 3.0)


def revalue(pos: Position, market: Market, rets: np.ndarray, dvol: np.ndarray) -> np.ndarray:
    """P&L of one position for each row of factor moves (full revaluation)."""
    i = market.spot_index(pos.underlying)
    S_now = market.spots[pos.underlying]
    S = S_now * np.exp(rets[:, i])
    sig_now = market.vols.get(pos.underlying)
    sig_new = _sigma_for(pos, market, dvol)
    v_now = value(pos, S_now, sig_now, market.rd)
    v_new = value(pos, S, sig_new if sig_new is not None else sig_now, market.rd)
    return np.asarray(v_new - v_now, dtype=float) * np.ones(len(rets))


def position_pnl(positions: list[Position], market: Market, rets: np.ndarray, dvol: np.ndarray) -> dict:
    return {p.id: revalue(p, market, rets, dvol) for p in positions}


def portfolio_pnl(positions: list[Position], market: Market, rets: np.ndarray, dvol: np.ndarray) -> np.ndarray:
    total = np.zeros(len(rets))
    for p in positions:
        total += revalue(p, market, rets, dvol)
    return total


def historical_window(market: Market, window: int = WINDOW):
    return market.rets[-window:], market.dvol[-window:]


def var_from_pnl(pnl: np.ndarray, alpha: float = ALPHA_VAR) -> float:
    return float(-np.quantile(pnl, 1 - alpha))


def es_from_pnl(pnl: np.ndarray, alpha: float = ALPHA_ES) -> float:
    q = np.quantile(pnl, 1 - alpha)
    tail = pnl[pnl <= q]
    return float(-tail.mean())


def historical_var(positions, market, alpha=ALPHA_VAR, window=WINDOW) -> float:
    rets, dvol = historical_window(market, window)
    return var_from_pnl(portfolio_pnl(positions, market, rets, dvol), alpha)


def historical_es(positions, market, alpha=ALPHA_ES, window=WINDOW) -> float:
    rets, dvol = historical_window(market, window)
    return es_from_pnl(portfolio_pnl(positions, market, rets, dvol), alpha)


def factor_sensitivity_matrix(positions: list[Position], market: Market) -> np.ndarray:
    """Matrix S with one row per position and one column per risk factor (dP/dfactor)."""
    n_spot = len(market.spot_names)
    n_f = n_spot + len(market.vol_names)
    out = np.zeros((len(positions), n_f))
    for r, p in enumerate(positions):
        sig = market.vols.get(p.underlying)
        s = sensitivities(p, market.spots[p.underlying], sig, market.rd)
        out[r, market.spot_index(p.underlying)] = s["delta_cash"]
        if p.kind == "option":
            out[r, n_spot + market.vol_index(p.underlying)] = s["vega_pts"]
    return out


def factor_covariance(market: Market, window: int = WINDOW) -> np.ndarray:
    rets, dvol = historical_window(market, window)
    X = np.hstack([rets, dvol])
    return np.cov(X, rowvar=False)


def parametric_var(positions, market, alpha=ALPHA_VAR, window=WINDOW) -> float:
    S = factor_sensitivity_matrix(positions, market).sum(axis=0)
    cov = factor_covariance(market, window)
    sigma = float(np.sqrt(max(S @ cov @ S, 0.0)))
    return float(norm.ppf(alpha) * sigma)


def parametric_es(positions, market, alpha=ALPHA_ES, window=WINDOW) -> float:
    S = factor_sensitivity_matrix(positions, market).sum(axis=0)
    cov = factor_covariance(market, window)
    sigma = float(np.sqrt(max(S @ cov @ S, 0.0)))
    return float(sigma * norm.pdf(norm.ppf(alpha)) / (1 - alpha))


def component_var(positions, market, alpha=ALPHA_VAR, window=WINDOW) -> dict:
    """Euler component VaR per position. Sum of contributions equals the parametric VaR."""
    M = factor_sensitivity_matrix(positions, market)
    S = M.sum(axis=0)
    cov = factor_covariance(market, window)
    port_var = float(max(S @ cov @ S, 1e-18))
    sigma = np.sqrt(port_var)
    contrib = norm.ppf(alpha) * (M @ cov @ S) / sigma
    return {p.id: float(c) for p, c in zip(positions, contrib)}


def component_var_by_underlying(positions, market, alpha=ALPHA_VAR, window=WINDOW) -> dict:
    comp = component_var(positions, market, alpha, window)
    by_u: dict = {}
    for p in positions:
        by_u[p.underlying] = by_u.get(p.underlying, 0.0) + comp[p.id]
    return dict(sorted(by_u.items(), key=lambda kv: kv[1], reverse=True))


def monte_carlo_var(positions, market, alpha=ALPHA_VAR, paths=MC_PATHS, window=WINDOW, seed=11):
    """Returns (VaR, ES97.5) from full repricing of correlated normal shocks."""
    cov = factor_covariance(market, window)
    rng = np.random.default_rng(seed)
    L = np.linalg.cholesky(cov + 1e-14 * np.eye(cov.shape[0]))
    Z = rng.standard_normal((paths, cov.shape[0])) @ L.T
    n_spot = len(market.spot_names)
    pnl = portfolio_pnl(positions, market, Z[:, :n_spot], Z[:, n_spot:])
    return var_from_pnl(pnl, alpha), es_from_pnl(pnl, ALPHA_ES)


def desk_risk_summary(positions, market) -> dict:
    """All headline measures for one desk. Used by the limit framework and the agents."""
    S = factor_sensitivity_matrix(positions, market).sum(axis=0)
    n_spot = len(market.spot_names)
    delta_by_u = {u: float(S[market.spot_index(u)]) for u in market.spot_names}
    vega_total = float(S[n_spot:].sum())
    return {
        "var99_hist": historical_var(positions, market),
        "es975_hist": historical_es(positions, market),
        "var99_param": parametric_var(positions, market),
        "vega_pts_total": vega_total,
        "delta_by_underlying": delta_by_u,
        "n_positions": len(positions),
    }
