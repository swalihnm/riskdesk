# RiskDesk

A free market-risk workbench with agents built in. A Python engine computes VaR, Expected Shortfall, Greeks, stress losses, limit utilisation and backtests on a synthetic trading book. LangGraph agents investigate limit breaches, draft notes, and send every decision to a named human.

**The design rule:** the LLM never calculates a risk number. Every figure comes from the engine, and a grounding gate blocks any draft containing a number no tool returned.

All data is synthetic. Nothing calls a paid API. Progress and results: [PROGRESS.md](PROGRESS.md) and [docs/mrm/](docs/mrm/).

## Quick start
```bash
pip install -r requirements.txt
python scripts/build_data.py        # synthetic data, limits, incident logs, retrieval questions
python -m pytest -q tests           # 48 tests
python evals/golden.py              # 100-scenario golden set
python evals/run_eval.py            # score the agent on the golden set (template drafter)
streamlit run ui/app.py             # limits, investigation, approval queue
python -m riskdesk.mcp.server       # riskdesk-mcp over stdio
```

Optional local LLM drafter (free, slow on CPU): install [Ollama](https://ollama.com), `ollama pull qwen2.5:0.5b`, then `RISKDESK_DRAFTER=ollama python evals/run_eval.py`.

## What it does
| Part | Where |
| --- | --- |
| Pricing, Greeks (checked against textbook values and bump-and-reprice) | `riskdesk/engine/instruments.py` |
| Historical, parametric and Monte Carlo VaR; ES; Euler component VaR | `riskdesk/engine/risk.py` |
| Stress (named analogues and worst historical windows, both directions) | `riskdesk/engine/stress.py` |
| Limit framework (hard limit and 80% warning) | `riskdesk/engine/limits.py` |
| Kupiec test and Basel traffic light | `riskdesk/engine/backtest.py` |
| P&L attribution test (MAR32.42: Spearman and KS, green, amber, red) | `riskdesk/engine/pla.py` |
| Breach-investigation LangGraph, with human gates | `riskdesk/agents/graph.py` |
| Challenger agent: an independent second review that can add escalations, never remove them | `riskdesk/agents/challenger.py` |
| Function-calling drafter (local model picks engine tools; figures must come from tool results) | `riskdesk/agents/tool_agent.py` |
| Daily VaR commentary workflow | `riskdesk/agents/commentary.py` |
| Grounding gate, PII filter, injection screen, schemas, approval gate | `riskdesk/guardrails/` |
| Hybrid retrieval (BM25 plus sentence embeddings) and a pgvector backend | `riskdesk/rag/index.py`, `riskdesk/rag/pgstore.py` |
| MCP server (`riskdesk-mcp`) | `riskdesk/mcp/server.py` |
| Golden set, eval runner, CI gate, LLM judge and judge agreement check | `evals/` |
| Monitoring tab: run health and eval drift | `riskdesk/monitoring.py`, `ui/app.py` |
| Versioned prompts | `prompts/` |
| Model-risk pack | `docs/mrm/` |

## Results so far (synthetic data)
- Unit tests: 95 passing. MCP server tested over stdio with a live client. Streamlit app run through its test harness.
- Golden set, template drafter, 100 scenarios: 100% breach the intended desk and rank it first; root-cause accuracy 100% over 50 cases; task completion 100% of breached cases; 0 unsupported numbers shipped. These cases shock the largest exposure, so they are easy.
- Harder attribution check (`evals/hard_attribution.py`): the shock hits a non-largest exposure, so the agent must not pick the largest. 5 of 5 correct. Five cases is too few for an accuracy estimate.
- Local 0.5B model as drafter, first 12 scenarios: 64% of drafted numbers unsupported, all blocked by the gate. A 100-scenario run is in progress; see [docs/mrm/eval_history.md](docs/mrm/eval_history.md) when it finishes.

These are results on a synthetic book built to be detectable. They are not evidence of performance on real data. See [docs/mrm/validation_report.md](docs/mrm/validation_report.md) for the limitations.

Launch materials: [resume bullets](docs/launch/resume_bullets.md) and [blog post draft](docs/launch/blog_post.md).

## Not included yet
- Real market data and calibrated implied-volatility history. Everything is synthetic.
- Judge calibration (needs your labels in `evals/judge_labels.csv`).
- pgvector retrieval and Langfuse tracing: both need Docker Desktop running. The docker-compose file starts Postgres with pgvector, but the code does not use it yet.
- Named reviewers: `data/reviewers.json` holds role placeholders. Replace them with real names before use.
- Basel traffic-light zones confirmed from search results only; the 97.5% ES level is confirmed in MAR33.3.

## Licence and data
Synthetic data only. No personal data. Names in the PII filter are invented.
