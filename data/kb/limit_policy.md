# RiskDesk Limit Policy (synthetic, for demonstration)

## Scope and ownership
This policy applies to the three trading desks in the RiskDesk synthetic book: DESK_EQ, DESK_VOL and DESK_FX. Each desk has three hard limits: one-day 99% VaR, worst stress loss, and absolute vega. The Market Risk function owns the limits. Desk heads own the positions.

## Hard limits and warning levels
Every hard limit has a warning level at 80% of the hard value. Utilisation is the measured value divided by the hard limit. Status is OK below 80%, WARNING from 80% to 100%, and BREACH above 100%.

## Breach response
When a desk reaches BREACH, the desk head must be told within the same business day. The Market Risk analyst opens a breach case, attributes the excess to risk drivers, and checks the market data before any action. A breach is never closed by changing the limit alone.

## Data quality before market conclusions
Before a breach is treated as a market move, the analyst confirms that each underlying price passes the jump check: the one-day log move must be within six daily standard deviations of the history, unless a verified market event explains it. A breach driven by a failed jump check is a data incident, not a market move, and is raised with the data owner.

## Limit calibration
Limits are set with headroom above the baseline measure. A hard limit below 60% of the baseline one-day VaR is treated as a calibration error. Changes to a limit need a written proposal, a rationale, a second-line review and approval by the Head of Market Risk. The proposal is held until approved; no agent may change a limit.

## Stress limit
The stress limit applies to the worst loss across the named hypothetical scenarios and the worst historical windows. A stress breach requires a desk-level action plan within five business days.

## Vega limit
Vega is measured as the sum of position vega per one vol point. A vega breach triggers a review of option positions on the named underlyings, with the largest vega contributors reviewed first.

## Model and methodology changes
Any change to the VaR method, the window length, or the confidence level is a model change. It must be validated under the model risk policy before use.
