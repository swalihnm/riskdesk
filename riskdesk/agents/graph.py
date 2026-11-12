"""Breach-investigation LangGraph.

Stages (node names in brackets):
  1. Triage               [triage]              rank limit breaches by utilisation; no breach ends the run
  2. Attribution          [attribution]         Euler component VaR, data-quality and limit-calibration checks, classify
  3. Policy lookup        [policy_lookup]       hybrid retrieval over policy and regulatory text (citations only)
  4. Draft and validate   [draft_report, validate]  prose from engine facts; numeric grounding + PII redaction; retry once
  5. Human gates          [queue_review, human_review, queue_approval, approval_gate]
                          escalated cases pause for a risk manager; others pause for approval.
                          Limit-change proposals are queued but never applied by the agent.

Interrupts only occur in the two gate nodes. Anything that writes to a queue happens in the node before,
because LangGraph re-runs a node from its start when it resumes.
"""

from __future__ import annotations

import asyncio
import json
import math
import operator
import os
import re
import time
import uuid
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from riskdesk import audit
from riskdesk.agents.drafters import TemplateDrafter, get_drafter, load_prompt, timed
from riskdesk.agents.tool_agent import run_tool_agent
from riskdesk.config import APPROVAL_PATH, TRACE_PATH
from riskdesk.engine.limits import breaches as rank_breaches
from riskdesk.guardrails import approval
from riskdesk.guardrails.grounding import check_grounding
from riskdesk.guardrails.pii import redact
from riskdesk.guardrails.schemas import Classification, InvestigationReport
from riskdesk.tools import Session, attribution, baseline, data_checks, limit_status, search_policy

SESSIONS: dict = {}
METRIC_LABEL = {"var99": "one-day 99% VaR", "stress_loss": "worst stress loss", "vega_pts": "absolute vega"}
ESCALATE_BELOW_CONFIDENCE = 0.5
# Policy (escalation_matrix.md): ambiguous means the top two drivers are within 20%, i.e. margin < 1.25.
# confidence = (margin - 1) / 0.5, capped to [0, 1], so margin 1.25 gives 0.5 and anything below escalates.
CONFIDENCE_FLOOR_MARGIN = 1.0
CONFIDENCE_SCALE = 0.5


class State(TypedDict, total=False):
    run_id: str
    drafter_kind: str
    approval_path: str
    status: str
    desk: str
    metric: str
    value: float
    limit: float
    utilisation: float
    limit_status: str
    breach_count: int
    all_breaches: list
    attribution: dict
    flags: list
    baseline_var99: float
    hard_var99: float
    classification: str
    top_driver: str | None
    top_share: float | None
    margin_ratio: float
    confidence: float
    escalate: bool
    citations: list
    draft_text: str
    draft_attempts: int
    drafter_used: str
    tool_calls: list
    draft_fallback_reason: str | None
    grounding: dict
    pii_entities: list
    report: dict | None
    queue: str
    approval_id: str | None
    decision: dict | None
    tool_outputs: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def _trace(state: State, node: str, started: float, extra: dict | None = None) -> dict:
    rec = {"run_id": state.get("run_id"), "node": node, "latency_ms": (time.perf_counter() - started) * 1000,
           "prompt_version": load_prompt()["version"], "drafter": state.get("drafter_used", state.get("drafter_kind")),
           **(extra or {})}
    os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    audit.append(f"node.{node}", {k: v for k, v in rec.items() if k not in ("latency_ms",)})
    return rec


def triage(state: State) -> dict:
    t = time.perf_counter()
    s: Session = SESSIONS[state["run_id"]]
    rows = limit_status(s)
    ranked = rank_breaches(rows)
    out = {"tool_outputs": [{"limit_rows": rows}], "breach_count": len(ranked),
           "all_breaches": [{"desk": b["desk"], "metric": b["metric"], "utilisation": b["utilisation"]}
                            for b in ranked]}
    if not ranked:
        out["status"] = "no_breach"
    else:
        top = ranked[0]
        out.update({"status": "breach", "desk": top["desk"], "metric": top["metric"], "value": top["value"],
                    "limit": top["limit"], "utilisation": top["utilisation"], "limit_status": top["status"]})
    out["trace"] = [_trace(state | out, "triage", t)]
    return out


