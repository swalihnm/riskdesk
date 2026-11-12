# Letting an LLM explain a market-risk breach, without letting it compute one

Written for: engineers and risk professionals who are curious about agents in regulated settings.

I built RiskDesk to answer one question: can an LLM agent help a market-risk team investigate a limit breach without ever being trusted with a number?

The design rule is simple. A Python engine computes every figure: one-day 99% VaR by historical, parametric and Monte Carlo methods; 97.5% Expected Shortfall; component VaR that adds up exactly to the total; stress losses in both directions; and a 250-day backtest with the Basel traffic-light zones. The agent reads those figures through a small set of tools, writes a short note, and sends it to a person. Before the note goes anywhere, a grounding check looks at every number in it and blocks the note if any figure is not one the engine returned.

## What I found
On a synthetic book with 100 injected breaches, the agent reached the intended desk in every case and ranked it first. No unsupported number reached a reviewer. I want to be careful about what that means. The injected causes are the largest exposures on their desks, so the test is easy. It shows the plumbing works, not that the agent would find a real cause in a real book.

The more useful result was negative. I tried a 0.5-billion-parameter local model as the drafter. In a 12-scenario trial, 64% of the numbers it wrote were ones the engine never produced. The gate caught every one of them, but I would not run that model without the gate, and the validation report says so.

## Regulatory points I got wrong at first
I wrote my first regulatory summaries from memory. Checking them against the primary texts changed three things. The current version of the Bank of England's SS1/23 took effect on 23 April 2026, not in 2024. The Federal Reserve's SR 26-2 says in a footnote that generative and agentic AI models are not within its scope, which I had described as an open question. And the principle titles in SS1/23 are different from the ones I had written. The lesson for me was to check the primary text before writing it down.

## What is not done
The data is synthetic, and the judge that is meant to check citations has not been calibrated against human labels. The retrieval test is too close to the document headings to mean much. A real deployment needs real implied-volatility history, authentication on the approval queue, and an independent validator.

The code, the golden set and the model-risk pack are in the repository, with every limitation written next to the result it affects.
