"""MCP server and commentary workflow tests."""

import os

import pytest

from riskdesk import audit
from riskdesk.agents.commentary import daily_commentary
from riskdesk.mcp import server
from riskdesk.tools import Session


@pytest.fixture(scope="module")
def base():
    return Session.base()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKDESK_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    return tmp_path


def test_mcp_server_registers_expected_tools():
    names = set(server.mcp._tool_manager._tools.keys())
    expected = {"list_desks", "limit_status", "compute_var", "compute_es", "attribution",
                "stress_test", "data_checks", "backtest", "search_policy"}
    assert expected <= names


def test_mcp_compute_var_matches_engine_and_is_audited(base, tmp_path):
    server.set_session(base)
    out = server.compute_var("DESK_EQ", "historical")
    assert out["var99_1d"] > 0
    ok, n = audit.verify(str(tmp_path / "audit.jsonl"))
    assert ok and n >= 1


def test_mcp_rejects_unknown_method(base):
    server.set_session(base)
    with pytest.raises(ValueError):
        server.compute_var("DESK_EQ", "bogus")


def test_mcp_policy_search_returns_citations(base):
    server.set_session(base)
    hits = server.search_policy("breach response", 3)
    assert len(hits) == 3 and all("id" in h for h in hits)


def test_commentary_is_queued_for_approval_and_never_blocked_on_base_book(base, tmp_path):
    ap = str(tmp_path / "ap.json")
    out = daily_commentary(base, approval_path=ap)
    assert len(out) == 3
    assert all(r["status"] == "queued" for r in out)
    import json
    items = json.load(open(ap, encoding="utf-8"))
    assert all(i["kind"] == "daily_commentary" and i["status"] == "pending" for i in items)