def attribution_node(state: State) -> dict:
    t = time.perf_counter()
    s: Session = SESSIONS[state["run_id"]]
    desk = state["desk"]
    att = attribution(s, desk)
    dq = data_checks(s, desk)
    base = baseline(s, desk)
    flags = dq["flags"]
    margin = att["margin_ratio"]
    confidence = max(0.0, min(1.0, (margin - CONFIDENCE_FLOOR_MARGIN) / CONFIDENCE_SCALE))
    if flags:
        cls = Classification.DATA_ISSUE
    elif state["metric"] == "var99" and base["hard_var99_limit"] < 0.6 * base["baseline_var99"]:
        cls = Classification.LIMIT_ERROR
    else:
        cls = Classification.MARKET_MOVE
    top = att["drivers"][0] if att["drivers"] else None
    escalate = confidence < ESCALATE_BELOW_CONFIDENCE or cls != Classification.MARKET_MOVE
    out = {
        "attribution": att, "flags": flags, "baseline_var99": base["baseline_var99"],
        "hard_var99": base["hard_var99_limit"], "classification": cls.value,
        "top_driver": top["underlying"] if top else None,
        "top_share": top["share"] if top else None, "margin_ratio": margin,
        "confidence": confidence, "escalate": escalate,
        "tool_outputs": [att, dq, base],
    }
    out["trace"] = [_trace(state | out, "attribution", t, {"classification": cls.value, "escalate": escalate})]
    return out


def policy_lookup(state: State) -> dict:
    t = time.perf_counter()
    s: Session = SESSIONS[state["run_id"]]
    query = {
        Classification.MARKET_MOVE.value: f"{state['metric']} breach response escalation desk head market risk",
        Classification.DATA_ISSUE.value: "jump check failed price data incident data owner stale price",
        Classification.LIMIT_ERROR.value: "limit calibration hard limit below baseline approval change",
    }[state["classification"]]
    hits = search_policy(s, query, 10)
    # Citations must be policy or regulatory text. Incident logs are precedent: they can inform a note,
    # but they do not state how a case should be handled, so they are never cited as the policy basis.
    citations = [h["id"] for h in hits
                 if not h["quarantined"] and not h["id"].startswith("incident_logs#")][:2]
    out = {"citations": citations, "tool_outputs": [{"policy_hits": [h["id"] for h in hits]}]}
    out["trace"] = [_trace(state | out, "policy_lookup", t, {"citations": citations})]
    return out


def _facts(state: State) -> dict:
    return {
        "desk": state["desk"], "metric_label": METRIC_LABEL[state["metric"]],
        "value": state["value"], "limit": state["limit"], "utilisation": state["utilisation"],
        "status": state["limit_status"], "classification": state["classification"],
        "top_driver": state.get("top_driver"), "top_share": state.get("top_share"),
        "escalate": state["escalate"],
    }


def content_check(text: str, state: State) -> tuple[bool, str]:
    """A model note must name the desk and the classification, and must not echo the prompt.

    The grounding gate checks figures; this checks that the note is about the case at all.
    """
    low = text.lower()
    if state["desk"].lower() not in low:
        return False, "desk not named"
    synonyms = {
        "market_move": ["market move", "market-move", "market"],
        "data_issue": ["data issue", "data-issue", "data"],
        "limit_error": ["limit error", "limit calibration", "calibration", "limit set"],
    }
    if not any(s in low for s in synonyms.get(state["classification"], [state["classification"]])):
        return False, "classification not named"
    for leaked in ("classification already decided", "a breach needs a note", "first call limit_status"):
        if leaked in low:
            return False, "prompt echoed"
    return True, ""


