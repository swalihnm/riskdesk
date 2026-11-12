# RiskDesk: complete project record

**Completed: 96%** · last updated 12 November 2026 · repository https://github.com/swalihnm/riskdesk (public, branch `main`) · 95 tests collected, all passing

This file is the full record of the project: what it is, every file and why it exists, how each part works, every result with the data it was produced from, every decision and bug, what is still open, and the chronological log. It is refreshed at each milestone. Percentages are an estimate of how much of the plan is built and checked. They are not a measured metric.

## Contents
1. Purpose and scope
2. Status at a glance
3. Architecture
4. Data (real and synthetic)
5. Risk engine
6. Investigation agents
7. Guardrails and controls
8. Retrieval
9. Evaluation
10. Monitoring and the dashboard
11. MCP server and interfaces
12. Tests
13. Configuration, environment and dependencies
14. Model-risk documentation
15. Decisions and why
16. Bugs found and fixed
17. Known limitations
18. Open items (owner and next step)
19. Commands
20. Repository file map (every tracked file)
21. Commit history (every commit)
22. Chronological log

---

## 1. Purpose and scope

RiskDesk is a market-risk workbench with LLM agents, built for a demonstration and a job application for an AI engineering role in traded risk. A Python engine computes one-day risk measures for a three-desk book. Agents investigate limit breaches and draft notes. Every decision waits for a named human reviewer.

Design rules, enforced in code:
- The language model never computes a risk figure. Every figure in a note must come from an engine tool result, and a grounding gate blocks any figure that does not.
- Agents never change a limit or a position. A limit change is a proposal in an approval queue.
- Every tool call and every agent step is written to a hash-chained audit log.
- Prompts are versioned. Any change to a prompt is recorded, and a CI gate reruns the evaluation.
- Free and local tools only: no paid API, no paid data, no account needed for the core project.

Out of scope: real positions, real counterparties, regulatory reporting, capital calculation, and any production deployment.

## 2. Status at a glance

| Area | State | Notes |
| --- | --- | --- |
| Risk engine (pricing, VaR, ES, component VaR, stress, limits, backtest, PLA) | Built, tested | Real data is the default |
| Market data | Real data built and merged; synthetic kept | Yahoo Finance, ECB, FRED; see section 4 |
| Investigation graph (LangGraph) | Built, tested, evaluated | 100-scenario evaluations on real and synthetic data |
| Function-calling drafter (local model picks engine tools) | Built, tested, evaluated | 3B model; full run on synthetic data |
| Challenger agent (second reviewer) | Built, tested, trialled | False alarms reduced, not eliminated |
| Commentary workflow (daily VaR) | Built, tested | Queues for approval |
| Guardrails (grounding, citation control, content check, PII, injection, approval gate, audit) | Built, tested | |
| Retrieval (BM25, sentence embeddings, hybrid, pgvector) | Built, measured | Independent question set still needed |
| Evaluation (golden set, runner, CI gate, LLM judge, judge check) | Built | Human labels not yet provided |
| Monitoring (dashboard tab, run health, drift) | Built | One full run on real data so far |
| MCP server (10 tools) | Built, tested over stdio | |
| Dashboard (4 tabs) | Built, run through Streamlit's test harness | Not checked in a browser |
| Model-risk pack | Built | Some sections still describe the synthetic run; see section 18 |
| Infrastructure (Docker Postgres with pgvector, CI workflow, Ollama models) | Built | Docker running locally; CI not yet run on GitHub |
| P&L attribution test (MAR32.42) | Built, tested | Synthetic and real results recorded |
| LLM judge (citation support) | Built, measured against automated labels | Human agreement not computed until human labels exist |
| Hosted deployment | Not built | Needs a hosting account |
| Langfuse tracing | Not built | Decision: JSONL traces and the dashboard instead (section 15) |

## 3. Architecture

```
market data (real: data/real/ | synthetic: seeded generator)
        |
risk engine (riskdesk/engine): pricing, VaR (3 methods), ES, component VaR, stress, limits, backtest, PLA
        |
tools layer (riskdesk/tools.py): every function audited; the only route from agents to numbers
        |
  +-----+------------------------------+-----------------------------+
  |                                    |                             |
investigation graph            challenger agent            commentary workflow
(riskdesk/agents/graph.py)     (agents/challenger.py)      (agents/commentary.py)
 triage -> attribution ->       independent re-derivation
 challenge -> policy lookup ->  adds escalations only
 draft -> validate -> gates
        |
guardrails (riskdesk/guardrails): grounding, citation control, content check, PII, injection, schemas, approval queue, audit
        |
human reviewer (named, on allowlist) decides approval or rejection
        |
outputs: approval queue, audit log (hash-chained), JSONL traces, evaluation history
        |
interfaces: Streamlit dashboard (ui/app.py), MCP server (riskdesk/mcp/server.py), CLI evaluation scripts (evals/)
```

Retrieval (riskdesk/rag) supplies policy citations to the graph. It runs in memory, or in PostgreSQL with pgvector. Evaluation (evals/) replays generated scenarios through the graph and scores the results. Monitoring (riskdesk/monitoring.py) reads the trace file and the evaluation history.

## 4. Data

### 4.1 Real market data (the default since merge `a094a14`)

Stored in `data/real/` (`prices.parquet`, `provenance.json`) and committed, so the project runs offline and results are reproducible. Refresh with `python scripts/fetch_real_data.py`.

| Input | Source | Detail |
| --- | --- | --- |
| Equity ETF closes | Yahoo Finance via `yfinance` (unofficial) | SPY, QQQ, XLF, XLE, XLV, IWM; adjusted closes |
| EUR/USD | ECB reference rates | USD per EUR, used directly |
| GBP/USD and AUD/USD | ECB reference rates | derived: USD per EUR divided by GBP (or AUD) per EUR |
| Discount rate | FRED `DGS1` | 1-year US Treasury; latest 4.38% (9 Nov 2026) |
| Foreign rates | FRED `IR3TIB01EZM156N`, `IR3TIB01GBM156N`, `IR3TIB01AUM156N` | 3-month interbank, monthly; EUR 2.03% (Jan 2026), GBP 3.71% (Jan 2026), AUD 4.51% (Aug 2026) |
| Cross-check only | CBOE `VIX_History.csv` | VIX close 17.49 on 11 Nov 2026; not used in calculations |

Sample: 1,251 trading days, 1 Nov 2021 to 11 Nov 2026. Volatility factor: 21-day realised volatility, annualised, and its daily change in vol points (a proxy, since no free source gives per-ETF implied volatility). Checks: no gaps over five days, no duplicate dates; the only daily move above 10% is QQQ +11.3% on 9 April 2025.

Assumptions a reviewer must know are in `docs/data/real_data.md`: realised volatility as the implied-volatility proxy, illustrative desk sizes, Black-Scholes with no dividends, monthly foreign rates, and the unofficial Yahoo source.

### 4.2 Synthetic market data (kept for comparison)

`riskdesk/engine/market.py` generates 750 days of correlated, fat-tailed factor moves from seed 42, with two stress episodes (days 200 to 210 and 520 to 530). A one-factor model gives equity loadings 0.7 and FX loadings 0.3, Student-t(5) shocks, and daily volatility of 1.1% (equities) and 0.5% (FX). Used when `RISKDESK_DATA=synthetic`. The earlier results and the tests that call `generate_history` use it. Its cache file `data/cache/history.parquet` is gitignored.

### 4.3 The book
Forty positions across three desks, generated by `riskdesk/engine/book.py` with seed 7 from the market's own names and rates:
- DESK_EQ: 3 cash equity positions and 8 equity options on the first three underlyings.
- DESK_VOL: 3 cash equity positions and 14 equity options across all six underlyings.
- DESK_FX: 12 FX forwards, four per currency pair, expiries 0.25 to 1.0 years.

