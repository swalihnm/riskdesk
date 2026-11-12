# Validation report: RiskDesk

Scope: the risk engine, the investigation agent and the approval controls. Date of results: 12 November 2026. Data: synthetic only.

Structure follows the classic validation pillars (conceptual soundness, implementation, outcomes analysis and ongoing monitoring) and the five principles of PRA SS1/23.

Regulatory position, checked on 12 November 2026 against the primary texts:
- **SR 26-2** (Federal Reserve, 17 April 2026) supersedes SR 11-7. Its footnote 3 says generative AI and agentic AI models "are not within the scope of this guidance", but that governance and controls should still cover tools and systems outside its scope. RiskDesk's drafting agent is therefore outside SR 26-2 by the letter's own terms. This report applies the governance expectations to it voluntarily, and uses the SS1/23 principles and classic validation pillars for the rest.
- **PRA SS1/23** (Bank of England) was published 17 May 2023 and its current version took effect 23 April 2026. It applies to UK banks, building societies and certain PRA-designated investment firms with internal model approval. RiskDesk is not such a firm, so SS1/23 is used here as a reference framework, not a requirement. The 2026 amendments are not reviewed in this report.

## 1. Model identification and tiering
- Components: risk engine, limit framework, investigation graph, drafters, retrieval.
- Proposed tier: 2 (advisory). No component can change a limit or a position. Tier would move up if any output were connected to live limits or automated actions.

## 2. Conceptual soundness
| Design choice | Rationale | Assessment |
| --- | --- | --- |
| The LLM never computes numbers | Removes the largest hallucination risk in risk reporting | Enforced by the grounding gate (section 4) |
| Historical VaR as primary measure | No distributional assumption | Adequate; window of 250 days is short for stress |
| Parametric and Monte Carlo as cross-checks | Independent methods | Divergence for equity desks is expected (fat tails); documented |
| Euler component VaR for attribution | Sums exactly to the parametric VaR | Linear; approximate for options |
| Escalation when top-two drivers are within 20% | Matches the escalation policy | Tested with constructed margins (section 3) |
| Human approval for every output | Keeps accountability with a named person | Enforced in code: agent reviewers are refused |

## 3. Implementation testing
- Unit tests: 47 passing (`python -m pytest -q tests`). They cover Black-Scholes prices and Greeks against textbook values and bump-and-reprice, parametric VaR against a hand calculation, the normal ES formula, Euler allocation summing to VaR, Monte Carlo against the parametric measure for a linear book, Kupiec and the Basel zones, grounding, PII, injection screening, the audit chain, approval rules and graph paths.
- Hand check: a single cash position's parametric VaR, computed by hand from the sample standard deviation, equals the code output to the dollar (1,761).
- Defects found and fixed during build: see `PROGRESS.md`. The material ones were a stress floor that made the stress limit meaningless, a grounding regex that reported false unsupported numbers, and a limit-change proposal that was never queued on the escalation path.

## 4. Outcomes analysis
### 4.1 Engine backtest (base book, 250 days)
- Exceptions: 4 of 250. Basel zone: green (0 to 4 is green).
- Kupiec test: p = 0.38, model not rejected at 5%.

### 4.2 Golden-set eval (template drafter, 100 scenarios, prompt 1.1.0)
| Measure | Result | Limitation |
| --- | --- | --- |
| Injected breach on intended desk | 100% (100 of 100) | Injection size raised up to 12 times until the desk breaches |
| Intended desk ranked first (multi-breach included) | 100% (100 of 100) | Multi-breach cases use two shocks of different size |
| Root-cause accuracy | 100% (50 of 50 with a driver) | Shocks target the desk's largest exposure, so this is an easy case |
| Classification accuracy | 100% (of cases ranked first) | Data-quality, limit-error and market-move cases are constructed to be distinct |
| Escalation correctness | 100% (of cases ranked first) | Ambiguous cases constructed to measured margins of about 1.1 (escalate) and 2.5 (control) |
| Task completion | 100% (of breached) | Every breached run reached a gate with a validated report |
| Numeric hallucination rate in drafts | 0% | Trivially true for the template, which copies numbers from the engine |
| Unsupported numbers shipped | 0 | |

Scoring note: an earlier version required the intended desk to rank first, which failed when a shared underlying also breached a second desk. Scoring now records "breached" and "ranked first" separately. The rule change is recorded in the change log.

