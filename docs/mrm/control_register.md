# Control register: RiskDesk

| ID | Control | What it prevents | How it is tested | Evidence |
| --- | --- | --- | --- | --- |
| C-01 | Engine is the only source of numbers | LLM-invented risk figures | Grounding gate on every draft; unit tests | `riskdesk/guardrails/grounding.py`; `tests/test_guardrails.py` |
| C-02 | Unsupported numbers blocked before queueing | Wrong figures reaching a reviewer | Gate test; golden-set `unsupported_numbers_shipped` must be 0 | `evals/results/latest_template.json` |
| C-03 | Named human required for any decision | Agent self-approval | Test that agent and system reviewers are refused | `tests/test_guardrails.py::test_approval_requires_named_human` |
| C-04 | Limit changes are proposals only | Agent changing a limit | Test that proposals carry `applied: false`; no code path applies them | `tests/test_graph.py::test_limit_error_is_classified_and_proposal_queued` |
| C-05 | Data-quality check before market conclusions | A bad price presented as a market move | Golden-set data-quality cases, 17 of 17 classified correctly when breached | `evals/golden.py` |
| C-06 | Escalation when attribution is ambiguous | Overconfident driver attribution | Constructed margins at about 1.1 and 2.5 | `evals/golden.py`; `tests/test_graph.py` |
| C-07 | PII and confidential-name filter on every draft | Personal or counterparty names in reports | Presidio plus custom recognisers; regex fallback | `riskdesk/guardrails/pii.py`; tests |
| C-08 | Prompt injection screen on free text | Instructions hidden in notes | Pattern tests; quarantine of flagged passages in retrieval | `riskdesk/guardrails/injection.py` |
| C-09 | Hash-chained audit log | Silent edits to the record | Tamper test changes one entry and verification fails | `tests/test_guardrails.py::test_audit_chain_verifies_and_detects_tampering` |
| C-10 | Prompt versioning and change gate | Silent prompt drift | CI runs the golden set on prompt changes and fails on regressions | `.github/workflows/ci.yml`; `evals/ci_gate.py` |
| C-11 | Output schema validation | Malformed reports reaching queues | Pydantic models at the report boundary | `riskdesk/guardrails/schemas.py` |
| C-12 | Fallback to template when the LLM fails | Pipeline failure or silent bad output | Recorded as `template_fallback` in each run | `riskdesk/agents/graph.py::draft_report` |
| C-13 | Tool allowlist and argument validation for the local model | The model calling an unknown tool or passing an invalid desk or method | Scripted-model tests: unknown tool, bad desk, bad method, extra argument, over-long query, all rejected and not executed | `riskdesk/agents/tool_agent.py::validate_call`; `tests/test_agents_v2.py` |
| C-14 | Schema-constrained output from the local model | Free text that cannot be parsed or validated | Ollama `format` constraint on the final call; pydantic validation before use | `riskdesk/agents/drafters.py::parse_note`; test for invalid JSON |
| C-15 | Content check on model notes | An off-topic note, or one that echoes the prompt, reaching review | Desk and classification must be named; prompt echo rejected; falls back to the template and records the reason | `riskdesk/agents/graph.py::content_check`; eval `content_check_failures` |
| C-16 | Citation control | A note citing a policy section that does not exist | Every policy ID in a note must come from policy lookup or a tool result | `riskdesk/agents/graph.py::validate`; test `test_validate_blocks_policy_id_that_no_tool_returned` |
| C-17 | Approval-queue lock | Concurrent runs corrupting the queue file | Process-wide lock around every read-modify-write | `riskdesk/guardrails/approval.py::_LOCK` |
| C-18 | Independent challenger agent | The first analyst's classification going unchallenged | Challenger sees only desk and metric, uses four read-only tools, and reaches its own conclusion. Disagreement, confidence below 0.5, or a failed challenge escalates to a human. The challenger cannot remove an escalation | `riskdesk/agents/challenger.py::compare`, `riskdesk/agents/graph.py::challenge_node`; tests in `tests/test_challenger.py` (15) |

## Gaps
- No control yet checks the regulatory text against the primary source (manual task).
- No control yet checks the judge's accuracy (kappa not measured).
- Access control is not implemented: the approval queue is a local JSON file. Any production use needs authentication and role-based approval.
- The audit log is local and tamper-evident, not tamper-proof. Production needs write-once storage.