def draft_report(state: State) -> dict:
    """Drafts the note. drafter 'tools' runs the function-calling agent; any failure falls back to the template."""
    t = time.perf_counter()
    prompt = load_prompt()
    facts = _facts(state)
    kind = state.get("drafter_kind") or "template"
    attempts = state.get("draft_attempts", 0) + 1
    citations = state.get("citations", [])
    extra_outputs: list = []
    tool_calls: list = []
    reason = None
    if kind == "tools":
        ctx = {"desk": state["desk"], "metric": state["metric"], "classification": state["classification"]}
        ta = asyncio.run(run_tool_agent(SESSIONS[state["run_id"]], ctx, prompt))
        tool_calls = ta["tool_calls"]
        extra_outputs = ta["tool_outputs"]
        if ta["summary"]:
            res, used = {"text": ta["summary"], "tokens": ta["tokens"]}, "ollama_tools"
        else:
            reason = ta["error"] or "no valid summary"
            res, used = TemplateDrafter().draft(facts, citations, prompt), "template_fallback"
    else:
        try:
            drafter = get_drafter(kind)
            res = timed(drafter.draft, facts, citations, prompt)
            used = drafter.name
        except Exception as e:
            reason = f"{type(e).__name__}: {str(e)[:200]}"
            res, used = TemplateDrafter().draft(facts, citations, prompt), "template_fallback"
    if used in ("ollama", "ollama_tools") and reason is None:
        ok, why = content_check(res["text"], state)
        if not ok:
            reason = f"content_check_failed: {why}"
            res, used = TemplateDrafter().draft(facts, citations, prompt), "template_fallback"
    out = {"draft_text": res["text"], "draft_attempts": attempts, "drafter_used": used,
           "tool_outputs": [{"facts": facts}] + extra_outputs, "tool_calls": [c["name"] for c in tool_calls],
           "draft_fallback_reason": reason}
    out["trace"] = [_trace(state | out, "draft_report", t, {"tokens": res.get("tokens", 0),
                                                           "llm_latency_ms": res.get("latency_ms"),
                                                           "tool_calls": len(tool_calls),
                                                           "fallback_reason": reason})]
    return out


_POLICY_ID = re.compile(r"\b(?:limit_policy|escalation_matrix|market_risk_reference|regulatory_summaries|incident_logs)#[a-z0-9-]+")


def validate(state: State) -> dict:
    t = time.perf_counter()
    prompt = load_prompt()
    clean = redact(state["draft_text"])
    g = check_grounding(clean["text"], state["tool_outputs"])
    # Citation control: any policy ID named in the note must be one the policy lookup or a tool returned.
    allowed_ids = set(state.get("citations", []))
    for o in state.get("tool_outputs", []):
        for h in (o.get("policy_hits") or []):
            allowed_ids.add(h["id"] if isinstance(h, dict) else h)
    named = set(_POLICY_ID.findall(clean["text"]))
    bad_ids = sorted(named - allowed_ids)
    if bad_ids:
        g = {**g, "unsupported": g["unsupported"] + [f"citation:{b}" for b in bad_ids], "ok": False}
    out = {"grounding": g, "pii_entities": clean["entities"], "draft_text": clean["text"]}
    if g["ok"]:
        try:
            rep = InvestigationReport(
                desk=state["desk"], metric=state["metric"],
                classification=Classification(state["classification"]),
                top_driver=state.get("top_driver"), confidence=state["confidence"],
                escalate=state["escalate"], summary=clean["text"],
                citations=state.get("citations", []), prompt_version=prompt["version"],
                drafter=state.get("drafter_used", "unknown"))
            out["report"] = rep.model_dump(mode="json")
        except Exception as e:  # schema failure is treated like a grounding failure
            out["grounding"] = {**g, "ok": False, "schema_error": str(e)[:200]}
            out["report"] = None
    else:
        out["report"] = None
    out["trace"] = [_trace(state | out, "validate", t, {"grounding_ok": out["grounding"]["ok"]})]
    return out


def route_after_validate(state: State) -> str:
    if state.get("report") is None:
        if state.get("draft_attempts", 0) < 2:
            return "draft_report"
        return "queue_review"
    return "queue_review" if state.get("escalate") else "queue_approval"


