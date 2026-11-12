"""Challenger agent tests. The local model is replaced by httpx.MockTransport, and the graph tests replace the
challenger with a stub, so these run offline."""

import asyncio
import json
import random

import httpx
import pytest

from evals.golden import INTENSITIES, build_scenario, to_session
from riskdesk.agents import challenger as C
from riskdesk.agents import graph
from riskdesk.agents.drafters import load_prompt
from riskdesk.tools import Session


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKDESK_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(graph, "TRACE_PATH", str(tmp_path / "traces.jsonl"))


@pytest.fixture(scope="module")
def base():
    return Session.base()


def _msg(content="", tool_calls=None, tokens=2):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"message": m, "eval_count": tokens}


def _tc(name, args=None):
    return {"function": {"name": name, "arguments": args or {}}}


def _client(responses):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(seen) - 1])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


# --- validation and comparison ---------------------------------------------

@pytest.mark.parametrize("name, args", [
    ("compute_var", {"desk": "DESK_EQ"}),          # not a challenger tool
    ("attribution", {"desk": "DESK_XYZ"}),         # desk not in book
    ("baseline", {"desk": "DESK_EQ", "method": "x"}),  # unexpected argument
    ("limit_status", {"desk": "DESK_EQ"}),         # takes no arguments
])
def test_challenger_rejects_bad_calls(name, args):
    assert C.validate_call(name, args) is not None


def test_challenger_tools_are_read_only_and_match_specs():
    spec_names = {t["function"]["name"] for t in C.TOOL_SPECS}
    assert spec_names == set(C.CHALLENGE_TOOLS)


def test_compare_agrees_when_everything_matches():
    agrees, reasons = C.compare({"classification": "market_move", "top_driver": "EQ_ALPHA"},
                                {"classification": "market_move", "top_driver": "EQ_ALPHA", "confidence": 0.9})
    assert agrees and reasons == []


def test_compare_flags_classification_driver_and_low_confidence():
    agrees, reasons = C.compare({"classification": "market_move", "top_driver": "EQ_ALPHA"},
                                {"classification": "data_issue", "top_driver": "EQ_BETA", "confidence": 0.3})
    assert not agrees
    assert len(reasons) == 3


# --- the challenger loop against a scripted model --------------------------

def test_challenger_gathers_evidence_then_returns_structured_conclusion(base):
    client, seen = _client([
        _msg(tool_calls=[_tc("limit_status")]),
        _msg(tool_calls=[_tc("attribution", {"desk": "DESK_FX"})]),
        _msg(tool_calls=[_tc("baseline", {"desk": "DESK_FX"})]),
        _msg(tool_calls=[_tc("data_checks", {"desk": "DESK_FX"})]),
        _msg(),
        _msg(content=json.dumps({"classification": "market_move", "top_driver": "FX_GBPUSD", "confidence": 0.8})),
    ])
    out = asyncio.run(C.run_challenger(base, {"desk": "DESK_FX", "metric": "var99"}, load_prompt("challenger"),
                                       client=client))
    assert out["error"] is None
    assert out["challenge"] == {"classification": "market_move", "top_driver": "FX_GBPUSD", "confidence": 0.8}
    assert [c["name"] for c in out["tool_calls"]] == ["limit_status", "attribution", "baseline", "data_checks"]
    assert seen[-1]["format"] == C.CHALLENGE_SCHEMA


def test_challenger_rejects_out_of_schema_conclusion(base):
    client, _ = _client([
        _msg(tool_calls=[_tc("limit_status")]),
        _msg(),
        _msg(content=json.dumps({"classification": "maybe", "top_driver": "FX_GBPUSD", "confidence": 0.8})),
    ])
    out = asyncio.run(C.run_challenger(base, {"desk": "DESK_FX", "metric": "var99"}, load_prompt("challenger"),
                                       client=client))
    assert out["challenge"] is None and out["error"]


def test_challenger_without_tool_calls_is_an_error(base):
    client, _ = _client([_msg(content="I think it is a market move.")])
    out = asyncio.run(C.run_challenger(base, {"desk": "DESK_FX", "metric": "var99"}, load_prompt("challenger"),
                                       client=client))
    assert out["challenge"] is None and "no valid tool call" in out["error"]


# --- the graph: the challenger adds escalations, never removes them --------

def _breach(base, kind, i):
    for k in INTENSITIES:
        sc = build_scenario(kind, i, base, random.Random(i), k=k)
        s = to_session(sc, base)
        r = graph.investigate(s, approval_path="scratch/challenger_test_ap.json", challenge=False)
        if r["status"] == "breach":
            return sc, s, r
    raise AssertionError("no breach found for test case")


def _stub(challenge=None, error=None):
    async def fake(session, context, prompt, **kw):
        if error:
            return {"challenge": None, "tool_calls": [], "tokens": 0, "error": error}
        return {"challenge": challenge, "tool_calls": [{"name": "attribution", "args": {}, "ok": True}],
                "tokens": 1, "error": None}
    return fake


def test_challenger_disabled_leaves_no_trace_in_result(base):
    sc, s, r = _breach(base, "single_position_vol", 0)
    assert r["challenge"] is None and r["challenge_agrees"] is None


def test_agreeing_challenger_does_not_change_an_unescalated_case(base, monkeypatch):
    sc, s, primary = _breach(base, "single_position_vol", 0)
    assert primary["escalate"] is False
    agree = {"classification": primary["classification"], "top_driver": primary["top_driver"], "confidence": 0.95}
    monkeypatch.setattr(graph, "run_challenger", _stub(agree))
    r = graph.investigate(s, approval_path="scratch/challenger_test_ap.json", challenge=True)
    assert r["challenge_agrees"] is True
    assert r["escalate"] is False
    assert r["queue"] == "approval"


def test_disagreeing_challenger_escalates_to_human_review(base, monkeypatch):
    sc, s, primary = _breach(base, "single_position_vol", 0)
    other = "data_issue" if primary["classification"] != "data_issue" else "market_move"
    monkeypatch.setattr(graph, "run_challenger", _stub({"classification": other, "top_driver": "EQ_ZZZ",
                                                        "confidence": 0.9}))
    r = graph.investigate(s, approval_path="scratch/challenger_test_ap.json", challenge=True)
    assert r["challenge_agrees"] is False
    assert r["escalate"] is True
    assert r["queue"] == "human_review"
    assert any("classification disagrees" in x for x in r["challenge_reasons"])


def test_failed_challenge_escalates_fail_safe(base, monkeypatch):
    sc, s, primary = _breach(base, "single_position_vol", 0)
    monkeypatch.setattr(graph, "run_challenger", _stub(error="ConnectError: model down"))
    r = graph.investigate(s, approval_path="scratch/challenger_test_ap.json", challenge=True)
    assert r["escalate"] is True
    assert r["queue"] == "human_review"
    assert any("challenge unavailable" in x for x in r["challenge_reasons"])


def test_challenger_cannot_remove_an_escalation(base, monkeypatch):
    sc, s, primary = _breach(base, "limit_error", 3)
    assert primary["escalate"] is True
    agree = {"classification": primary["classification"], "top_driver": primary["top_driver"], "confidence": 0.99}
    monkeypatch.setattr(graph, "run_challenger", _stub(agree))
    r = graph.investigate(s, approval_path="scratch/challenger_test_ap.json", challenge=True)
    assert r["challenge_agrees"] is True
    assert r["escalate"] is True
    assert r["queue"] == "human_review"