### 4.3 Local LLM drafter trial (`qwen2.5:0.5b` via Ollama, first 12 scenarios)
| Measure | Result |
| --- | --- |
| Unsupported share of drafted numbers | 64% |
| Unsupported numbers shipped to queues | 0 (blocked by the gate) |
| Runs that fell back to the template | 6 of 12 |
| Task completion | 92% |
| Median latency per run | about 63 seconds |

Finding: a 0.5-billion-parameter local model is not reliable for numbers. The gate prevents harm, but the drafter should not be used without the gate, and a larger model should be tested before any production-like use. The full 100-scenario run with this drafter has not been done.

### 4.4 Retrieval
Ablation on a paraphrased set of 59 questions (`evals/rag_eval_v2.jsonl`), section-level relevance:

| Chunking | Method | recall@5 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- |
| section | BM25 | 0.831 | 0.753 | 0.796 |
| section | dense (all-MiniLM-L6-v2) | 0.966 | 0.873 | 0.897 |
| section | hybrid (RRF of BM25 and dense) | 0.983 | 0.858 | 0.889 |
| section | character-trigram baseline | 0.864 | 0.790 | 0.817 |
| window 60 words, 20 overlap | dense | 0.966 | 0.860 | 0.887 |
| window 60 words, 20 overlap | hybrid | 0.949 | 0.864 | 0.898 |

The pgvector database returns the same top-5 sections as the in-memory dense index on all 59 questions (`tests/test_pgstore.py`).

Caveat: the same author wrote the questions and the knowledge base. The earlier set of 40 questions, written close to the headings, scored 1.0 for every method and does not discriminate. An independent question set is still needed before any retrieval claim is made.

### 4.5 Judge calibration
- The judge is a transparent keyword rule, not an LLM. `evals/judge_labels.csv` holds 75 rows: 50 real citations and 25 deliberate mismatches (negative controls).
- An AI reviewer (not a human) labelled all 75 rows. Against that reviewer, the rule judge agrees on all 50 real citations and on 4 of 25 mismatches, marking 21 mismatches SUPPORTED. Cohen's kappa is 0.20: slight agreement, and the rule cannot be relied on.
- A human reviewer's labels are still needed. Until they exist, no judge accuracy is reported.
- The review found a real citation defect: market-move cases cited a past incident record instead of the policy. Fixed; citations are now policy or regulatory text only.

### 4.6 Harder attribution check
`evals/hard_attribution.py` shocks a non-largest exposure, so the largest existing exposure is a distractor. The agent named the shocked underlying in 5 of 5 cases and never named the distractor. Five cases is too few to estimate accuracy: the other non-largest exposures cannot breach their desk within the tested injection range. A fair estimate needs more cases, which need a larger injection range or a larger book.

### 4.7 P&L attribution test (MAR32.42)
Hypothetical P&L (full revaluation) compared with risk-theoretical P&L (this project's linear sensitivities) over the same 250 days, per desk:

| Desk | Spearman | KS statistic | Zone |
| --- | --- | --- | --- |
| DESK_EQ | 1.000 | 0.016 | green |
| DESK_VOL | 1.000 | 0.016 | green |
| DESK_FX | 1.000 | 0.012 | green |
| Cash-only control | 0.99999 | 0.012 | green |

Reading: on one-day moves of about 1%, the linear model explains the full revaluation closely, including for the option desks. The test therefore does not discriminate between these desks. It would become informative on larger or gap moves, which this synthetic history contains only in its two stress episodes. The risk-theoretical model is this project's linear approximation, not a bank's model, so the zones are not a regulatory result.

## 5. Ongoing monitoring
See `monitoring_plan.md`. A single eval run is recorded. Drift cannot be assessed until the scheduled weekly runs have produced at least two points.

## 6. Open issues
1. The Basel traffic-light zones were confirmed from search results only; the 97.5% ES level was confirmed in MAR33.3 of the primary PDF. The SR 26-2 and SS1/23 points in the introduction were checked against the primary texts.
2. The judge is a rubric only, with no kappa yet.
3. The golden set is generated by the engine it tests, and its root-cause cases are easy by design. A harder set is needed before any accuracy claim.
4. The trace file accumulates runs from tests and the Ollama trial, so per-node latency figures mix sources. Per-run tracing should be separated before those figures are used.
5. No independent validator has reviewed this work.

## 7. Opinion
On the synthetic evidence, the engine's measures are internally consistent and the controls behave as designed. The results are not evidence of performance on real data, and the parts most at risk (the local drafter's numbers and the judge) are not yet validated. Recommendation: use only for demonstration until items 1 to 5 in section 6 are closed.
