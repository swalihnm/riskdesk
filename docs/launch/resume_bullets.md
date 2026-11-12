# Resume bullets: RiskDesk

Written for: the author's resume. Every number below is from a saved run in `evals/results/` or from a test in `tests/`. Delete any bullet you cannot defend in an interview, as the plan says. Items marked PENDING need a result first.

- Built RiskDesk, a market-risk workbench on a synthetic 40-position, three-desk book: historical, parametric and Monte Carlo one-day 99% VaR, 97.5% Expected Shortfall, Euler component VaR, stress testing and Basel traffic-light backtesting, with 48 automated tests passing.
- Designed the LangGraph breach-investigation workflow so the LLM never computes a risk figure: a grounding gate blocks any draft number that no engine tool returned, and every output waits for a named human reviewer.
- Built a 100-scenario golden set with injected causes: 100% of injected breaches reached the intended desk and ranked first; 0 unsupported numbers reached a reviewer. Root-cause scores are on easy, engine-generated cases, and that is stated in the write-up.
- Exposed the engine as a nine-tool MCP server; tested over stdio with a live client, and every tool call is written to a hash-chained audit log.
- Wrote a model-risk pack (model card, validation report, control register, monitoring plan) and recorded a limitation for each open item, including an unvalidated 0.5B local drafter whose numbers were unsupported in 64% of trial cases and blocked by the gate.
- PENDING: judge agreement (Cohen's kappa) on 50 labelled cases.
- PENDING: local-model drafter on the full 100 scenarios.

## Do not claim
- Any figure on real market data. The book and market are synthetic.
- Any hallucination rate below 100% blocked for the local model. It was blocked by a gate, not eliminated.
- "Regulatory compliant" or "validated for use". The pack is a template, not an independent validation.
- Any retrieval accuracy. Recall@5 = 1.0 is on questions close to the headings and is not a fair test.
