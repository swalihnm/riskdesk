# Workflow documentation and change log: RiskDesk

## Breach-investigation workflow
| Stage | Node | Inputs | Outputs | Failure modes and handling |
| --- | --- | --- | --- | --- |
| 1. Triage | `triage` | Limit rows for all desks | Ranked breaches; top breach selected | No breach ends the run. Ties are ordered by utilisation. |
| 2. Attribution | `attribution` | Desk positions, market history, limits, baseline | Component VaR by underlying, data flags, classification, confidence | Data flag: classified as data issue, escalated. Limit below 60% of baseline: classified as limit error, escalated. Margin below 1.25: escalated. |
| 3. Policy lookup | `policy_lookup` | Classification, metric | Up to two citation IDs | Quarantined passages excluded. No citation is allowed to invent an ID. |
| 4. Draft | `draft_report` | Engine facts, citations, prompt version | Draft text | LLM failure: template fallback, recorded. |
| 5. Validate | `validate` | Draft, all tool outputs | Redacted text, grounding result, validated report | Unsupported number or schema error: retry once, then human review. |
| 6a. Human review | `queue_review`, `human_review` | Report or no-report payload | Queue item; pause for named reviewer | Limit-calibration cases also create a proposal, which is never applied. |
| 6b. Approval | `queue_approval`, `approval_gate` | Validated report | Queue item; pause for named reviewer | Rejected items are recorded with the reviewer and note. |

Every node writes to the audit log and the trace file.

## Daily commentary workflow
Compares each desk's one-day 99% VaR today and yesterday, drafts two sentences from those numbers, runs the same grounding and PII checks, and queues the text for approval. Blocked text is recorded and not queued.

## Change log
| Date | Version | Change | Eval run | Approved by |
| --- | --- | --- | --- | --- |
| 2026-11-12 | engine 0.1.0 | Initial engine: pricing, VaR (historical, parametric, Monte Carlo), ES, component VaR, stress, backtest | Base-book backtest: 4 exceptions, green | Not yet reviewed |
| 2026-11-12 | prompt breach_report 1.0.0 | First drafting prompt | Not run | Not reviewed |
| 2026-11-12 | prompt breach_report 1.1.0 | Added rule to copy figures from FACTS only and omit unsupported figures | Golden set: 98% breach, 100% root cause, 0 shipped | Not reviewed |
| 2026-11-12 | graph | Fixed: limit-change proposal not queued on escalation path | Test added; suite passes | Not reviewed |
| 2026-11-12 | graph | Ambiguity threshold aligned to policy (margin below 1.25) | Golden set escalation 100% (constructed cases) | Not reviewed |
| 2026-11-12 | engine | Stress run in both directions | Base limits recalibrated | Not reviewed |
| 2026-11-12 | grounding | Fixed false unsupported numbers and percent matching | Suite passes | Not reviewed |
| 2026-11-12 | eval scoring | Breached and ranked-first now recorded separately; multi-breach generator uses largest exposure | Golden set: 100% breach, 100% ranked first; baseline reset | Not reviewed |
| 2026-11-12 | approval gate | Reviewer allowlist added (`data/reviewers.json`, role placeholders to replace with named people) | Test added; suite 48 passing | Not reviewed |
| 2026-11-12 | knowledge base | SS1/23 and SR 26-2 corrected against primary texts (current SS1/23 effective 23 April 2026; SR 26-2 scope excludes generative and agentic AI) | Retrieval recall@5 still 1.0 on 40 questions | Not reviewed |

Each change needs a named reviewer before it is treated as approved. "Not reviewed" means the change has not been through a second-line review.