def _queue_limit_proposal(state: State) -> None:
    """A limit-calibration case always produces a proposal for the approval gate. The agent never applies it."""
    proposed = float(-(-state["baseline_var99"] * 1.5 // 1000) * 1000)
    approval.submit(state["approval_path"], "limit_change_proposal", state["desk"], {
        "metric": "var99", "current_limit": state["hard_var99"], "proposed_limit": proposed,
        "reason": "hard limit is below 60% of the baseline VaR", "applied": False})


def queue_review(state: State) -> dict:
    t = time.perf_counter()
    payload = state.get("report") or {"status": "no_valid_report", "desk": state["desk"],
                                      "unsupported_numbers": state.get("grounding", {}).get("unsupported", [])}
    item = approval.submit(state["approval_path"], "human_review", state["desk"], payload)
    if state.get("classification") == Classification.LIMIT_ERROR.value:
        _queue_limit_proposal(state)
    out = {"queue": "human_review", "approval_id": item.id}
    out["trace"] = [_trace(state | out, "queue_review", t)]
    return out


def human_review(state: State) -> dict:
    decision = interrupt({"approval_id": state["approval_id"], "queue": "human_review"})
    return {"decision": decision}


def queue_approval(state: State) -> dict:
    t = time.perf_counter()
    item = approval.submit(state["approval_path"], "investigation_report", state["desk"], state["report"])
    out = {"queue": "approval", "approval_id": item.id}
    out["trace"] = [_trace(state | out, "queue_approval", t)]
    return out


def approval_gate(state: State) -> dict:
    decision = interrupt({"approval_id": state["approval_id"], "queue": "approval"})
    approval.decide(state["approval_path"], state["approval_id"], decision["reviewer"],
                    bool(decision["approve"]), decision.get("note", ""))
    return {"decision": decision}


def route_after_triage(state: State) -> str:
    return "attribution" if state.get("status") == "breach" else END


def route_after_queue_review(state: State) -> str:
    return "human_review"


def build_graph():
    g = StateGraph(State)
    g.add_node("triage", triage)
    g.add_node("attribution", attribution_node)
    g.add_node("policy_lookup", policy_lookup)
    g.add_node("draft_report", draft_report)
    g.add_node("validate", validate)
    g.add_node("queue_review", queue_review)
    g.add_node("human_review", human_review)
    g.add_node("queue_approval", queue_approval)
    g.add_node("approval_gate", approval_gate)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage, {"attribution": "attribution", END: END})
    g.add_edge("attribution", "policy_lookup")
    g.add_edge("policy_lookup", "draft_report")
    g.add_edge("draft_report", "validate")
    g.add_conditional_edges("validate", route_after_validate,
                            {"draft_report": "draft_report", "queue_review": "queue_review",
                             "queue_approval": "queue_approval"})
    g.add_conditional_edges("queue_review", route_after_queue_review, {"human_review": "human_review"})
    g.add_edge("human_review", END)
    g.add_edge("queue_approval", "approval_gate")
    g.add_edge("approval_gate", END)
    return g.compile(checkpointer=MemorySaver())


_GRAPH = None


def _init(session: Session, drafter_kind: str | None, approval_path: str) -> tuple[dict, dict]:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    run_id = uuid.uuid4().hex[:12]
    SESSIONS[run_id] = session
    config = {"configurable": {"thread_id": run_id}}
    init = {"run_id": run_id, "drafter_kind": drafter_kind or os.environ.get("RISKDESK_DRAFTER", "template"),
            "approval_path": approval_path, "draft_attempts": 0, "tool_outputs": [], "trace": []}
    return init, config


def investigate(session: Session, drafter_kind: str | None = None, approval_path: str = APPROVAL_PATH) -> dict:
    """Run the graph until it finishes or pauses at a human gate. Returns a summary."""
    init, config = _init(session, drafter_kind, approval_path)
    final = _GRAPH.invoke(init, config)
    return _summarise(final, config)


async def investigate_async(session: Session, drafter_kind: str | None = None,
                            approval_path: str = APPROVAL_PATH) -> dict:
    """Async entry point. Many investigations can run concurrently with asyncio.gather.

    The graph nodes are synchronous and run in worker threads; the tool-calling drafter is async internally.
    """
    init, config = _init(session, drafter_kind, approval_path)
    final = await _GRAPH.ainvoke(init, config)
    return _summarise(final, config)


def _summarise(final: dict, config: dict) -> dict:
    run_id = config["configurable"]["thread_id"]
    paused = "__interrupt__" in final
    queue = final.get("queue") if paused else ("none" if final.get("status") != "breach" else final.get("queue"))
    return {
        "run_id": run_id,
        "status": final.get("status"),
        "all_breaches": final.get("all_breaches", []),
        "desk": final.get("desk"),
        "metric": final.get("metric"),
        "utilisation": final.get("utilisation"),
        "classification": final.get("classification"),
        "top_driver": final.get("top_driver"),
        "confidence": final.get("confidence"),
        "escalate": final.get("escalate"),
        "report": final.get("report"),
        "grounding": final.get("grounding"),
        "queue": queue,
        "paused": paused,
        "approval_id": final.get("approval_id"),
        "drafter": final.get("drafter_used"),
        "tool_calls": final.get("tool_calls", []),
        "draft_fallback_reason": final.get("draft_fallback_reason"),
        "trace": final.get("trace", []),
        "config": config,
    }


def resume(run_id: str, reviewer: str, approve: bool, note: str = "") -> dict:
    config = {"configurable": {"thread_id": run_id}}
    return _GRAPH.invoke(Command(resume={"reviewer": reviewer, "approve": approve, "note": note}), config)
