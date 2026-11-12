"""Tests for the function-calling agent, structured notes, citation and content checks, retrieval metrics,
chunking, and the async graph path. The Ollama server is replaced by httpx.MockTransport so these tests run offline."""

import asyncio
import json
import random

import httpx
import pytest

from riskdesk.agents import graph
from riskdesk.agents.drafters import DraftNote, NOTE_SCHEMA, load_prompt, parse_note
from riskdesk.agents.tool_agent import run_tool_agent, validate_call
from riskdesk.config import KB_DIR
from riskdesk.rag.index import chunk_section, chunk_window, evaluate
from riskdesk.tools import Session


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKDESK_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(graph, "TRACE_PATH", str(tmp_path / "traces.jsonl"))


@pytest.fixture(scope="module")
def base():
    return Session.base()


# --- tool-call validation -------------------------------------------------

@pytest.mark.parametrize("name, args", [
    ("delete_everything", {}),                       # unknown tool
    ("compute_var", {"desk": "DESK_XYZ"}),           # desk not in book
    ("compute_var", {"desk": "DESK_EQ", "method": "monte_carlo"}),  # method not allowed here
    ("compute_var", {"desk": "DESK_EQ", "paths": 10**9}),          # unexpected argument
    ("limit_status", {"desk": "DESK_EQ"}),           # takes no arguments
    ("search_policy", {"query": "x" * 201}),         # too long
    ("search_policy", {"query": "   "}),             # empty
])
def test_validate_call_rejects_bad_calls(name, args):
    assert validate_call(name, args) is not None


def test_validate_call_accepts_good_call():
    assert validate_call("compute_var", {"desk": "DESK_FX", "method": "parametric"}) is None
    assert validate_call("limit_status", {}) is None


# --- the agent loop against a scripted model -------------------------------

