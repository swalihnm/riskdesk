"""Instrument pricing and analytic Greeks, vectorised over scenarios.

Conventions
- Spot factors are log returns; a position's `delta_cash` is dV/d(ln S).
- Vol factors are in vol points (1 point = 0.01 of implied vol); `vega_pts` is dV per vol point.
- `theta_day` is dV per calendar day; `rho_pct` is dV per 1% rate move.
- Synthetic simplification: options are European Black-Scholes with a flat rate and no dividends.
  FX forwards are valued as a foreign-currency bond minus a domestic bond, with flat rates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

RATE_DOMESTIC = 0.04  # flat USD rate, synthetic
DIV_YIELD = 0.0


@dataclass(frozen=True)
class Position:
    id: str
    desk: str
    kind: str  # "cash" | "option" | "fx_fwd"
    underlying: str
    qty: float = 0.0  # shares for cash/options (contracts x 100), foreign notional for fx_fwd
    strike: float = 0.0
    expiry: float = 0.0  # years
    is_call: bool = True
    rf: float = 0.0  # foreign rate, fx_fwd only

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _d1_d2(S, K, T, r, q, sig):
    T = np.maximum(T, 1e-8)
    sig = np.maximum(sig, 1e-6)
    sqrt_t = np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig**2) * T) / (sig * sqrt_t)
    return d1, d1 - sig * sqrt_t


def bs_price(S, K, T, r, q, sig, is_call: bool):
    S = np.asarray(S, dtype=float)
    sig = np.asarray(sig, dtype=float)
    d1, d2 = _d1_d2(S, K, T, r, q, sig)
    if is_call:
        price = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        intrinsic = np.maximum(S - K, 0.0)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
        intrinsic = np.maximum(K - S, 0.0)
    return np.where(T <= 0, intrinsic, price)


def bs_greeks(S, K, T, r, q, sig, is_call: bool) -> dict:
    """Analytic Black-Scholes Greeks per unit of option (not multiplied by quantity)."""
    S = np.asarray(S, dtype=float)
    sig = np.asarray(sig, dtype=float)
    d1, d2 = _d1_d2(S, K, T, r, q, sig)
    sqrt_t = np.sqrt(np.maximum(T, 1e-8))
    pdf_d1 = norm.pdf(d1)
    disc_q = np.exp(-q * T)
    disc_r = np.exp(-r * T)
    if is_call:
        delta = disc_q * norm.cdf(d1)
        theta = (-S * disc_q * pdf_d1 * sig / (2 * sqrt_t)
                 - r * K * disc_r * norm.cdf(d2) + q * S * disc_q * norm.cdf(d1))
        rho = K * T * disc_r * norm.cdf(d2)
    else:
        delta = disc_q * (norm.cdf(d1) - 1.0)
        theta = (-S * disc_q * pdf_d1 * sig / (2 * sqrt_t)
                 + r * K * disc_r * norm.cdf(-d2) - q * S * disc_q * norm.cdf(-d1))
        rho = -K * T * disc_r * norm.cdf(-d2)
    gamma = disc_q * pdf_d1 / (S * sig * sqrt_t)
    vega = S * disc_q * pdf_d1 * sqrt_t  # per 1.00 of vol
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def value(pos: Position, S, sig=None, rd: float = RATE_DOMESTIC):
    """Position value in USD for spot S (array or scalar) and implied vol sig (decimal)."""
    S = np.asarray(S, dtype=float)
    if pos.kind == "cash":
        return pos.qty * S
    if pos.kind == "option":
        return pos.qty * bs_price(S, pos.strike, pos.expiry, rd, DIV_YIELD, sig, pos.is_call)
    if pos.kind == "fx_fwd":
        T = pos.expiry
        return pos.qty * (S * np.exp(-pos.rf * T) - pos.strike * np.exp(-rd * T))
    raise ValueError(f"unknown instrument kind {pos.kind}")


def sensitivities(pos: Position, S: float, sig: float | None = None, rd: float = RATE_DOMESTIC) -> dict:
    """Position-level Greeks in risk-factor units."""
    zero = {"delta_cash": 0.0, "gamma_cash": 0.0, "vega_pts": 0.0, "theta_day": 0.0, "rho_pct": 0.0}
    if pos.kind == "cash":
        return {**zero, "delta_cash": pos.qty * S}
    if pos.kind == "fx_fwd":
        return {**zero, "delta_cash": pos.qty * S * np.exp(-pos.rf * pos.expiry)}
    if pos.kind == "option":
        g = bs_greeks(S, pos.strike, pos.expiry, rd, DIV_YIELD, sig, pos.is_call)
        return {
            "delta_cash": float(pos.qty * S * g["delta"]),
            "gamma_cash": float(pos.qty * S * S * g["gamma"]),
            "vega_pts": float(pos.qty * g["vega"] * 0.01),
            "theta_day": float(pos.qty * g["theta"] / 365.0),
            "rho_pct": float(pos.qty * g["rho"] * 0.01),
        }
    raise ValueError(pos.kind)
