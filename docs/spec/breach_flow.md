# Breach investigation: manual process and agent replacement

Written for: the market-risk SME who will review it, and the model-risk reviewer. Status: DRAFT. The manual steps below are written from the RiskDesk policy text (`data/kb/`), not from observed practice in any bank. A market-risk SME must check each step against how their desk actually works and sign off in section 6.

## 1. Scope
A limit breach on one desk and one metric (one-day 99% VaR, worst stress loss, or absolute vega) in the synthetic book. Out of scope: the decision to change a limit or a position, client communication, and any regulatory report.

## 2. Manual process (as written in policy)

| Step | Who | What they do | Policy source |
| --- | --- | --- | --- |
| M1 | Risk system | Flags BREACH when utilisation exceeds 100% of the hard limit; WARNING from 80% | limit_policy: hard limits and warning levels |
| M2 | Market-risk analyst | Tells the desk head the same business day | limit_policy: breach response; escalation level 1 |
| M3 | Market-risk analyst | Checks the price data: any one-day move beyond six daily standard deviations fails the jump check | limit_policy: data quality before market conclusions |
| M4 | Market-risk analyst | If the jump check fails, raises a data incident to the data owner within one hour and marks the breach provisional | escalation matrix: data incidents |
| M5 | Market-risk analyst | Attributes the excess to risk drivers (component VaR by underlying) | limit_policy: breach response |
| M6 | Market-risk analyst | Checks whether the limit itself is set in error (hard limit below 60% of baseline VaR) | limit_policy: limit calibration |
| M7 | Market-risk analyst | Writes the breach note and sends it to the Market Risk manager the same day | escalation level 2 |
| M8 | Market-risk manager | Decides whether to escalate to the Head of Market Risk, and whether the case is ambiguous (top two drivers within 20%) | escalation level 2 and 3; human review queue |
| M9 | Head of Market Risk | Decides on any temporary excess, and approves any limit change | escalation level 3; limit calibration |
| M10 | Analyst | Records every step, its evidence and its decision | escalation matrix: documentation |

Manual pain points the agent is meant to reduce: finding the drivers (M5), finding the right policy section (M7 and M8), and writing a consistent note (M7).

## 3. Agent replacement

| Step | Agent node | Input | Output | Control point |
| --- | --- | --- | --- | --- |
| M1 | `triage` | limit utilisation for every desk and metric | ranked breaches | Engine only; no LLM |
| M3, M4 | `attribution` (data flags) | prices, previous close, daily sigma | data-issue classification | Jump check is deterministic |
| M5 | `attribution` | Euler component VaR by underlying | top driver, share, top-two margin | Deterministic; sums to the total |
| M6 | `attribution` (limit check) | hard limit, baseline VaR | limit-error classification | Deterministic |
| M7 | `policy_lookup` | classification | up to two policy citations | Citations must be policy text, not incident logs |
| M7 | `draft_report` | engine facts, citations; optionally tool calls | note text | Drafter cannot compute figures; content check; template fallback |
| M7 | `validate` | note, every tool output | grounding result, redacted text | Blocks any figure no tool returned and any policy ID not returned by lookup or a tool |
| M8 (second review) | `challenge` | desk and metric only, not the first classification | independent classification, top driver and confidence, from read-only tools | Can add an escalation, never remove one. Disagreement, confidence below 0.5, or a failed challenge escalates |
| M8 | `queue_review` / `human_review` | report or no-report payload | pause for a named reviewer | Escalated when confidence is below 0.5 (top-two margin below 1.25), or on data or limit cases |
| M9 | `queue_approval` / `approval_gate` | validated report; any limit proposal | pause for a named approver | Limit proposals are never applied by the agent; reviewer must be on the allowlist |
| M10 | `audit`, `trace` | every node and tool call | hash-chained log; JSONL trace | Tamper-evident |

## 4. Failure modes and handling

| Failure | Detection | Handling |
| --- | --- | --- |
| Model invents a figure | grounding gate | Note blocked; retry once; then human review with no report |
| Model cites a policy that does not exist | citation control | Note blocked as above |
| Model note is off-topic or echoes the prompt | content check | Template fallback, recorded as `content_check_failed` |
| Model makes an invalid tool call | argument validation | Call rejected and not executed; if no valid call, template fallback |
| Model server unavailable | exception in drafter | Template fallback, recorded |
| Data error mistaken for a market move | jump check | Classified data_issue and escalated |
| Two drivers almost equal | top-two margin below 1.25 | Escalated to human review |
| Limit set in error | hard limit below 60% of baseline | Classified limit_error; proposal queued, not applied |

## 5. Decisions the SME must make
1. Confirm the 80% warning level and the 100% breach level for each metric.
2. Confirm the six-sigma jump threshold and whether a verified market event should override it.
3. Confirm the 1.25 ambiguity threshold, or replace it with the desk's own rule.
4. Confirm that the agent may draft but never decide, and who signs the note.
5. Confirm the 60%-of-baseline rule for limit calibration.

## 6. Sign-off

| Role | Name | Date | Comments |
| --- | --- | --- | --- |
| Market-risk SME | (to be named) | | |
| Market-risk manager | (to be named) | | |
| Model-risk reviewer | (to be named) | | |
