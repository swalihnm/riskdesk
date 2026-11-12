"""P&L attribution (PLA) test, following MAR32.42 of the Basel market-risk framework.

Two daily P&L series per desk over the window:
- HPL (hypothetical P&L): full revaluation of the desk's book under each actual daily move.
- RTPL (risk-theoretical P&L): what the risk model predicts for the same move. Here the model is the
  linear (delta and vega) approximation built from the analytic sensitivities.

The desk is compared on two metrics: the Spearman rank correlation of HPL and RTPL, and the
Kolmogorov-Smirnov statistic between their distributions. Zones, from MAR32.42 Table 2:
  green  correlation above 0.80 and KS below 0.09
  red    correlation below 0.70, or KS above 0.12
  amber  neither green nor red

Caveat: RTPL here is this project's linear model, not a bank's risk model. The zones show how well the
linear model explains the full revaluation for this synthetic book. They are not a regulatory result.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import ks_2samp, spearmanr

from riskdesk.engine.instruments import Position
from riskdesk.engine.market import Market
from riskdesk.engine.risk import WINDOW, factor_sensitivity_matrix, portfolio_pnl

GREEN_CORR, RED_CORR = 0.80, 0.70
GREEN_KS, RED_KS = 0.09, 0.12


def hypothetical_pnl(positions: list[Position], market: Market, window: int = WINDOW) -> np.ndarray:
    rets = market.rets[-window:]
    dvol = market.dvol[-window:]
    return portfolio_pnl(positions, market, rets, dvol)


def risk_theoretical_pnl(positions: list[Position], market: Market, window: int = WINDOW) -> np.ndarray:
    """Linear P&L: sensitivities (per risk factor) times the same daily factor moves."""
    S = factor_sensitivity_matrix(positions, market).sum(axis=0)
    X = np.hstack([market.rets[-window:], market.dvol[-window:]])
    return X @ S


def pla_zone(correlation: float, ks: float) -> str:
    if correlation < RED_CORR or ks > RED_KS:
        return "red"
    if correlation > GREEN_CORR and ks < GREEN_KS:
        return "green"
    return "amber"


def pla_test(positions: list[Position], market: Market, window: int = WINDOW) -> dict:
    hpl = hypothetical_pnl(positions, market, window)
    rtpl = risk_theoretical_pnl(positions, market, window)
    corr = float(spearmanr(hpl, rtpl).statistic) if np.std(hpl) > 0 and np.std(rtpl) > 0 else 0.0
    ks = float(ks_2samp(hpl, rtpl).statistic)
    return {"n": int(len(hpl)), "spearman": corr, "ks": ks, "zone": pla_zone(corr, ks),
            "hpl_std": float(np.std(hpl)), "rtpl_std": float(np.std(rtpl))}