Cash quantities are 2,000 to 20,000 units; option quantities are 5 to 59 contracts of 100 shares; forward notionals are 1 to 5 million with random sign. On ETFs priced near 750 this is a much larger exposure than the synthetic book had at prices near 100. The book is illustrative, and the limits are calibrated on it.

## 5. Risk engine (`riskdesk/engine`)

- **Instruments (`instruments.py`).** Black-Scholes European options with zero dividend yield and a flat domestic rate. Cash positions are valued as quantity times spot. FX forwards are valued as a foreign-currency amount discounted at the foreign rate minus the domestic amount discounted at the domestic rate. Analytic Greeks: delta, gamma, vega, theta, rho. Position-level sensitivities use dV/d(ln S) for spot and vega per vol point. Checked against textbook values (call 10.4506, put 5.5735 at S=K=100, T=1, r=5%, sigma=20%; delta 0.6368; gamma 0.018762; vega 37.524; theta -6.414; rho 53.2325) and against bump-and-reprice.
- **Risk measures (`risk.py`).** Window of 250 days.
  - Historical VaR: full revaluation of today's book under each of the last 250 daily moves; 99% quantile.
  - Parametric VaR: delta-normal, using the sample covariance of the factor moves; z(0.99) times the portfolio sigma.
  - Monte Carlo VaR: 10,000 correlated normal draws (Cholesky), with every option fully repriced.
  - Expected Shortfall at 97.5%: mean of the tail beyond the quantile (historical); normal formula for parametric.
  - Component VaR (Euler): z times the covariance of each position with the portfolio, divided by the portfolio sigma. Contributions sum exactly to the parametric VaR.
- **Stress (`stress.py`).** Five named hypothetical scenarios: equity crash (-35%, vol +25 pts), liquidity shock (-30%, FX -5%, vol +30), rate and FX shock (-12%, FX -10%, vol +8), EUR/USD -10% (first FX pair), implied vol +15 pts. Plus the three worst 10-day windows in the history. Every shock is also run reversed. The named scenarios are analogues, not replays of 2008, 2020 or 2022.
- **Limits (`limits.py`).** Per desk: one-day 99% VaR, worst stress loss, and absolute vega. Warning at 80% of the hard limit; breach above 100%. Hard limits are the baseline times 1.5, rounded up.
- **Backtest (`backtest.py`).** Rolling 250-day VaR forecast against the hypothetical P&L of each of the last 250 days. Kupiec proportion-of-failures test (likelihood ratio, chi-square with one degree of freedom). Basel traffic light for 250 observations at 99%: green 0 to 4, amber 5 to 9, red 10 or more (MAR32 Table 1). The zone names were confirmed in the primary text.
- **P&L attribution (`pla.py`, MAR32.42).** Hypothetical P&L (full revaluation) against risk-theoretical P&L (the linear sensitivities times the same moves). Spearman correlation and the Kolmogorov-Smirnov statistic. Green: correlation above 0.80 and KS below 0.09. Red: correlation below 0.70 or KS above 0.12. Amber otherwise. The risk-theoretical model is this project's linear approximation, not a bank's model.

Results on the real book (12 Nov 2026 data):

| Desk | Historical VaR | Parametric VaR | Monte Carlo VaR | ES 97.5% | PLA Spearman | PLA KS | PLA zone |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DESK_EQ | 534,196 | 520,746 | 511,687 | 634,063 | 1.0000 | 0.016 | green |
| DESK_VOL | 188,727 | 200,423 | 196,118 | 241,656 | 0.9999 | 0.020 | green |
| DESK_FX | 163,693 | 170,329 | 168,957 | 186,549 | 1.0000 | 0.012 | green |

Backtest on the real book: 250 days, 3 exceptions, green zone, Kupiec p = 0.758.

Limits on the real book (baseline, then hard limit):

| Desk | One-day 99% VaR | Stress loss | Vega (points) |
| --- | --- | --- | --- |
| DESK_EQ | 534,196 → 802,000 | 8,197,718 → 12,297,000 | 25,652 → 38,500 |
| DESK_VOL | 188,727 → 284,000 | 4,245,519 → 6,369,000 | 19,517 → 29,300 |
| DESK_FX | 163,693 → 246,000 | 2,252,169 → 3,379,000 | 0 → 100 |

Synthetic book, for comparison: the earlier hard VaR limits were DESK_EQ 147,000, DESK_VOL 138,000 and DESK_FX 161,000. The synthetic backtest had 4 exceptions (green, Kupiec p = 0.38). The synthetic PLA was green on all desks and on the cash-only control.

## 6. Investigation agents (`riskdesk/agents`)

### 6.1 Investigation graph (`graph.py`)
A LangGraph state machine. Node by node:
1. **triage**: ranks every desk and metric by utilisation; no breach ends the run.
2. **attribution**: Euler component VaR by underlying; top driver, its share, and the margin over the runner-up. Data checks: a jump test fails if a one-day log move exceeds six daily sigmas, and any quality flag marks the data. Classification: `data_issue` if any flag, `limit_error` if the hard VaR limit is below 60% of the baseline VaR, else `market_move`. Confidence = (margin minus 1) / 0.5, capped to [0, 1]. Escalation if confidence is below 0.5 (top-two margin below 1.25) or the classification is not `market_move`.
3. **challenge** (optional, off by default): the challenger agent (section 6.3). It can add an escalation, never remove one.
4. **policy_lookup**: hybrid retrieval, two citations at most, policy and regulatory text only (incident logs are never cited as policy).
5. **draft_report**: template drafter, Ollama drafter (JSON-constrained), or the function-calling drafter (`tools`). Falls back to the template on any failure, and records the reason. A model note must pass the content check.
6. **validate**: redaction (PII), grounding of every figure against the tool outputs, and a citation control on every policy ID the note names. Pydantic schema validation of the report. Up to two drafting attempts.
7. **queue_review / human_review** (escalated cases): a pause for a named reviewer. Limit-calibration cases also create a limit-change proposal, which is never applied.
8. **queue_approval / approval_gate** (non-escalated cases): a pause for a named approver.

Interrupts occur only in the two gate nodes. Queue writes happen in the node before each interrupt, because LangGraph re-runs a node from its start on resume. The graph has a synchronous entry point (`investigate`) and an asynchronous one (`investigate_async`), which the evaluation uses to run scenarios concurrently.

### 6.2 Function-calling drafter (`tool_agent.py`)
The local model may call six tools: limit_status, compute_var (historical or parametric only; Monte Carlo is excluded as too slow), attribution, data_checks, stress_test, and search_policy (returns section IDs and headings, not text). Each call is validated: the tool must exist, the desk must be one of the three, the method must be allowed, no extra arguments, and the query length is limited. Invalid calls are recorded and not executed. The final note is constrained to a JSON schema and parsed with pydantic. Up to six tool-calling steps.

### 6.3 Challenger agent (`challenger.py`)
A second, independent reviewer. It is given only the desk and the metric, not the first classification. It has four read-only tools (limit_status, attribution, baseline, data_checks) and must reach its own classification, top driver and confidence, returned as JSON constrained to a schema.

Comparison rules: a different classification, or a different top driver, or confidence below 0.5, is a disagreement. A failed challenge escalates (fail-safe). Agreement changes nothing. The challenger can add an escalation but never remove one, which is enforced by the graph and tested.

Trials (all on the synthetic market, which was the market in use at the time):

