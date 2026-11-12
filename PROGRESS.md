# RiskDesk progress

**Completed: 93%** (last updated 12 November 2026, during the job-description upgrade)

Update cadence: a background timer wakes me every 10 minutes and I refresh this figure. The timer only runs while a session is active, and it does not survive a closed session.

Percentage = share of the plan that is built and checked. Items that need your labels, decisions or accounts count as open.

## What changed in this round (job-description gaps)
- **Function-calling agent:** the local model chooses engine tools through Ollama's tool-call interface. Arguments are validated, and every figure must come from a tool result. Tested offline with a scripted model and live once.
- **Real embeddings:** all-MiniLM-L6-v2 (free, local) replaces the character-trigram vectors for the main retriever. Retrieval ablation: 2 chunkers x 4 methods, on a paraphrased 59-question set.
- **Structured output:** the drafter is constrained to a JSON schema and validated before use. Few-shot examples added to prompt 2.0.0.
- **Async:** the tool agent is async, the graph has an async entry point, and the eval runs scenarios concurrently. The local model still handles one request at a time.
- **Specification:** `docs/spec/breach_flow.md` documents the manual process, the agent replacement, the failure modes and an SME sign-off table. The manual steps come from the policy text, not from observed practice, and need SME review.
- **Two new checks:** a content check (a note must name the desk and the classification, and must not echo the prompt) and a citation control (any policy ID in a note must come from policy lookup or a tool).
- **Approval queue lock:** concurrent runs could corrupt the JSON queue. A process-wide lock now guards it.

## Status by component

| Component | Status | Notes |
| --- | --- | --- |
| Synthetic market data and book | Done | Synthetic only. Real data is a decision for you. |
| Pricing, Greeks, VaR, ES, component VaR | Done, tested | Textbook prices; hand-checked parametric VaR; Euler sums to VaR. |
| Stress testing | Done, tested | Both directions. Named scenarios are analogues. |
| Limits | Done, tested | Calibrated at 1.5x baseline. |
| Backtesting | Done, tested | Zones named amber, per MAR32. |
| Audit log | Done, tested | Hash-chained; locked for concurrent writes. |
| Knowledge base | Done, checked | SS1/23, SR 26-2, Basel zones and the 97.5% ES level checked against primary texts. |
| Retrieval | Done, measured | Paraphrased set: hybrid recall@5 0.983; dense MRR 0.873. See ablation below. |
| Function-calling agent | Built, partly tested | Tool calls work with the 0.5B model. A 100-scenario run is not yet done. |
| Structured output and few-shot | Done | Prompt 2.0.0 with schema-constrained output. |
| Guardrails | Done, tested | Grounding, citation control, content check, PII, injection, approval gate with allowlist. |
| Investigation graph | Done, tested | Sync and async entry points. 70 tests in total pass. |
| Drafters | Done | Template, Ollama free text (v1.1, earlier run), Ollama constrained (v2.0). |
| Daily VaR commentary | Done, tested | Queues for approval. |
| MCP server | Done, tested over stdio | Nine tools. |
| Streamlit UI | Done, tested in harness | Not checked in a browser. |
| Golden set, eval runner, CI gate | Done | Template run: 100 of 100 breach, ranked first, 0 unsupported shipped. |
| Harder attribution | Done, small | 5 of 5. Too few to estimate accuracy. |
| Specification of breach process | Drafted | Needs an SME to validate the steps and sign off. |
| Judge (citation support) | Partly | Rule judge. AI-reviewer kappa 0.20. Human labels still needed. |
| Monitoring | Partly | Timer-driven refresh of this file; eval history table. Drift needs more runs. |
| Model-risk pack | Done, needs update | Needs the new tool-agent and retrieval results. |
| Launch materials | Done, needs update | Resume bullets must be checked against the new results. |
| docker-compose (Postgres + pgvector) | Running | Container up; pgvector extension in use. |
| pgvector retrieval backend | Built, tested | Same top-5 sections as the in-memory dense index on all 59 questions. 3 tests against the live container. |
| Langfuse tracing | Not built | |
| LLM judge | Not built | |
| Multi-agent (challenger agent) | Not built | |
| PLA test (MAR32) | Not built | |
| Hosted deployment | Not built | Needs your account. |

## Retrieval ablation (paraphrased set, 59 questions)

| Chunking | Method | recall@5 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- |
| section | BM25 | 0.831 | 0.753 | 0.796 |
| section | dense (MiniLM) | 0.966 | 0.873 | 0.897 |
| section | hybrid (RRF) | 0.983 | 0.858 | 0.889 |
| section | char-trigram baseline | 0.864 | 0.790 | 0.817 |
| window 60w/20 overlap | dense | 0.966 | 0.860 | 0.887 |
| window 60w/20 overlap | hybrid | 0.949 | 0.864 | 0.898 |

Reading: section chunking did at least as well as fixed windows. Hybrid gives the best recall, and dense alone the best rank. These questions were written by the same author as the knowledge base, so an independent set is still needed.

## Results (synthetic data only)

Template drafter, 100 golden scenarios (current code): 100% breach on the intended desk; 100% ranked first; 100% task completion; 0 unsupported numbers shipped. Root-cause accuracy 100% over 50 cases, but the shocks target the largest exposure, so it is an easy test.

Local model (`qwen2.5:0.5b`), free-text drafting, earlier full 100-scenario run: 37% of drafted numbers unsupported, all blocked by the gate, 49 runs fell back to the template, task completion 90%. This was the free-text drafter before the schema change.

Tool-calling agent (`qwen2.5:0.5b`), one case: called `limit_status` and `data_checks`, produced a note that passed the figure check. The note was poor and passed only because it had no figures, which is why the content check was added.

## What is left, and who owns it

**You:**
1. Human labels for the judge in `evals/judge_labels.csv`, then `python evals/judge.py --kappa`.
2. Real market data or a stated volatility assumption.
3. Named reviewers in `data/reviewers.json`.
4. Approval for a GitHub repository, a push and the CI run.
5. An SME to validate `docs/spec/breach_flow.md` and sign it.
6. An independent retrieval question set, written without seeing the knowledge base.

**Me, next:**
- Report the full 100-scenario function-calling run with `qwen2.5:3b` when it finishes, separately from the 0.5B model.
- Add the challenger agent (multi-agent) and the PLA test.
- Update the model-risk pack and the resume bullets with the new measured results only.

## Log
- 12 Nov (10-minute refresh): function-calling agent with `qwen2.5:3b` on the first 12 scenarios: 10 of 12 notes accepted; 2 fell back to the template because the note did not name the classification; 0 unsupported figures shipped; 7% of drafted figures were unsupported and blocked. Prompt bumped to 2.1.0 to require the classification in words. Full 100-scenario run in progress; still 91%.
- 12 Nov: earlier rounds (engine, knowledge base, guardrails, graph, golden set, MCP, UI, judge, model-risk pack, launch materials). See git-style history in this file's earlier versions.
- 12 Nov: job-description gap round: retrieval ablation, function-calling agent, schema output, async, spec document, content and citation checks, approval lock. Progress 93% after the pgvector backend was built and tested.
