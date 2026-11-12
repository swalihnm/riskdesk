"""End-to-end tests of the investigation graph on one scenario of each kind, with files redirected to tmp."""

import random

import pytest

from evals.golden import build_scenario, to_session
from riskdesk.agents import graph
from riskdesk.engine.book import build_book  # noqa: F401  (ensures engine imports resolve)
from riskdesk.tools import Session


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKDESK_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(graph, "TRACE_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setenv("RISKDESK_DRAFTER", "template")
    return tmp_path


@pytest.fixture(scope="module")
def base():
    return Session.base()


def _run(base, kind, i, approval_path, k=None):
    """Steps the injection size up until the scenario breaches, as the golden-set generator does."""
    from evals.golden import INTENSITIES
    ks = [k] if k is not None else INTENSITIES
    res = sc = None
    for kk in ks:
        rng = random.Random(i)
        sc = build_scenario(kind, i, base, rng, k=kk)
        res = graph.investigate(to_session(sc, base), approval_path=approval_path)
        if kind == "limit_error" or res["status"] == "breach":
            break
    return sc, res


def test_no_breach_on_base_book_ends_without_queue(base, tmp_path):
    res = graph.investigate(base, approval_path=str(tmp_path / "ap.json"))
    assert res["status"] == "no_breach"
    assert res["paused"] is False
    assert [t["node"] for t in res["trace"]] == ["triage"]


def test_limit_error_is_classified_and_proposal_queued(base, tmp_path):
    ap = str(tmp_path / "ap.json")
    sc, res = _run(base, "limit_error", 3, ap)
    assert res["classification"] == "limit_error"
    assert res["escalate"] is True
    assert res["paused"] is True and res["queue"] == "human_review"
    import json
    kinds = [i["kind"] for i in json.load(open(ap))]
    assert "limit_change_proposal" in kinds
    proposal = [i for i in json.load(open(ap)) if i["kind"] == "limit_change_proposal"][0]
    assert proposal["status"] == "pending"
    assert proposal["payload"]["applied"] is False


def test_data_quality_is_called_a_data_issue_not_a_market_move(base, tmp_path):
    sc, res = _run(base, "data_quality", 2, str(tmp_path / "ap.json"))
    if res["status"] != "breach":
        pytest.skip("injection did not breach at this size")
    assert res["classification"] == "data_issue"
    assert res["escalate"] is True


def test_market_move_reaches_approval_queue_with_grounded_report(base, tmp_path):
    sc, res = _run(base, "single_position_vol", 0, str(tmp_path / "ap.json"), k=4.0)
    if res["status"] != "breach":
        pytest.skip("injection did not breach at this size")
    assert res["classification"] == "market_move"
    assert res["report"] is not None
    assert res["grounding"]["ok"] is True
    assert res["queue"] == "approval"


def test_approval_resume_records_named_reviewer(base, tmp_path):
    ap = str(tmp_path / "ap.json")
    sc, res = _run(base, "single_position_vol", 0, ap, k=4.0)
    if res["status"] != "breach":
        pytest.skip("injection did not breach at this size")
    graph.resume(res["run_id"], "Head of Market Risk", True, "reviewed")
    import json
    item = [i for i in json.load(open(ap)) if i["id"] == res["approval_id"]][0]
    assert item["status"] == "approved"
    assert item["decided_by"] == "Head of Market Risk"


def test_trace_records_prompt_version_and_latency(base, tmp_path):
    sc, res = _run(base, "limit_error", 3, str(tmp_path / "ap.json"))
    assert all("prompt_version" in t and "latency_ms" in t for t in res["trace"])