| Run | Prompt | Scenarios | Disagreements | Notes |
| --- | --- | --- | --- | --- |
| 1 | challenger 1.0.0 | 12 | 6 of 12 | all six were false alarms (the first analyst was right); the model often proposed data_issue with no data flag |
| 2 | challenger 1.1.0 | 12 | 3 of 12 | all three false alarms; data_issue still over-proposed; task completion 75% |

Prompt 1.1.0 makes the rules exact: data_issue needs a non-empty flags list, and limit_error uses the field names the baseline tool returns. The problem is reduced but not solved. Next steps are in section 18.

### 6.4 Drafters and prompts (`drafters.py`, `prompts/`)
- `TemplateDrafter`: deterministic text from the facts. Used in CI and tests.
- `OllamaDrafter`: a chat call with the system prompt, few-shot examples and the JSON schema. Output validated with pydantic.
- Prompt `breach_report.yaml` version 2.1.0: system rules (figures only from tools or facts, tools before writing, cite only given IDs, no action recommendations, 90 words maximum), two few-shot examples, a user template, and a tool prompt that requires the desk and the classification in words. The changelog from 1.0.0 to 2.1.0 is kept in the file.
- Prompt `challenger.yaml` version 1.1.0 (see 6.3).
- Prompt `judge.yaml` version 1.0.0 (see 9.6).
- Prompt `var_commentary.yaml` version 1.0.0: two-sentence daily commentary, used by the commentary workflow.

### 6.5 Daily commentary (`commentary.py`)
Computes each desk's one-day 99% VaR today and yesterday (the window shifted by one day), drafts two sentences from those figures, runs the grounding and PII checks, and queues the text for approval. Blocked text is not queued.

## 7. Guardrails and controls (`riskdesk/guardrails`, `riskdesk/audit.py`)

| Control | Where | What it does |
| --- | --- | --- |
| Grounding gate | `grounding.py` | Every figure in a note must match a tool output or a whitelisted method constant (97.5, 99, 250, 80, 100, 10, 5, 4, 9, 0 to 3, 6, 7, 20, 60). Percentages are matched as written (85% matches 85). Identifiers such as INC-0001 and SS1/23 are excluded from figure extraction. |
| Citation control | `graph.py::validate` | Every policy ID in a note must be one that policy lookup or a tool returned. |
| Content check | `graph.py::content_check` | A model note must name the desk and the classification (accepting natural synonyms: "market move", "data issue", "limit error", "calibration"). It must not echo the prompt. Otherwise the template is used and the reason recorded. |
| PII filter | `pii.py` | Presidio with the default recognisers, plus custom recognisers for the synthetic trader and counterparty names. Regex fallback if Presidio fails. Redaction is never skipped. |
| Injection screen | `injection.py` | Pattern checks for instruction-override phrases in retrieved text; flagged passages are quarantined. |
| Schemas | `schemas.py` | Pydantic models for findings, drivers, attribution, the investigation report and approval items. |
| Approval queue | `approval.py` | JSON-file queue, process-wide lock, decisions need a named reviewer on the allowlist (`data/reviewers.json`). Agent, system, riskdesk, assistant and bot names are refused. A second decision on an item is rejected. |
| Audit log | `audit.py` | Hash-chained JSON lines. Each entry stores the previous hash. `verify()` detects any edit. Tests change one entry and confirm detection. Local file, not write-once. |

Control register entries C-01 to C-18 are in `docs/mrm/control_register.md`.

## 8. Retrieval (`riskdesk/rag`)

- **Corpus.** Four knowledge-base files in `data/kb/`: limit policy (8 sections), escalation matrix (6), market-risk reference (10), regulatory summaries (11), plus 50 synthetic incident logs. Sections are the units of relevance.
- **Chunkers.** Section (one chunk per `##` section) and window (60 words with 20 overlap, inside each section).
- **Scorers.** BM25 (rank_bm25); dense (all-MiniLM-L6-v2 via sentence-transformers, normalised cosine); hybrid (reciprocal-rank fusion of BM25 and dense, constant 60, pool of 50); character-trigram hashing as a baseline.
- **Metrics.** Section-level recall@5, MRR@10 and nDCG@10 with binary relevance.
- **pgvector (`pgstore.py`).** Table `kb_chunks` with a 384-dimensional vector column and an HNSW index, in the Docker Postgres. Its top-5 sections match the in-memory dense index for all 59 questions (tested).

Ablation on the paraphrased set (`evals/rag_eval_v2.jsonl`, 59 questions, written by the author who also wrote the corpus):

| Chunking | Method | recall@5 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- |
| section | BM25 | 0.831 | 0.753 | 0.796 |
| section | dense (MiniLM) | 0.966 | 0.873 | 0.897 |
| section | hybrid | 0.983 | 0.858 | 0.889 |
| section | character-trigram baseline | 0.864 | 0.790 | 0.817 |
| window 60/20 | dense | 0.966 | 0.860 | 0.887 |
| window 60/20 | hybrid | 0.949 | 0.864 | 0.898 |

The earlier 40-question set (`evals/rag_questions.jsonl`), written close to the headings, scores 1.0 for every method and does not discriminate. It is kept for reference only.

## 9. Evaluation (`evals`)

### 9.1 Golden set (`golden.py`, `evals/golden_set.jsonl`)
100 scenarios with a known cause, six types: single_position_vol (17), correlated_fx (17), data_quality (17), limit_error (17), multi_breach (16), ambiguous (16). Each scenario injects its cause into the market (regime shocks over the last 20 days, implied-vol jumps, a bad tick on one day, or a lower limit). Injection size is raised through eight levels (1x, 1.5x, 2x, 3x, 4x, 6x, 8x, 12x) until the intended desk breaches. The shocks target each desk's largest exposure. Ambiguous cases are built to a measured top-two margin: about 1.1 (must escalate) on even indices and about 2.5 (control, must not escalate) on odd indices.

Ground truth per scenario: expected classification, expected top driver (underlying), expected escalation, and the desk that should breach.

Metrics (`run_eval.py`):
- Injection breach rate: intended desk breaches.
- Intended desk ranked first (multi-breach included).
- Root-cause accuracy: top driver matches the injected driver, on cases ranked first with a driver.
- Classification and escalation correctness, on cases ranked first.
- Task completion: breached, validated report, paused at a gate.
- Unsupported figures shipped, and the rate of unsupported figures among drafted figures.
- Tool-call rate, fallback rate, content-check failures, challenger disagreements, latency.

### 9.2 Results (all runs, with the data each was produced from)

| Run | Data | Drafter, model, prompt | Breach | Ranked first | Root cause | Classification | Escalation | Task completion | Figures unsupported (drafted) | Shipped unsupported | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Template, current | real | template, prompt 2.1.0 | 98% | 98% | 100% (n=50) | 100% | 100% | 100% | 0% | 0 | none |
| Template, earlier | synthetic | template, prompt 2.0.0 | 100% | 100% | 100% (n=50) | 100% | 100% | 100% | 0% | 0 | none |
| Local 0.5B, free text | synthetic | ollama, prompt 1.1.0 | 100% | 100% | 100% | 100% | 100% | 90% | 37.2% | 0 | 49 |
| Local 3B, tools, first 12 (strict content check) | synthetic | tools, prompt 2.0.0 | 100% | 100% | 100% | 100% | 100% | 67% | 8.6% | 0 | 7 of 12 |
| Local 3B, tools, first 12 (synonym check) | synthetic | tools, prompt 2.1.0 | 100% | 100% | 100% | 100% | 100% | 91.7% | 7.1% | 0 | 2 of 12 |
| Local 3B, tools, full 100 | synthetic | tools, prompt 2.1.0 | 100% | 100% | 100% (n=50) | 100% | 100% | 75% | 10.8% | 0 | 19 of 100 |
| Local 3B, tools with challenger 1.0.0, first 12 | synthetic | tools, prompt 2.1.0 | 100% | 100% | 100% | 100% | 100% | 91.7% | 6.1% | 0 | 1 of 12 |
| Local 3B, tools with challenger 1.1.0, first 12 | synthetic | tools, prompt 2.1.0 | 100% | 100% | 100% | 100% | 100% | 75% | 11.1% | 0 | 3 of 12 |

