"""Synthetic trading book: 40 positions across 3 desks (equities cash, equity options, FX forwards)."""

from __future__ import annotations

import numpy as np

from riskdesk.engine.instruments import RATE_DOMESTIC, Position
from riskdesk.engine.market import EQUITIES, FX, Market

DESKS = ["DESK_EQ", "DESK_VOL", "DESK_FX"]
BOOK_SEED = 7


def build_book(market: Market, seed: int = BOOK_SEED) -> list[Position]:
    rng = np.random.default_rng(seed)
    eq_names = list(EQUITIES)
    fx_names = list(FX)
    positions: list[Position] = []

    # 6 cash equity positions: 3 on DESK_EQ, 3 on DESK_VOL
    for k, u in enumerate(eq_names):
        desk = "DESK_EQ" if k < 3 else "DESK_VOL"
        qty = float(rng.integers(2000, 20000))
        positions.append(Position(f"CASH-{u}", desk, "cash", u, qty=qty))

    # 22 equity options: 8 on DESK_EQ (first three names), 14 on DESK_VOL (all names)
    expiries = [0.25, 0.5, 1.0, 2.0]
    for n in range(22):
        if n < 8:
            desk, u = "DESK_EQ", eq_names[n % 3]
        else:
            desk, u = "DESK_VOL", eq_names[n % 6]
        s0 = market.spots[u]
        contracts = int(rng.integers(5, 60))
        sign = 1.0 if rng.random() < 0.5 else -1.0
        positions.append(Position(
            id=f"OPT-{n:02d}-{u}",
            desk=desk,
            kind="option",
            underlying=u,
            qty=sign * contracts * 100.0,
            strike=round(s0 * float(rng.uniform(0.85, 1.15)), 2),
            expiry=float(expiries[int(rng.integers(0, 4))]),
            is_call=bool(rng.random() < 0.5),
        ))

    # 12 FX forwards on DESK_FX, 4 per pair
    fwd_expiries = [0.25, 0.5, 1.0]
    for n in range(12):
        u = fx_names[n % 3]
        spot, rf = FX[u]
        T = float(fwd_expiries[int(rng.integers(0, 3))])
        fwd = market.spots[u] * np.exp((RATE_DOMESTIC - rf) * T)
        notional = float(rng.integers(1, 6)) * 1_000_000.0 * (1 if rng.random() < 0.6 else -1)
        positions.append(Position(
            id=f"FWD-{n:02d}-{u}",
            desk="DESK_FX",
            kind="fx_fwd",
            underlying=u,
            qty=notional,
            strike=round(float(fwd * rng.uniform(0.99, 1.01)), 5),
            expiry=T,
            rf=rf,
        ))
    return positions


def positions_by_desk(positions: list[Position], desk: str) -> list[Position]:
    return [p for p in positions if p.desk == desk]
