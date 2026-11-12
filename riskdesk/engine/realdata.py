"""Real market data for the risk engine.

Sources (all free; no account or API key):
- Equity ETF closes: Yahoo Finance, via the yfinance library (unofficial; subject to rate limits and terms of use).
- EUR cross rates: European Central Bank reference rates (USD, GBP and AUD per EUR), via the ECB data portal.
- Rates: Federal Reserve Economic Data (FRED) series: 1-year US Treasury yield (discounting) and 3-month
  interbank rates for the euro area, UK and Australia (foreign rates for the FX forwards). The 3-month series
  are monthly and lag by a few months.
- Cross-check only: CBOE VIX close (not used in the calculations).

Volatility is a proxy. No free source gives implied volatility for each ETF. The engine uses 21-day realised
volatility, and its daily change, as the implied-volatility factor. The VIX is recorded for comparison.

The fetched prices and rates are committed in data/real/ with their provenance, so the project runs offline
and results are reproducible. Refresh with scripts/fetch_real_data.py.
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from riskdesk.config import DATA_DIR
from riskdesk.engine.market import Market

REAL_DIR = os.path.join(DATA_DIR, "real")
PRICES_PATH = os.path.join(REAL_DIR, "prices.parquet")
PROVENANCE_PATH = os.path.join(REAL_DIR, "provenance.json")

EQUITY_TICKERS = ["SPY", "QQQ", "XLF", "XLE", "XLV", "IWM"]
FX_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD"]
# foreign 3-month rate series for each pair (FRED)
FOREIGN_RATE_SERIES = {"EURUSD": "IR3TIB01EZM156N", "GBPUSD": "IR3TIB01GBM156N", "AUDUSD": "IR3TIB01AUM156N"}
DOLLAR_RATE_SERIES = "DGS1"
VOL_WINDOW = 21
TRADING_DAYS = 252
START = "2021-11-01"

ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A?format=csvdata&startPeriod={start}"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def _ecb_series(ccy: str, start: str) -> pd.Series:
    import httpx
    r = httpx.get(ECB_URL.format(ccy=ccy, start=start), timeout=120, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(df["OBS_VALUE"].values, index=pd.to_datetime(df["TIME_PERIOD"]), name=ccy, dtype=float)
    return s.dropna()


def _fred_series(series: str) -> pd.Series:
    import httpx
    r = httpx.get(FRED_URL.format(series=series), timeout=120, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), na_values=["."])
    date_col = df.columns[0]
    s = pd.Series(df[series].values, index=pd.to_datetime(df[date_col]), name=series, dtype=float)
    return s.dropna()


def _vix_last() -> tuple[str, float] | None:
    import httpx
    try:
        r = httpx.get(VIX_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        last = df.iloc[-1]
        return str(last["DATE"]), float(last["CLOSE"])
    except Exception:
        return None


def fetch(start: str = START) -> tuple[pd.DataFrame, dict]:
    """Downloads the prices and rates. Returns (prices, provenance). Writes nothing."""
    import yfinance as yf

    eq = yf.download(EQUITY_TICKERS, start=start, interval="1d", progress=False, auto_adjust=True)["Close"]
    eq = eq[EQUITY_TICKERS].dropna()
    usd_per_eur = _ecb_series("USD", start)
    gbp_per_eur = _ecb_series("GBP", start)
    aud_per_eur = _ecb_series("AUD", start)
    fx = pd.concat([usd_per_eur, usd_per_eur / gbp_per_eur, usd_per_eur / aud_per_eur], axis=1).dropna()
    fx.columns = ["EURUSD", "GBPUSD", "AUDUSD"]
    prices = eq.join(fx, how="inner").dropna()
    prices.index = pd.to_datetime(prices.index).tz_localize(None).normalize()
    prices = prices[~prices.index.duplicated()].sort_index()

    dollar = _fred_series(DOLLAR_RATE_SERIES)
    foreign = {p: _fred_series(sid) for p, sid in FOREIGN_RATE_SERIES.items()}
    vix = _vix_last()
    provenance = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": start,
        "last_price_date": prices.index[-1].date().isoformat(),
        "equity_tickers": EQUITY_TICKERS,
        "fx_pairs": FX_PAIRS,
        "sources": {
            "equities": "Yahoo Finance via yfinance (unofficial)",
            "fx": "ECB reference rates: USD, GBP and AUD per EUR; GBPUSD and AUDUSD derived by cross",
            "dollar_rate": f"FRED {DOLLAR_RATE_SERIES} (1-year Treasury, percent)",
            "foreign_rates": {p: f"FRED {sid} (3-month interbank, monthly)" for p, sid in FOREIGN_RATE_SERIES.items()},
            "vix_cross_check": "CBOE VIX_History.csv (not used in calculations)",
        },
        "rd": float(dollar.iloc[-1]) / 100.0,
        "rd_date": dollar.index[-1].date().isoformat(),
        "rf": {p: float(s.iloc[-1]) / 100.0 for p, s in foreign.items()},
        "rf_dates": {p: s.index[-1].date().isoformat() for p, s in foreign.items()},
        "vix_last": {"date": vix[0], "close": vix[1]} if vix else None,
        "volatility_proxy": f"{VOL_WINDOW}-day realised volatility, annualised; factor is its daily change in vol points",
    }
    return prices, provenance


def save(prices: pd.DataFrame, provenance: dict) -> None:
    os.makedirs(REAL_DIR, exist_ok=True)
    prices.to_parquet(PRICES_PATH)
    with open(PROVENANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)


def build_market(prices: pd.DataFrame, provenance: dict) -> Market:
    spot_names = EQUITY_TICKERS + FX_PAIRS
    px = prices[spot_names].astype(float)
    rets_all = np.log(px).diff().dropna()
    eq_rets = rets_all[EQUITY_TICKERS]
    vol_all = eq_rets.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)  # annualised, decimal
    dvol_all = 100.0 * vol_all.diff()  # vol points per day
    usable = dvol_all.dropna().index
    rets = rets_all.loc[usable]
    dvol = dvol_all.loc[usable]
    spots = {n: float(px[n].iloc[-1]) for n in spot_names}
    prev = {n: float(px[n].iloc[-2]) for n in spot_names}
    vols = {n: float(np.clip(vol_all[n].iloc[-1], 0.05, 1.5)) for n in EQUITY_TICKERS}
    sigma = {n: float(rets_all[n].std()) for n in spot_names}
    return Market(
        spot_names=spot_names,
        vol_names=list(EQUITY_TICKERS),
        rets=rets[spot_names].to_numpy(),
        dvol=dvol[EQUITY_TICKERS].to_numpy(),
        spots=spots,
        vols=vols,
        prev_close=prev,
        daily_sigma=sigma,
        rd=float(provenance["rd"]),
        rf={p: float(provenance["rf"][p]) for p in FX_PAIRS},
        asof=prices.index[-1].date().isoformat(),
    )


def load_market() -> Market:
    prices = pd.read_parquet(PRICES_PATH)
    with open(PROVENANCE_PATH, encoding="utf-8") as f:
        provenance = json.load(f)
    return build_market(prices, provenance)