Root-cause accuracy is 100% in every run, because the shocks target the largest exposure, so the test is easy by design. The hard-attribution check (section 9.5) is the harder test.

Earlier free-text run on synthetic data (`evals/results/latest_ollama_v1.1_freetext.json`): 100 scenarios, 51 model notes and 49 template fallbacks, 37.2% of drafted figures unsupported and blocked, 0 shipped, median latency about 29 s. A single 0.5B function-calling case (one scenario) called two tools and produced a note with no figures, which passed the figure check; that is why the content check was added.

Figures blocked by the gate are the only figures that failed. None reached a reviewer in any run.

### 9.3 CI gate (`ci_gate.py`, `evals/baseline.json`)
Compares the latest template run with the baseline. Fails if any figure reached a queue, or if root-cause accuracy, injection breach rate or task completion fell by more than 2 points. The baseline is currently the real-data template run; `--update-baseline` sets it after a reviewed run. The gate passes on the current baseline. The GitHub workflow has not yet run.

### 9.4 Retrieval, PLA, backtest and limits
See sections 5 and 8. These are recorded in `docs/mrm/validation_report.md`. The PLA and backtest figures in that report are from the synthetic run; the real-data figures are in section 5 of this file.

### 9.5 Hard attribution (`hard_attribution.py`, `evals/results/hard_attribution.json`)
The shock hits a non-largest exposure, so the largest existing exposure is a distractor. 5 of 5 cases correct on the synthetic book. Only five non-largest exposures can breach their desk within the tested injection range, so it is too small for an accuracy estimate. Not yet re-run on real data.

### 9.6 Citation-support judge (`judge.py`, `llm_judge.py`, `judge_labels.csv`)
The dataset: 75 rows, each pairing a claim ("this case should be handled under the cited policy section") with the cited passage. 50 are real citations from breached cases (policy sections for their case type). 25 are negative controls, in which the passage is deliberately a section for a different case type. Columns: `judge_label` (the rule), `automated_label` and `automated_reviewer` (an automated reviewer, kept separate), and `human_label` and `human_reviewer` (empty, for a human).

- **Rule judge (`judge.py`).** SUPPORTED if the passage contains a keyword for the classification. Against the automated reviewer: all 50 real citations agree; 21 of the 25 negative controls are wrongly SUPPORTED (the keywords "limit" and "data" appear in unrelated sections). Kappa 0.203.
- **LLM judge (`llm_judge.py`, rubric 1.0.0, qwen2.5:3b, JSON-constrained).** 75 of 75 answered, no errors, 487 s. Agreement with the automated reviewer 42.7%, kappa 0.098. Not computed against human labels, because none exist.
- Human agreement is reported only once every row has a human label (`python evals/judge.py --kappa`). Labelling guide: `docs/eval/judge_labelling_guide.md`.

The automated reviewer's labels are not human labels and must not be cited as such.

## 10. Monitoring and the dashboard (`riskdesk/monitoring.py`, `ui/app.py`)

- **Trace file** (`data/traces/traces.jsonl`, gitignored): one record per graph node per run: run ID, node, latency, prompt version, drafter, tokens, fallback reason, grounding result, challenger agreement, and classification. It accumulates across all runs, including tests that write to temporary files.
- **Run health** (`run_health`): runs, drafter outcomes, fallback reasons, prompt versions in use, challenger disagreements, grounding failures, tokens and tokens per run, and run-time p50 and p95.
- **Eval history** (`evals/results/history.jsonl`): one line per full evaluation run with the prompt version, the drafter, the data source (from `data_source`, added with the real-data switch) and the summary. Earlier lines lack the field and are synthetic.
- **Drift chart**: `write_report()` draws `docs/mrm/eval_drift.png` when there are two or more runs.
- **Dashboard Monitoring tab**: run-health metrics, bar charts of drafters and fallback reasons, the eval history table, and a line chart when there are two or more runs.

Langfuse is not used (section 15).

## 11. MCP server and interfaces

- **MCP server** (`riskdesk/mcp/server.py`, FastMCP from the MCP Python SDK pinned below version 2). Ten tools: list_desks, limit_status, compute_var (historical, parametric or monte_carlo), compute_es, attribution, stress_test, data_checks, backtest, pla_test, search_policy. Tested over stdio with a live client (with nine tools at that time; pla_test was added afterwards).
- **Dashboard** (`ui/app.py`, Streamlit). Four tabs: Limits (limit table and the audit-chain status), Investigate (runs an investigation on the current book), Approval queue (approve or reject with a named reviewer), Monitoring. Run through Streamlit's test harness, including the investigate button. Not checked in a browser.
- **Evaluation CLI** (`evals/run_eval.py`): `--limit` and `--concurrency`. Writes `evals/results/latest_template.json`, or a tagged name for other drafters, models, challenger versions and synthetic runs, and appends to `history.jsonl` on full runs.

## 12. Tests

95 tests collected; 74 test functions (some parametrised). All pass on the current `main`.

| File | Tests | What it covers |
| --- | --- | --- |
| `tests/test_engine.py` | 17 | Textbook prices and Greeks, bump-and-reprice, put-call parity, hand-checked parametric VaR and ES, Euler sums to VaR, Monte Carlo against parametric, stress in both directions, Kupiec, Basel zones |
| `tests/test_guardrails.py` | 13 | Grounding (including percentages and identifiers), PII (regex and Presidio paths), injection patterns, audit tamper detection, approval rules, reviewer allowlist, no second decision |
| `tests/test_challenger.py` | 12 | Challenger tool validation and read-only tool set; comparison rules; the agent loop against a scripted model; graph behaviour for agreement, disagreement, failure, and no removal of escalation |
| `tests/test_agents_v2.py` | 13 | Function-calling tool validation; agent loop against a scripted model (valid call, rejected call, invalid JSON, server failure); note schema; content check; citation control; retrieval metrics on known ranks; window chunks map to sections; async graph run |
| `tests/test_graph.py` | 6 | No breach ends the run; limit error queues a proposal; data issue escalates; market move reaches approval; named reviewer recorded |
| `tests/test_mcp_commentary.py` | 5 | MCP tool registration and output; audit entries; unknown method refused; policy search returns citations; commentary queued |
| `tests/test_pgstore.py` | 3 | Table rows match chunks; database top-5 equals the in-memory dense index; recall on the paraphrased set (needs the Postgres container; skipped otherwise) |
| `tests/test_pla.py` | 3 (8 with parameters) | Zone thresholds from MAR32.42; the cash-only control is green; every desk gets a zone |
| `tests/test_monitoring.py` | 2 | Run-health counts from a hand-made trace file; empty and missing files |

Tests use the synthetic generator where they need a fixed market, and redirect audit, trace and approval files to temporary folders.

## 13. Configuration, environment and dependencies

