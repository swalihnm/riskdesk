"""Synthetic market data: 750 days of correlated, fat-tailed factor moves with two stress episodes.

No real market data is used. Everything is generated from a seed and cached to Parquet so that
tests never touch the network. The 'current' snapshot is the end of the generated history.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np

EQUITIES = {  # name: (initial spot, base implied vol)
    "EQ_ALPHA": (120.0, 0.22),
    "EQ_BETA": (65.0, 0.27),
    "EQ_GAMMA": (240.0, 0.19),
    "EQ_DELTA": (38.0, 0.31),
    "EQ_EPSILON": (95.0, 0.24),
    "EQ_ZETA": (180.0, 0.21),
}
FX = {  # name: (initial spot in USD per unit, foreign rate)
    "FX_EURUSD": (1.08, 0.025),
    "FX_GBPUSD": (1.27, 0.035),
    "FX_AUDUSD": (0.66, 0.040),
}
DAILY_SIGMA = {**{k: 0.011 for k in EQUITIES}, **{k: 0.005 for k in FX}}
N_DAYS = 750
SEED = 42
STRESS_EPISODES = [(200, 210, -0.02, 2.5), (520, 530, -0.015, 2.0)]  # (start, end, drift/day, vol pts/day)


@dataclass
class Market:
    spot_names: list
    vol_names: list
    rets: np.ndarray  # (T, n_spot) daily log returns
    dvol: np.ndarray  # (T, n_vol) daily implied-vol changes in vol points
    spots: dict
    vols: dict  # decimal implied vol (current)
    prev_close: dict
    daily_sigma: dict
    rd: float = 0.04
    rf: dict = field(default_factory=dict)
    asof: str = ""
    quality_flags: dict = field(default_factory=dict)  # underlying -> list of flags

    @property
    def factor_names(self) -> list:
        return [f"ret:{n}" for n in self.spot_names] + [f"dvol:{v}" for v in self.vol_names]

    def spot_index(self, name: str) -> int:
        return self.spot_names.index(name)

    def vol_index(self, name: str) -> int:
        return self.vol_names.index(name)

    def copy(self) -> "Market":
        return copy.deepcopy(self)


def generate_history(n_days: int = N_DAYS, seed: int = SEED):
    rng = np.random.default_rng(seed)
    eq_names, fx_names = list(EQUITIES), list(FX)
    spot_names = eq_names + fx_names
    n_spot = len(spot_names)

    # One-factor model: common shock loads 0.7 on equities, 0.3 on FX (positive definite by construction)
    loadings = np.array([0.7] * len(eq_names) + [0.3] * len(fx_names))
    idio = np.sqrt(1 - loadings**2)
    sig_d = np.array([DAILY_SIGMA[n] for n in spot_names])

    df = 5  # Student-t tails
    t_scale = np.sqrt((df - 2) / df)
    common = rng.standard_t(df, size=(n_days, 1)) * t_scale
    eps = rng.standard_t(df, size=(n_days, n_spot)) * t_scale
    rets = (loadings * common + idio * eps) * sig_d

    # Stress episodes: negative drift and extra vol in the equity block
    for start, end, drift, _ in STRESS_EPISODES:
        rets[start:end, : len(eq_names)] += drift

    vol_names = eq_names
    corr_common = common[:, 0]
    dvol = np.zeros((n_days, len(vol_names)))
    for j in range(len(vol_names)):
        dvol[:, j] = -0.6 * corr_common + 0.4 * rng.standard_normal(n_days)  # vol points / day
    for start, end, _, vol_pts in STRESS_EPISODES:
        dvol[start:end, :] += vol_pts
    return spot_names, vol_names, rets, dvol


def _snapshot(spot_names, vol_names, rets, dvol, rd=0.04) -> Market:
    init_spot = {**{k: v[0] for k, v in EQUITIES.items()}, **{k: v[0] for k, v in FX.items()}}
    base_vol = {k: v[1] for k, v in EQUITIES.items()}
    log_path = np.cumsum(rets, axis=0)
    spots_now = {n: float(init_spot[n] * np.exp(log_path[-1, i])) for i, n in enumerate(spot_names)}
    prev = {n: float(init_spot[n] * np.exp(log_path[-2, i])) for i, n in enumerate(spot_names)}
    vol_path = np.cumsum(dvol, axis=0) / 100.0
    vols_now = {n: float(np.clip(base_vol[n] + vol_path[-1, j], 0.05, 1.5)) for j, n in enumerate(vol_names)}
    sigma = {n: float(np.std(rets[:, i])) for i, n in enumerate(spot_names)}
    return Market(
        spot_names=spot_names,
        vol_names=vol_names,
        rets=rets,
        dvol=dvol,
        spots=spots_now,
        vols=vols_now,
        prev_close=prev,
        daily_sigma=sigma,
        rd=rd,
        rf={k: v[1] for k, v in FX.items()},
        asof=date(2026, 11, 12).isoformat(),
    )


def load_market(cache_path: str | None = None, n_days: int = N_DAYS, seed: int = SEED) -> Market:
    """The market the engine uses. Real data by default (data/real/, see riskdesk/engine/realdata.py).

    Set RISKDESK_DATA=synthetic to use the seeded synthetic market instead. cache_path applies only to the
    synthetic market.
    """
    if os.environ.get("RISKDESK_DATA", "real").strip().lower() == "synthetic":
        return load_synthetic(cache_path, n_days, seed)
    from riskdesk.engine.realdata import load_market as load_real_market
    return load_real_market()


def load_synthetic(cache_path: str | None = None, n_days: int = N_DAYS, seed: int = SEED) -> Market:
    """Load the cached history if present, otherwise generate it and cache it to Parquet."""
    import pandas as pd

    if cache_path and os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
        spot_names = [c[4:] for c in df.columns if c.startswith("ret_")]
        vol_names = [c[5:] for c in df.columns if c.startswith("dvol_")]
        rets = df[[f"ret_{n}" for n in spot_names]].to_numpy()
        dvol = df[[f"dvol_{n}" for n in vol_names]].to_numpy()
    else:
        spot_names, vol_names, rets, dvol = generate_history(n_days, seed)
        if cache_path:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            cols = {f"ret_{n}": rets[:, i] for i, n in enumerate(spot_names)}
            cols.update({f"dvol_{n}": dvol[:, j] for j, n in enumerate(vol_names)})
            pd.DataFrame(cols).to_parquet(cache_path)
    return _snapshot(spot_names, vol_names, rets, dvol)


def apply_regime_shock(market: Market, underlyings: list, last_n: int, mult: float,
                       vol_jump_pts: float = 0.0) -> Market:
    """Inject a shock: scale the last N days of moves for the given underlyings, and optionally jump implied vol.

    Used by the golden-set generator to create breaches with a known driver.
    """
    m = market.copy()
    for u in underlyings:
        if u in m.spot_names:
            i = m.spot_index(u)
            m.rets[-last_n:, i] *= mult
        if u in m.vol_names:
            j = m.vol_index(u)
            m.dvol[-last_n:, j] *= mult
            m.vols[u] = float(np.clip(m.vols[u] + vol_jump_pts / 100.0, 0.05, 1.5))
    return m


def apply_bad_tick(market: Market, underlying: str, multiplier: float, flag: str = "jump_check_failed") -> Market:
    """Inject a bad price on the current day only (a data-quality error, not a market move)."""
    m = market.copy()
    m.spots[underlying] = m.prev_close[underlying] * multiplier
    m.quality_flags.setdefault(underlying, []).append(flag)
    return m