def _mock_client(responses):
    """responses: list of dicts returned in order for each /api/chat call."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(calls) - 1])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def _msg(content="", tool_calls=None, tokens=3):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"message": m, "eval_count": tokens}


def test_tool_agent_calls_tool_then_returns_schema_valid_note(base):
    prompt = load_prompt()
    client, calls = _mock_client([
        _msg(tool_calls=[{"function": {"name": "compute_var", "arguments": {"desk": "DESK_FX", "method": "historical"}}}]),
        _msg(),  # no further tool calls
        _msg(content=json.dumps({"summary": "Desk DESK_FX breach note, classification market_move."})),
    ])
    ctx = {"desk": "DESK_FX", "metric": "var99", "classification": "market_move"}
    out = asyncio.run(run_tool_agent(base, ctx, prompt, client=client))
    assert out["error"] is None
    assert out["summary"].startswith("Desk DESK_FX")
    assert out["tool_calls"] == [{"name": "compute_var", "args": {"desk": "DESK_FX", "method": "historical"}, "ok": True}]
    assert out["tool_outputs"][0]["desk"] == "DESK_FX"
    # the final call must be constrained to the note schema
    assert calls[-1]["format"] == NOTE_SCHEMA
    # tools were offered on the tool-calling steps
    assert calls[0]["tools"] and "tools" not in calls[-1]


def test_tool_agent_records_rejected_call_and_gives_no_summary(base):
    prompt = load_prompt()
    client, _ = _mock_client([
        _msg(tool_calls=[{"function": {"name": "delete_everything", "arguments": {}}}]),
        _msg(),
    ])
    ctx = {"desk": "DESK_FX", "metric": "var99", "classification": "market_move"}
    out = asyncio.run(run_tool_agent(base, ctx, prompt, client=client))
    assert out["summary"] is None
    assert out["tool_calls"][0]["ok"] is False
    assert out["tool_outputs"] == []  # a rejected call is never executed


def test_tool_agent_rejects_invalid_final_json(base):
    prompt = load_prompt()
    client, _ = _mock_client([
        _msg(tool_calls=[{"function": {"name": "limit_status", "arguments": {}}}]),
        _msg(),
        _msg(content="not json at all"),
    ])
    ctx = {"desk": "DESK_FX", "metric": "var99", "classification": "market_move"}
    out = asyncio.run(run_tool_agent(base, ctx, prompt, client=client))
    assert out["summary"] is None
    assert out["error"] and "ValueError" in out["error"]


def test_tool_agent_failure_is_reported_not_raised(base):
    prompt = load_prompt()

    def handler(request):
        return httpx.Response(500, json={"error": "model unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = {"desk": "DESK_FX", "metric": "var99", "classification": "market_move"}
    out = asyncio.run(run_tool_agent(base, ctx, prompt, client=client))
    assert out["summary"] is None and out["error"]


# --- structured note ------------------------------------------------------

def test_parse_note_accepts_only_schema_conforming_json():
    assert parse_note(json.dumps({"summary": "A note long enough to pass the minimum length check."}))
    with pytest.raises(ValueError):
        parse_note(json.dumps({"text": "wrong key here, long enough to pass length"}))
    with pytest.raises(ValueError):
        parse_note("plain text is not JSON")
    with pytest.raises(ValueError):
        DraftNote(summary="short")


# --- content check and citation control -----------------------------------

def _state(**kw):
    base_state = {"desk": "DESK_FX", "classification": "market_move", "metric": "var99", "citations": [],
                  "tool_outputs": [], "draft_text": "", "confidence": 1.0, "escalate": False,
                  "drafter_used": "template", "draft_attempts": 1}
    return {**base_state, **kw}


def test_content_check_requires_desk_and_classification():
    st = _state()
    assert graph.content_check("Desk DESK_FX breach, classified market move, escalated no.", st)[0] is True
    assert graph.content_check("Some desk had a breach.", st)[0] is False          # no desk named
    assert graph.content_check("DESK_FX breach but no label.", st)[0] is False     # no classification
    assert graph.content_check("Classification already decided: DESK_FX market_move", st)[0] is False  # echo


def test_validate_blocks_policy_id_that_no_tool_returned():
    st = _state(draft_text="Desk DESK_FX market move. See limit_policy#made-up-section for handling.",
                citations=["limit_policy#breach-response"])
    out = graph.validate(st)
    assert out["grounding"]["ok"] is False
    assert any("citation:limit_policy#made-up-section" in u for u in out["grounding"]["unsupported"])


def test_validate_allows_policy_id_returned_by_policy_search():
    st = _state(draft_text="Desk DESK_FX market move. Policy: limit_policy#breach-response applies.",
                citations=[], tool_outputs=[{"policy_hits": [{"id": "limit_policy#breach-response", "heading": "x"}]}])
    assert graph.validate(st)["grounding"]["ok"] is True


# --- retrieval metrics and chunking ---------------------------------------

class _Stub:
    def __init__(self, ranking):
        self.ranking = ranking

    def search(self, query, k=10):
        return [{"id": sid} for sid in self.ranking[query]][:k]


def test_retrieval_metrics_on_known_ranks():
    idx = _Stub({"q1": ["a", "b", "c"], "q2": ["x", "gold", "y"], "q3": ["m", "n", "o"]})
    qs = [{"q": "q1", "chunk": "a"},          # rank 1
          {"q": "q2", "chunk": "gold"},       # rank 2
          {"q": "q3", "chunk": "missing"}]    # not retrieved
    r = evaluate(idx, qs, k=5)
    assert r["recall@5"] == pytest.approx(2 / 3)
    assert r["mrr@10"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert r["ndcg@10"] == pytest.approx((1 + 1 / 1.5849625007211562 + 0) / 3)  # 1/log2(3) for rank 2
    assert len(r["misses"]) == 1


def test_window_chunks_map_back_to_sections_and_ids_are_unique():
    sections = {c.section_id for c in chunk_section(KB_DIR)}
    windows = chunk_window(KB_DIR, 60, 20)
    assert windows and all(w.section_id in sections for w in windows)
    assert len({w.id for w in windows}) == len(windows)


# --- async graph path -----------------------------------------------------

def test_investigate_async_runs_a_breach_case(base):
    from evals.golden import build_scenario, to_session
    sc = build_scenario("limit_error", 3, base, random.Random(3), k=1.0)
    res = asyncio.run(graph.investigate_async(to_session(sc, base), drafter_kind="template",
                                              approval_path="scratch/async_test_ap.json"))
    assert res["status"] == "breach"
    assert res["classification"] == "limit_error"
    assert res["paused"] is True