### 13.1 Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `RISKDESK_DATA` | `real` | `synthetic` uses the seeded generator |
| `RISKDESK_DRAFTER` | `template` | `ollama` (constrained free text) or `tools` (function calling) |
| `RISKDESK_OLLAMA_MODEL` | `qwen2.5:0.5b` | Model used by the drafters, challenger and LLM judge |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `RISKDESK_CHALLENGER` | `off` | `on` runs the challenger |
| `RISKDESK_AUDIT_PATH` | `data/audit/audit.jsonl` | Audit log location |
| `RISKDESK_PII` | `presidio` | `regex` skips Presidio |
| `RISKDESK_PG_DSN` | `postgresql://riskdesk:riskdesk_local_only@localhost:5432/riskdesk` | pgvector database (local development credentials) |

### 13.2 Infrastructure
- Docker Compose (`docker-compose.yml`): one service, `pgvector/pgvector:pg16`, database `riskdesk`, user `riskdesk`, port 5432. The password is a local default. Running locally on Docker Desktop (server version 29.7.2).
- Ollama 0.40.16 with models `qwen2.5:0.5b` (397 MB) and `qwen2.5:3b` (1.9 GB).
- spaCy model `en_core_web_lg` (for Presidio's default engine).
- Sentence-transformers model `sentence-transformers/all-MiniLM-L6-v2` (downloaded once, then cached).
- CI: `.github/workflows/ci.yml` runs the tests on push and pull request, and, for pull requests that change `prompts/`, the golden-set evaluation and the CI gate. Not yet run on GitHub.

### 13.3 Python dependencies (`requirements.txt`)
numpy, pandas, scipy, pyarrow, pydantic, pyyaml, rank-bm25, langgraph, mcp (below 2), presidio-analyzer, presidio-anonymizer, spacy, streamlit, matplotlib, pytest, httpx, sentence-transformers, psycopg (binary). The market-data loader also uses yfinance, which is installed locally but not yet listed in `requirements.txt`.

## 14. Model-risk documentation (`docs/mrm`, `docs/spec`)

- `model_card.md`: purpose, users, components, inputs, outputs and limitations. The inputs section still describes the synthetic data and needs updating for real data.
- `validation_report.md`: regulatory position (SR 26-2 excludes generative and agentic AI, footnote 3; SS1/23 applies to UK banks with internal-model approval), conceptual soundness, implementation testing, outcomes (backtest, golden set, LLM drafter trials, retrieval ablation, PLA, judge), ongoing monitoring, open issues, and an opinion. The PLA and backtest figures are from the synthetic run and need updating.
- `control_register.md`: controls C-01 to C-18, each with what it prevents, how it is tested, and the evidence file.
- `monitoring_plan.md`: metrics, alert thresholds, dashboard, drift, re-validation triggers, gaps.
- `workflow_and_change_log.md`: each graph stage with inputs, outputs and failure modes; a change log of model and prompt changes, each marked not reviewed until a named reviewer signs it.
- `eval_history.md`: generated table of eval runs and node latency.
- `docs/spec/breach_flow.md`: the manual breach-investigation process (steps M1 to M10 from policy text), the agent replacement for each step (including the challenger step), the failure modes and their handling, the decisions an SME must make, and a sign-off table. Status: draft, not signed.
- `docs/data/real_data.md`: sources, provenance, assumptions, checks, dependence of results on the data, and refresh instructions.
- `docs/eval/judge_labelling_guide.md`: how a human labels the 75 judge rows, rules of thumb, and why automated labels must stay separate.
- `docs/launch/resume_bullets.md`: resume draft with measured results only and a "do not claim" list. Its numbers must be checked against this file before use.
- `docs/launch/blog_post.md`: draft blog post on the project.

## 15. Decisions and why

1. **The language model never computes a figure.** Figures come from the engine; the grounding gate enforces this. Chosen because the job description and the regulatory context both make numbers the critical risk.
2. **Free and local tools only.** Ollama models, open-source libraries, public data. No paid API, so the project costs nothing and runs offline from its committed data.
3. **Real data by default, from free sources.** FRED and ECB are official. Yahoo Finance is unofficial and rate-limited; the stored copy is what results are produced from. Implied volatility is replaced by realised volatility; the VIX is a cross-check. Chosen so the project uses real market moves without a paid volatility-surface feed.
4. **JSONL traces and a dashboard tab instead of Langfuse.** Langfuse self-hosting needs about six services on Docker. The dashboard covers the same measures (tokens, latency, failures, drift) from files. Langfuse can be added if a role requires it.
5. **The challenger can only add escalations.** A second reviewer that could remove an escalation would weaken the controls. Enforced in code and tested.
6. **Citations are policy text only.** Incident logs are precedents, not policy. A review of the first judge sample found every market-move case citing an incident record; fixed.
7. **Content check and citation control.** The grounding gate checks figures, not quality. A 3B model note once passed the figure check while being an echo of the prompt, so a content check was added.
8. **Automated labels and human labels are separate columns.** Automated labels were once in the column a human would fill, which invites confusion. Human agreement is reported only when human labels are complete.
9. **Evaluation results are tagged by drafter, model, challenger version and data source.** Runs with different settings must never overwrite each other.
10. **The Basel zone is named amber.** The MAR32 text uses amber; the code previously said yellow.
11. **SR 26-2 and SS1/23 are described as the primary texts say.** SR 26-2 excludes generative and agentic AI (footnote 3); SS1/23 applies to UK banks with internal-model approval, so it is a reference here.
12. **Shared approval queue with a lock.** Concurrent runs corrupted the JSON file once; a process-wide lock fixes it. A database would be the production choice.
13. **The MCP SDK is pinned below version 2.** Version 2 removed the FastMCP interface the server uses.
14. **Presidio with custom recognisers, and a regex fallback.** Presidio handles personal data; the custom recognisers cover the synthetic trader and counterparty names.
15. **Data and results committed to the repository.** So a reviewer can reproduce every number, and each result names the data it came from.
16. **Local developer notes are kept out of the repository.** Excluded through the clone's private exclude list.
17. **Commits carry no AI attribution.** Applied to every commit and file, as instructed.
18. **The book keeps the synthetic generator's sizes on real prices.** This keeps the structure comparable across data sources. The consequence is larger exposures than the synthetic book; documented.

## 16. Bugs found and fixed

Engine and data:
- Config paths resolved inside the package instead of the repository root.
- Stress loss was floored at zero for the FX desk (net short), making the stress limit meaningless. Fixed by running every shock in both directions.
- Breach injections often failed to breach because they hit a small exposure. Fixed by targeting the largest exposure.
- Ambiguous cases were not ambiguous (4 of 16 escalated). Rebuilt with measured margins and negative controls.
- Scoring required the intended desk to rank first, which failed when a shared underlying breached a second desk. Now breached and ranked-first are separate.
- Real-data switch: the stress scenario and the book referred to synthetic names and constants. Now they read names and rates from the market.
- Real-data switch: the golden set and the hard-attribution script used synthetic constants. Fixed in the same change.

Grounding, drafting and agents:
- A figure regex swallowed "is 107" and reported ",222" as unsupported.
- Percentages were compared as fractions, so "99%" did not match 99. Fixed to compare as written.
- A limit-change proposal was never queued on the escalation path. Fixed and tested.
- Policy citations included incident logs. Fixed.
- A model note could pass the figure check while being off topic. Added a content check.
- The content check rejected notes that were correct but worded differently. Added natural synonyms.
- The tool prompt did not require the classification in words. Prompt 2.1.0 requires it.
- A policy-ID check compared a set with dictionaries and would have raised an error. Fixed before it ran.

Evaluation and judge:
- The judge export had no passage text, so the judge had nothing real to assess. Now each claim is paired with its cited passage.
- The judge's agreement returned 1.0 when both label sets used one category. Now reports the kappa as undefined.
- Automated labels and human columns were mixed. Separated.
- The judge rubric file had an unquoted colon, which broke the YAML parser. Quoted.
- A trial overwrote the template results. Results are now tagged and kept separately.
- Challenger trials wrote to the same file name as earlier trials. Now tagged by challenger prompt version.
- The eval history lacked the data source. Added; earlier lines are treated as synthetic.

Infrastructure and repository:
- The approval queue file was corrupted when a judge export and a background run wrote to it at once. The export now uses its own file, and a lock protects the queue.
- The MCP SDK version 2 removed FastMCP. Pinned below version 2.
- CI dependencies were missing sentence-transformers, psycopg and httpx. Added before the first CI run.
- Line endings were mixed (CRLF and LF). Normalised to LF with `.gitattributes`.
- A local developer-notes file name appeared in `.gitignore` and in early commits. Removed from history before the first push, while nothing had been published.
- The README test count was out of date. Corrected.
- A commit command failed because a path had been renamed. Re-run with the correct paths.

## 17. Known limitations

1. **Results are easy by design.** Root-cause accuracy is 100% because the shocks target the largest exposure. The hard-attribution check is too small to estimate accuracy.
2. **The retrieval test is not independent.** The author wrote the questions and the corpus.
3. **The LLM judge is weak.** Kappa 0.10 against the automated reviewer; no human comparison yet.
4. **The challenger still over-proposes data issues.** Three false alarms in twelve after prompt 1.1.0.
5. **The local models are small.** The 0.5B model produces unreliable figures; the 3B model is better but still gives unsupported figures about 7 to 11% of the time, all blocked.
6. **Volatility is a proxy.** Realised volatility stands in for implied volatility, so option and vega risk are likely understated.
7. **The desks are illustrative.** Sizes are the synthetic generator's, on ETFs priced near 750.
8. **Data sources can change.** Yahoo Finance is unofficial and rate-limited; the monthly foreign rates lag by up to ten months.
9. **Black-Scholes without dividends.** ETF dividends are ignored.
10. **The PLA risk-theoretical model is linear.** The zones show fit to this linear model, not a bank's model.
11. **Stress scenarios are analogues.** Not replays of 2008, 2020 or 2022.
12. **The audit log is tamper-evident, not write-once.**
13. **The approval queue has no authentication.** Reviewer names are checked against an allowlist only.
14. **The dashboard has not been viewed in a browser.** It has been tested through Streamlit's harness.
15. **CI has not run on GitHub.** The commands were run locally.
16. **Hard attribution and the PLA test on real data have not been checked against independent results.**

## 18. Open items

Needs you (the owner):
1. **Human labels.** Fill `human_label` and `human_reviewer` for the 75 rows in `evals/judge_labels.csv` using `docs/eval/judge_labelling_guide.md` (about 30 minutes). Then run `python evals/judge.py --kappa`.
2. **Named reviewers.** Replace the role placeholders in `data/reviewers.json` with named people.
3. **SME sign-off** on `docs/spec/breach_flow.md`.
4. **Licence.** None yet; MIT is the usual choice for a portfolio project.
5. **Independent retrieval questions.** Written by someone who has not seen the corpus, to replace the author-written set.
6. **Hosting account**, only if a live demonstration is wanted.
7. **Run CI on GitHub.** Confirm that the workflow runs; it has not run yet.

Can be done next:
8. **Update the model card, validation report, resume bullets and the PLA and backtest sections** to the real-data results, and mark the synthetic ones as such.
9. **Re-run the 3B function-calling evaluation on real data** (about 70 minutes; results committed under a real-data tag).
10. **Re-run hard attribution and the PLA check** on real data and record them.
11. **Investigate the challenger's data-issue false alarms** further (rules, examples or a design change), then re-trial.
12. **Improve the LLM judge** (few-shot examples, a stronger model or a different prompt) and measure it against the automated reviewer. Report human agreement when labels exist.
13. **Add `yfinance` to `requirements.txt`** and document the data refresh in the README.
14. **Browser check** of the dashboard.
15. **Commit and push** after each change (standing instruction).

## 19. Commands

```
python -m pytest -q tests                       # 95 tests (about 75 s)
python scripts/build_data.py                    # knowledge-base files, retrieval questions, limits
python scripts/fetch_real_data.py               # refresh real market data (needs internet)
python evals/golden.py                          # regenerate the golden set
python evals/run_eval.py --concurrency 4        # template drafter, current data
RISKDESK_DRAFTER=tools RISKDESK_OLLAMA_MODEL=qwen2.5:3b python evals/run_eval.py
RISKDESK_CHALLENGER=on RISKDESK_DRAFTER=tools python evals/run_eval.py --limit 12
RISKDESK_DATA=synthetic python evals/run_eval.py   # synthetic market, for comparison
python evals/ci_gate.py                         # gate against the baseline
python evals/ci_gate.py --update-baseline       # after a reviewed run
python evals/judge.py --export                  # build the judge sample
python evals/judge.py --kappa                   # agreement with reviewers
python evals/llm_judge.py                       # LLM judge run
python evals/rag_eval.py                        # retrieval ablation
python evals/hard_attribution.py                # harder attribution check
python -m riskdesk.monitoring                   # eval table and drift chart
streamlit run ui/app.py                         # dashboard
python -m riskdesk.mcp.server                   # MCP server over stdio
docker compose up -d postgres                   # pgvector database
```

## 20. Repository file map (every tracked file)

Generated from `git ls-files` at the time of writing. One line per file, with its purpose.

| File | Purpose |
| --- | --- |
| `.gitattributes` | Line-ending rules: text files stored as LF; PNG and Parquet treated as binary. |
| `.github/workflows/ci.yml` | CI: tests on every push and pull request; golden-set evaluation and CI gate on pull requests that change prompts. |
| `.gitignore` | Files kept out of the repository: caches, audit logs, traces, approval queues, scratch files, backups. |
| `PROGRESS.md` | This complete project record. |
| `README.md` | Project overview, data section, quick start, what it does, results, what is not included. |
| `data/kb/escalation_matrix.md` | Knowledge base: escalation levels, human review queue, data incidents, documentation rule. |
| `data/kb/incident_logs.md` | Knowledge base: 50 synthetic incident logs used as precedent (never cited as policy). |
| `data/kb/limit_policy.md` | Knowledge base: limit policy (scope, limits and warnings, breach response, data quality, calibration, stress, vega, model changes). |
| `data/kb/market_risk_reference.md` | Knowledge base: explanatory notes on VaR, historical and parametric and Monte Carlo methods, ES, component VaR, Greeks, stress, backtesting, Kupiec. |
| `data/kb/regulatory_summaries.md` | Knowledge base: SS1/23, SR 26-2 (footnote 3 scope), Basel backtesting zones and 97.5% ES, audit trail and human oversight. Checked against primary texts. |
| `data/limits.json` | Limits per desk (one-day 99% VaR, stress loss, vega) with baseline values, calibrated on the real book at 1.5x. |
| `data/real/prices.parquet` | Real market data: daily closes of six ETFs and three FX pairs, 1 Nov 2021 to 11 Nov 2026 (committed). |
| `data/real/provenance.json` | Provenance of the real data: sources, fetch time, rates and their dates, VIX cross-check, volatility proxy definition. |
| `data/reviewers.json` | Allowlist of named reviewers who may approve or reject queued items (role placeholders to replace). |
| `docker-compose.yml` | Local Postgres with pgvector (pgvector/pgvector:pg16) for the retrieval backend. |
| `docs/data/real_data.md` | Real data documentation: sources, latest values, assumptions, checks, dependence of results, refresh instructions. |
| `docs/eval/judge_labelling_guide.md` | Instructions for a human labeller of the 75 judge rows, rules of thumb, and the column meanings. |
| `docs/launch/blog_post.md` | Draft blog post about the project and its findings, with limitations. |
| `docs/launch/resume_bullets.md` | Draft resume bullets using measured results only, with a do-not-claim list. |
| `docs/mrm/control_register.md` | Control register C-01 to C-18: what each prevents, how it is tested, and the evidence. |
| `docs/mrm/eval_history.md` | Generated table of full eval runs and per-node latency from the trace file. |
| `docs/mrm/model_card.md` | Model card: purpose, users, components, inputs, outputs, limitations, ethics, maintenance. |
| `docs/mrm/monitoring_plan.md` | Monitoring plan: metrics and thresholds, dashboard, drift, re-validation triggers, gaps. |
| `docs/mrm/validation_report.md` | Validation report: regulatory position, conceptual soundness, implementation tests, outcomes, open issues, opinion. |
| `docs/mrm/workflow_and_change_log.md` | Graph stages with inputs, outputs and failure modes; change log of model and prompt changes. |
| `docs/spec/breach_flow.md` | Breach investigation: manual process (M1 to M10), agent replacement, failure modes, SME decisions, sign-off table (draft). |
| `evals/baseline.json` | CI gate baseline: the reviewed real-data template run summary. |
| `evals/build_rag_eval_v2.py` | Builds the paraphrased 59-question retrieval set and checks every gold section ID. |
| `evals/ci_gate.py` | CI gate: fails if any figure shipped unsupported or if a headline measure dropped by more than 2 points. |
| `evals/golden.py` | Golden-set generator: six scenario types, injection sizes 1x to 12x until breach, ambiguous margins, controls. |
| `evals/golden_set.jsonl` | The 100 golden scenarios for the current (real) data: type, desk, expected label, driver, escalation. |
| `evals/hard_attribution.py` | Harder root-cause test: shock on a non-largest exposure with the largest as a distractor. |
| `evals/judge.py` | Citation-support rule judge, sample export (positives and negative controls), and agreement check with reviewers. |
| `evals/judge_labels.csv` | 75 judge rows: claim, cited passage, rule label, automated reviewer label, empty human columns. |
| `evals/judge_labels_round1.csv` | First round of automated labels, kept as the record of the citation defect found. |
| `evals/llm_judge.py` | LLM judge: asks the local model for SUPPORTED or NOT_SUPPORTED with a reason; reports agreement with reviewers. |
| `evals/rag_eval.py` | Retrieval ablation: two chunkers, four methods, recall@5, MRR@10, nDCG@10 on two question sets. |
| `evals/rag_eval_v2.jsonl` | Paraphrased retrieval questions (59) with gold section IDs (headline set). |
| `evals/rag_questions.jsonl` | Earlier retrieval questions (40), written close to the headings; reference only. |
| `evals/results/hard_attribution.json` | Result of the harder attribution check on the synthetic book (5 cases). |
| `evals/results/history.jsonl` | One line per full eval run: prompt, drafter, data source, summary. |
| `evals/results/latest_ollama_v1.1_freetext.json` | Local 0.5B free-text drafting, 100 scenarios, synthetic data (prompt 1.1.0). |
| `evals/results/latest_synthetic.json` | Synthetic-data template run (earlier), kept under its own name. |
| `evals/results/latest_template.json` | Current template run on real data (the one the CI gate reads). |
| `evals/results/latest_template_synthetic.json` | Synthetic-data template run, kept for comparison. |
| `evals/results/latest_tools_qwen2.5-3b_challenger-p1.1.0_first12.json` | Challenger prompt 1.1.0 with the 3B model, 12 scenarios, synthetic data. |
| `evals/results/latest_tools_qwen2.5-3b_challenger_first12.json` | Challenger prompt 1.0.0 with the 3B model, 12 scenarios, synthetic data. |
| `evals/results/latest_tools_qwen2.5-3b_first12.json` | Function-calling 3B model, first 12 scenarios, synthetic data (prompt 2.1.0). |
| `evals/results/latest_tools_qwen2.5-3b_synthetic.json` | Function-calling 3B model, full 100 scenarios, synthetic data (prompt 2.1.0). |
| `evals/results/llm_judge_qwen2-5-3b.json` | LLM judge run (qwen2.5:3b, rubric 1.0.0) over the 75 rows, synthetic-era labels. |
| `evals/results/rag_ablation.json` | Retrieval ablation results: every chunker and method on both question sets. |
| `evals/run_eval.py` | Evaluation runner: concurrent scenarios, scoring, result files tagged by drafter, model, challenger and data source. |
| `prompts/breach_report.yaml` | Breach-note prompt 2.1.0: system rules, few-shot examples, user and tool prompts, changelog. |
| `prompts/challenger.yaml` | Challenger prompt 1.1.0: independent classification rules, tool prompt, changelog. |
| `prompts/judge.yaml` | LLM judge rubric 1.0.0: SUPPORTED or NOT_SUPPORTED with a reason. |
| `prompts/var_commentary.yaml` | Daily VaR commentary prompt 1.0.0. |
| `requirements.txt` | Python dependencies. |
| `riskdesk/__init__.py` | Package marker and version. |
| `riskdesk/agents/__init__.py` | Package marker for the agents. |
| `riskdesk/agents/challenger.py` | Challenger agent: read-only tools, its own schema, comparison rules, fail-safe. |
| `riskdesk/agents/commentary.py` | Daily VaR commentary workflow: today against yesterday, grounded and queued for approval. |
| `riskdesk/agents/drafters.py` | Drafters: template, and Ollama constrained to a JSON schema; note validation with pydantic. |
| `riskdesk/agents/graph.py` | Investigation graph: triage, attribution, challenge, policy lookup, draft, validate, human and approval gates. |
| `riskdesk/agents/tool_agent.py` | Function-calling drafter: validated tool calls to engine tools; schema-constrained final note. |
| `riskdesk/audit.py` | Hash-chained audit log with verification. |
| `riskdesk/config.py` | Paths and settings: data, prompts, traces, approvals, evaluation files, Ollama URL and model. |
| `riskdesk/engine/__init__.py` | Package marker for the risk engine. |
| `riskdesk/engine/backtest.py` | Kupiec test, Basel traffic-light zones (amber naming), rolling 250-day backtest. |
| `riskdesk/engine/book.py` | The 40-position three-desk book, built from the market's own names and rates. |
| `riskdesk/engine/instruments.py` | Black-Scholes options, cash and FX forward valuation, analytic Greeks and sensitivities. |
| `riskdesk/engine/limits.py` | Limit calibration (1.5x baseline), limit status with warning and breach, ranking of breaches. |
| `riskdesk/engine/market.py` | Market structure, seeded synthetic generator, regime-shock and bad-tick helpers, and the loader dispatch (real by default). |
| `riskdesk/engine/pla.py` | P&L attribution test (MAR32.42): Spearman, KS, zones; linear risk-theoretical model. |
| `riskdesk/engine/realdata.py` | Real data loader: fetch from Yahoo Finance, ECB and FRED; build the market; realised-volatility factor. |
| `riskdesk/engine/risk.py` | Historical, parametric and Monte Carlo VaR; expected shortfall; Euler component VaR. |
| `riskdesk/engine/stress.py` | Named hypothetical scenarios and worst historical windows, both directions; names read from the market. |
| `riskdesk/guardrails/approval.py` | Approval queue: JSON storage, process-wide lock, named-reviewer allowlist, audit of decisions. |
| `riskdesk/guardrails/grounding.py` | Numeric grounding: every figure in a note must match a tool output or a whitelisted constant. |
| `riskdesk/guardrails/injection.py` | Prompt-injection pattern screen for retrieved text; quarantine of flagged passages. |
| `riskdesk/guardrails/pii.py` | PII filter: Presidio with custom trader and counterparty recognisers; regex fallback. |
| `riskdesk/guardrails/schemas.py` | Pydantic models: findings, drivers, attribution, investigation report, approval items. |
| `riskdesk/mcp/__init__.py` | Package marker for the MCP server. |
| `riskdesk/mcp/server.py` | MCP server: ten engine tools over stdio. |
| `riskdesk/monitoring.py` | Run health from the trace file, eval series, drift chart, report writer. |
| `riskdesk/rag/__init__.py` | Package marker for retrieval. |
| `riskdesk/rag/index.py` | Chunkers (section and window), BM25, dense embeddings, hybrid fusion, retrieval metrics. |
| `riskdesk/rag/pgstore.py` | pgvector store: table, HNSW index, search, same interface as the in-memory index. |
| `riskdesk/tools.py` | Tools layer: every function the agents and the MCP server may call, each audited. |
| `scripts/build_data.py` | Builds knowledge-base incident logs, retrieval questions and the limits file. |
| `scripts/fetch_real_data.py` | Refreshes the real market data and its provenance in data/real/. |
| `tests/test_agents_v2.py` | Tests for the function-calling drafter, note schema, checks, retrieval metrics, async graph. |
| `tests/test_challenger.py` | Tests for the challenger: tool validation, comparison, agent loop, graph behaviour. |
| `tests/test_engine.py` | Tests for pricing, Greeks, VaR, ES, Euler, Monte Carlo, stress, Kupiec, Basel zones. |
| `tests/test_graph.py` | Tests for the investigation graph paths and the approval gate. |
| `tests/test_guardrails.py` | Tests for grounding, PII, injection, audit tamper detection, approval rules. |
| `tests/test_mcp_commentary.py` | Tests for MCP tool registration and output, audit entries, policy search, commentary. |
| `tests/test_monitoring.py` | Tests for the run-health summary on a hand-made trace file. |
| `tests/test_pgstore.py` | Tests for the pgvector backend against the live container (skipped without it). |
| `tests/test_pla.py` | Tests for the PLA zone thresholds and the cash-only control. |
| `ui/app.py` | Streamlit dashboard: Limits, Investigate, Approval queue and Monitoring tabs. |

## 21. Commit history (every commit)

Generated from `git log` at the time of writing, newest first.

| Commit | Date | Message |
| --- | --- | --- |
| `b51dbf4` | 2026-11-12 | Record the full 100-scenario function-calling run on the synthetic market |
| `23420eb` | 2026-11-12 | Record synthetic-data runs: challenger prompt 1.1.0 and LLM judge |
| `a094a14` | 2026-11-12 | Document the real market data: sources, provenance and assumptions |
| `686c008` | 2026-11-12 | Re-run the golden-set evaluation on real market data |
| `84e09b5` | 2026-11-12 | Use the amber zone name in the backtest retrieval question |
| `a773d99` | 2026-11-12 | Use real market data by default; read names and rates from the market |
| `a20d130` | 2026-11-12 | Add real market data loader with provenance |
| `736c2a2` | 2026-11-12 | Update progress record: PLA test and LLM judge |
| `aae7e80` | 2026-11-12 | Update README and monitoring plan for the new components |
| `d11bd39` | 2026-11-12 | Add P&L attribution results to the validation report |
| `dd4d78f` | 2026-11-12 | Add LLM judge for citation support, measured against labels |
| `e17cd82` | 2026-11-12 | Add P&L attribution test (MAR32.42) |
| `7a850b5` | 2026-11-12 | Update progress record: monitoring, labelling and challenger trials |
| `f1e362e` | 2026-11-12 | Name challenger result files by challenger prompt version |
| `89c28d6` | 2026-11-12 | Tighten challenger classification rules (prompt 1.1.0) |
| `19029b0` | 2026-11-12 | Record challenger trial on the first 12 scenarios (prompt 1.0.0) |
| `3a76ca7` | 2026-11-12 | Clarify the rule for uncertain labels in the labelling guide |
| `7d8300c` | 2026-11-12 | Add run health and eval drift to the dashboard |
| `dbace86` | 2026-11-12 | Add labelling guide for the citation-support judge |
| `f8dbaf0` | 2026-11-12 | Separate automated judge labels from human labels |
| `dece66d` | 2026-11-12 | Document the challenger step and its control |
| `5aa6e67` | 2026-11-12 | Record challenger agreement and disagreements in evaluation output |
| `e83da2c` | 2026-11-12 | Add challenger agent for independent second review |
| `8ad7d2c` | 2026-11-12 | Add embedding, database and HTTP client dependencies |
| `f77c294` | 2026-11-12 | Normalise line endings to LF across the repository |
| `cc510a8` | 2026-11-12 | Add model-risk documentation, breach process specification and progress log |
| `79f72e2` | 2026-11-12 | Add unit and integration tests |
| `0e106ca` | 2026-11-12 | Add golden-set evaluation, judge calibration and CI gate |
| `2fdd0ac` | 2026-11-12 | Add investigation agents, function-calling drafter, MCP server and dashboard |
| `a0ed466` | 2026-11-12 | Add hybrid retrieval with sentence embeddings and a pgvector backend |
| `a7f4e9f` | 2026-11-12 | Add guardrails: grounding gate, PII filtering, injection screen, approval gate and audit log |
| `812d774` | 2026-11-12 | Add synthetic knowledge base, calibrated limits, reviewer allowlist and versioned prompts |
| `23937ab` | 2026-11-12 | Add risk engine: pricing, VaR, expected shortfall, stress, limits and backtesting |
| `5bdf533` | 2026-11-12 | Set up project structure, configuration and CI workflow |

## 22. Chronological log

- **Project set-up.** Engine core, synthetic market, book, risk measures, stress, limits, backtest, audit log, knowledge base, and the first tests.
- **Guardrails and agents.** Grounding gate, PII filter, injection screen, approval queue, investigation graph with human gates, template drafter, golden set, evaluation runner and CI gate.
- **MCP, dashboard and first evaluation.** MCP server over the engine, Streamlit dashboard, first 100-scenario run (template): 100% breach on the intended desk.
- **Judge and labels.** Citation-support judge built; 50 real citations with negative controls; first automated-reviewer labels; kappa 0.20; a citation defect found and fixed.
- **Local models.** Free-text drafting with qwen2.5:0.5b (37% of figures unsupported, all blocked); function-calling drafter; schema-constrained output; content check; citation control; 3B model trials.
- **Retrieval.** Paraphrased 59-question set; ablation over two chunkers and four methods; sentence embeddings; pgvector backend tested against the Postgres container.
- **Challenger.** Second agent built; trials at prompt 1.0.0 (6 false alarms of 12) and 1.1.0 (3 of 12).
- **Monitoring.** Run health and eval drift on the dashboard; labels split into automated and human columns; labelling guide.
- **P&L attribution.** MAR32.42 test built and added to the report and the MCP server.
- **LLM judge.** Rubric 1.0.0; 75 rows judged; kappa 0.10 against the automated reviewer.
- **Repository.** Created on GitHub; history cleaned of a local file name before the first push; line endings normalised; CI dependencies added; every change committed and pushed.
- **Real data.** Feasibility checked (FRED, ECB and VIX reachable; Yahoo Finance rate-limited on one occasion and working later); loader and stored data committed; engine reads names and rates from the market; limits recalibrated; golden set regenerated (98% breach); documentation written; merged to `main`.
- **Synthetic-era results committed.** Full 3B function-calling run (75% task completion), challenger 1.1.0 trial, LLM judge run.
- **This record.** Full project record written.
