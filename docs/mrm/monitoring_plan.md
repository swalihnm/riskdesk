# Monitoring plan: RiskDesk

## Metrics tracked
| Metric | Source | Frequency | Alert threshold |
| --- | --- | --- | --- |
| Root-cause accuracy | Golden-set eval | Each prompt change and weekly | Drop of more than 2 points vs baseline (CI) |
| Task completion | Golden-set eval | Weekly | Drop of more than 2 points |
| Unsupported numbers shipped | Golden-set eval, grounding gate | Every run | Any value above 0 is a stop |
| Injection breach rate | Golden-set eval | Weekly | Drop of more than 5 points (may indicate broken injections) |
| Node latency and tokens | Trace file (`data/traces/traces.jsonl`) | Per run | Median above 5 seconds for any non-LLM node |
| Fallback rate to template | Run records (`drafter` field) | Per run | Above 20% of runs |
| Audit chain integrity | `audit.verify()` | Daily, and in the UI | Any failure is a stop |

## Drift
- Eval history is appended to `evals/results/history.jsonl` on each full run. `riskdesk/monitoring.py` writes the table and the drift chart.
- A weekly scheduled run of `evals/run_eval.py` is needed to produce a trend. Until then the chart does not exist.

## Re-validation triggers
- Any change to a prompt version, the drafter model, the retrieval index or the knowledge base.
- Any change to the risk engine's method, window or confidence level.
- A new desk, a new instrument type, or a new underlying.
- Any unsupported number shipped, audit-chain failure or unreviewed approval.

## Gaps
- Latency and token figures in the trace file are not yet separated by run, so they mix tests and trials.
- No production monitoring stack (Langfuse is planned but not deployed).
- Drift is measured on synthetic scenarios only.
