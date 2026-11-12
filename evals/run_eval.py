"""Run the golden set through the investigation graph and score it.

Usage:
  python evals/run_eval.py                  # template drafter (deterministic)
  RISKDESK_DRAFTER=ollama python evals/run_eval.py
  python evals/run_eval.py --limit 12       # quick run on the first 12 scenarios

Writes evals/results/latest.json and appends one line to evals/results/history.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("RISKDESK_AUDIT_PATH", os.path.join(ROOT, "data", "audit", "eval_audit.jsonl"))

from evals.golden import generate, to_session  # noqa: E402
from riskdesk.agents.drafters import load_prompt  # noqa: E402
import asyncio  # noqa: E402

from riskdesk.agents.graph import investigate_async  # noqa: E402
from riskdesk.tools import Session  # noqa: E402

RESULTS_DIR = os.path.join(ROOT, "evals", "results")
EVAL_APPROVALS = os.path.join(ROOT, "data", "eval", "approvals.json")


def score(sc: dict, res: dict) -> dict:
    # The intended desk must breach. For multi-breach cases the agent investigates the top-ranked breach,
    # so the root-cause and label checks apply only when the intended desk is the top-ranked one.
    intended_breached = any(b["desk"] == sc["breach_desk"] for b in res.get("all_breaches", []))
    top_is_intended = res["status"] == "breach" and res["desk"] == sc["breach_desk"]
    breach_found = intended_breached
    report = res.get("report") or {}
    row = {
        "id": sc["id"], "kind": sc["kind"], "expected_label": sc["expected_label"],
        "expected_driver": sc["expected_driver"], "expected_escalate": sc["expected_escalate"],
        "breach_found": breach_found, "top_is_intended": top_is_intended,
        "predicted_desk": res["desk"], "utilisation": res["utilisation"],
        "predicted_label": res["classification"], "predicted_driver": res["top_driver"],
        "escalated": res["escalate"], "queue": res["queue"], "drafter": res["drafter"] or "none",
        "tool_calls": len(res.get("tool_calls") or []), "fallback_reason": res.get("draft_fallback_reason"),
        "challenge_agrees": res.get("challenge_agrees"), "challenge_reasons": res.get("challenge_reasons") or [],
        "intensity": sc.get("intensity"), "injection_not_breaching": bool(sc.get("injection_not_breaching")),
        "report_valid": res["report"] is not None,
        "completed": bool(res["paused"] and res["report"] is not None and breach_found),
        "label_correct": res["classification"] == sc["expected_label"],
        "escalation_correct": bool(res["escalate"]) == sc["expected_escalate"],
        "root_cause_applicable": sc["expected_driver"] is not None,
        "root_cause_correct": sc["expected_driver"] is not None and res["top_driver"] == sc["expected_driver"],
        "numbers_drafted": (res.get("grounding") or {}).get("numbers", 0),
        "numbers_unsupported": len((res.get("grounding") or {}).get("unsupported", [])),
        "latency_ms": sum(t["latency_ms"] for t in res["trace"]),
        "prompt_version": report.get("prompt_version", load_prompt()["version"]),
    }
    return row


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    breached = [r for r in rows if r["breach_found"]]           # intended desk breached (any rank)
    ranked_first = [r for r in rows if r["top_is_intended"]]      # intended desk is the investigated breach
    rc = [r for r in ranked_first if r["root_cause_applicable"]]
    drafted = sum(r["numbers_drafted"] for r in rows)
    unsupported = sum(r["numbers_unsupported"] for r in rows)
    shipped_unsupported = sum(r["numbers_unsupported"] for r in rows if r["completed"])
    by_kind = {}
    for k in sorted({r["kind"] for r in rows}):
        kr = [r for r in rows if r["kind"] == k]
        by_kind[k] = {"n": len(kr), "breach_found": sum(r["breach_found"] for r in kr),
                      "label_correct": sum(r["label_correct"] for r in kr),
                      "escalation_correct": sum(r["escalation_correct"] for r in kr)}
    lat = sorted(r["latency_ms"] for r in rows)
    return {
        "n_scenarios": n,
        "injection_breach_rate": len(breached) / n,
        "root_cause_accuracy": (sum(r["root_cause_correct"] for r in rc) / len(rc)) if rc else None,
        "root_cause_n": len(rc),
        "top_ranked_rate": len(ranked_first) / n,
        "classification_accuracy": (sum(r["label_correct"] for r in ranked_first) / len(ranked_first)
                                    if ranked_first else None),
        "escalation_correctness": (sum(r["escalation_correct"] for r in ranked_first) / len(ranked_first)
                                   if ranked_first else None),
        "task_completion": sum(r["completed"] for r in breached) / len(breached) if breached else None,
        "numeric_hallucination_rate_drafted": unsupported / drafted if drafted else 0.0,
        "unsupported_numbers_shipped": shipped_unsupported,
        "latency_ms_p50": lat[len(lat) // 2] if lat else None,
        "by_kind": by_kind,
        "drafters": dict(Counter(r["drafter"] for r in rows)),
        "tool_call_rate": sum(1 for r in rows if r["tool_calls"] > 0) / n,
        "fallback_rate": sum(1 for r in rows if r["drafter"] == "template_fallback") / n,
        "content_check_failures": sum(1 for r in rows if (r["fallback_reason"] or "").startswith("content_check")),
        "challenger_run": sum(1 for r in rows if r["challenge_agrees"] is not None),
        "challenger_disagreements": sum(1 for r in rows if r["challenge_agrees"] is False),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=1,
                    help="scenarios in flight at once (the local model still runs one request at a time)")
    args = ap.parse_args()

    base = Session.base()
    scenarios = generate()
    if args.limit:
        scenarios = scenarios[: args.limit]
    os.makedirs(os.path.dirname(EVAL_APPROVALS), exist_ok=True)
    if os.path.exists(EVAL_APPROVALS):
        os.replace(EVAL_APPROVALS, EVAL_APPROVALS + f".{int(time.time())}.bak")
    t0 = time.time()

    async def run_all() -> list[dict]:
        sem = asyncio.Semaphore(args.concurrency)

        async def one(sc: dict) -> dict:
            async with sem:
                res = await investigate_async(to_session(sc, base), approval_path=EVAL_APPROVALS)
                return score(sc, res)

        return await asyncio.gather(*(one(sc) for sc in scenarios))

    rows = asyncio.run(run_all())
    summary = summarise(rows)
    summary["wall_seconds"] = round(time.time() - t0, 1)
    prompt = load_prompt()
    run = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt": {"name": prompt["name"], "version": prompt["version"]},
        "drafter_env": os.environ.get("RISKDESK_DRAFTER", "template"),
        "data_source": "synthetic" if os.environ.get("RISKDESK_DATA", "real").lower() == "synthetic" else "real",
        "model": os.environ.get("RISKDESK_OLLAMA_MODEL", "qwen2.5:0.5b") if os.environ.get("RISKDESK_DRAFTER") in ("ollama", "tools") else None,
        "summary": summary,
        "rows": rows,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    model_tag = os.environ.get("RISKDESK_OLLAMA_MODEL", "qwen2.5:0.5b").replace(":", "-")
    challenger_tag = ""
    if os.environ.get("RISKDESK_CHALLENGER", "off").lower() in ("on", "1", "true"):
        challenger_tag = "_challenger-p" + load_prompt("challenger")["version"]
    data_tag = "" if run["data_source"] == "real" else "_synthetic"
    tag = run["drafter_env"] + ("" if run["drafter_env"] == "template" else "_" + model_tag) + challenger_tag + data_tag + ("" if not args.limit else f"_first{args.limit}")
    with open(os.path.join(RESULTS_DIR, f"latest_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2, default=str)
    if not args.limit:
        with open(os.path.join(RESULTS_DIR, "history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({k: run[k] for k in ("run_at", "prompt", "drafter_env", "data_source", "summary")},
                               default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
