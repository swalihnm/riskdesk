# Market Risk Reference Notes (RiskDesk paraphrase)

These notes are written by RiskDesk in its own words for teaching and demonstration. They are not quotations. Check every point against the primary text (the Basel Committee market-risk standard on bis.org) before relying on it.

## Value at Risk definition
Value at Risk is the loss that a portfolio is not expected to exceed over a given holding period at a given confidence level. A 99% one-day VaR is exceeded on about 1 day in 100 if the model is correct.

## Historical simulation
Historical VaR reprices the current portfolio under each past daily move and takes the loss at the chosen percentile. It needs no distributional assumption, but it only reflects the moves in its window.

## Parametric (delta-normal) VaR
Parametric VaR assumes that factor moves are normally distributed and that P&L is linear in the factors. It is fast and transparent, but it understates risk for option books with large gamma and for fat-tailed moves.

## Monte Carlo VaR
Monte Carlo VaR simulates correlated factor moves and fully reprices the portfolio for each one. It captures non-linearity, but its results depend on the chosen distribution and the number of paths.

## Expected Shortfall
Expected Shortfall at 97.5% is the average loss in the worst 2.5% of outcomes. It is sensitive to the shape of the tail, which VaR ignores. Regulators moved to Expected Shortfall for market-risk capital in the Basel market-risk framework.

## Component and marginal VaR
Component VaR splits total VaR across positions so that the parts add up to the whole (Euler allocation). A positive component means the position adds risk; a negative component means it hedges.

## Greeks
Delta measures sensitivity to the underlying price. Gamma measures how delta changes with the price. Vega measures sensitivity to implied volatility. Theta measures time decay. Rho measures sensitivity to interest rates. Gamma rises sharply near expiry for at-the-money options.

## Stress testing
A stress test applies a large, plausible move to the book, either a named historical episode or a hypothetical shock. It answers "what could we lose in a bad scenario", which VaR does not answer directly.

## VaR backtesting
Backtesting compares each day's VaR forecast with the hypothetical P&L on that day. An exception is a loss larger than the forecast. For 99% VaR over 250 days, about 2.5 exceptions are expected. The Basel traffic-light zones are green for 0 to 4 exceptions, amber for 5 to 9, and red for 10 or more.

## Kupiec proportion-of-failures test
The Kupiec test compares the observed exception rate with the expected rate using a likelihood-ratio statistic that follows a chi-squared distribution with one degree of freedom. A small p-value means the model's exception rate is inconsistent with its stated confidence level.
