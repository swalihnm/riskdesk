# Real market data: sources, provenance and limits

Written for: a model-risk reviewer, and anyone reproducing the results. The values below are from `data/real/provenance.json` (fetched 12 November 2026, UTC).

## What is used

| Input | Used for | Source | Latest value | Date |
| --- | --- | --- | --- | --- |
| Closes: SPY, QQQ, XLF, XLE, XLV, IWM | Equity underlyings; spot and returns | Yahoo Finance via `yfinance` (adjusted closes) | SPY 759.81 | 11 Nov 2026 |
| EUR/USD | FX underlying | ECB reference rate (USD per EUR) | 1.1127 | 11 Nov 2026 |
| GBP/USD | FX underlying | ECB rates (USD per EUR divided by GBP per EUR) | derived | 11 Nov 2026 |
| AUD/USD | FX underlying | ECB rates (USD per EUR divided by AUD per EUR) | derived | 11 Nov 2026 |
| 1-year US Treasury | Discount rate (`rd`) | FRED `DGS1` | 4.38% | 9 Nov 2026 |
| 3-month interbank, euro area | Foreign rate for EUR/USD forwards | FRED `IR3TIB01EZM156N` (monthly) | 2.03% | 1 Jan 2026 |
| 3-month interbank, UK | Foreign rate for GBP/USD forwards | FRED `IR3TIB01GBM156N` (monthly) | 3.71% | 1 Jan 2026 |
| 3-month interbank, Australia | Foreign rate for AUD/USD forwards | FRED `IR3TIB01AUM156N` (monthly) | 4.51% | 1 Aug 2026 |
| CBOE VIX | Cross-check only; not used in any calculation | CBOE `VIX_History.csv` | 17.49 | 11 Nov 2026 |

Sample: 1,251 trading days from 1 November 2021 to 11 November 2026. The first 21 days are used to start the volatility estimate, leaving 1,229 daily observations. The VaR window is the last 250 of them.

## Assumptions the reviewer should know about

1. **Volatility is a proxy.** No free source gives implied volatility for each ETF. The engine uses 21-day realised volatility, annualised, and its daily change in vol points as the implied-volatility factor. Real implied volatility usually sits above realised, so option vegas and vol-related limits are likely understated. The VIX cross-check is recorded so the gap can be seen.
2. **The desk structure is illustrative.** The book keeps the synthetic generator's sizes: 2,000 to 20,000 shares per cash position and 100 to 6,000 option shares. On ETFs priced near 750, these are much larger exposures than the synthetic book had. The limits are calibrated on this book, so the limits and exposures are internally consistent but are not a real portfolio.
3. **Option pricing is Black-Scholes.** Options on the ETFs are priced with the realised-volatility proxy, flat rates and no dividend yield. ETF dividends are ignored, so the equity forwards and option prices are approximate.
4. **Foreign rates are monthly.** The three foreign 3-month rates are monthly FRED series and lag by up to ten months. They enter only the FX forward valuation.
5. **Yahoo Finance is unofficial.** The `yfinance` library calls Yahoo's public endpoints. It can break, return rate-limit errors, or change without notice, and its terms of use apply. The stored copy in `data/real/` is the version the results were produced from.
6. **Dates.** The ECB and the equity exchanges publish on different holidays. The series are joined on common dates only, so a few days in the sample are dropped.

## What is checked

- No gaps longer than five days, and no duplicate dates.
- The largest single-day moves are visible in the data. The only daily move above 10% in the sample is QQQ, +11.3% on 9 April 2025, a day of very large market moves. Its size is a real observation, not a data error.
- The latest SPY close and EUR/USD agree with a separate download made the same day.

## How the results depend on this

- All results in `evals/results/` labelled as real were produced from `data/real/`.
- Results labelled `synthetic` were produced from the seeded generator (`RISKDESK_DATA=synthetic`) and are kept for comparison.
- The golden-set injections are applied to the real history, so their size is relative to real volatility.

## Refreshing the data

```
python scripts/fetch_real_data.py
```

This overwrites `data/real/`. Commit the new files together with the evaluation they produce, so each result can be traced to its data.
