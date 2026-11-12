"""Monitoring: cost, latency, failure types and eval drift from the trace and eval history files.

Writes docs/mrm/eval_history.md (a table) and docs/mrm/eval_drift.png (a chart once there are two or more runs).
A weekly chart needs a weekly scheduled run of evals/run_eval.py; a single run only produces the table.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

from riskdesk.config import TRACE_PATH

ROOT = os.path.join(os.path.dirname(__file__), "..")
HISTORY = os.path.join(ROOT, "evals", "results", "history.jsonl")
MRM_DIR = os.path.join(ROOT, "docs", "mrm")


def trace_summary(path: str = TRACE_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    by_node = defaultdict(lambda: {"n": 0, "latency_ms_total": 0.0, "tokens": 0})
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            t = json.loads(line)
            d = by_node[t["node"]]
            d["n"] += 1
            d["latency_ms_total"] += t.get("latency_ms", 0.0)
            d["tokens"] += int(t.get("tokens", 0) or 0)
    return {k: {**v, "latency_ms_mean": v["latency_ms_total"] / v["n"]} for k, v in by_node.items()}


def history() -> list[dict]:
    if not os.path.exists(HISTORY):
        return []
    return [json.loads(l) for l in open(HISTORY, encoding="utf-8") if l.strip()]


def write_report() -> str:
    os.makedirs(MRM_DIR, exist_ok=True)
    runs = history()
    lines = ["# Eval history", "", "| Run | Prompt | Drafter | Breach rate | Root cause | Completion | Unsupported shipped |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        s = r["summary"]
        lines.append(f"| {r['run_at']} | {r['prompt']['version']} | {r['drafter_env']} | "
                     f"{s['injection_breach_rate']:.0%} | {_pct(s['root_cause_accuracy'])} | "
                     f"{_pct(s['task_completion'])} | {s['unsupported_numbers_shipped']} |")
    if not runs:
        lines.append("| (no runs yet) | | | | | | |")
    lines += ["", "## Node latency (trace file)", "", "| Node | Calls | Mean latency (ms) | Tokens |", "| --- | --- | --- | --- |"]
    for node, d in sorted(trace_summary().items()):
        lines.append(f"| {node} | {d['n']} | {d['latency_ms_mean']:.1f} | {d['tokens']} |")
    path = os.path.join(MRM_DIR, "eval_history.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if len(runs) >= 2:
        _chart(runs)
    return path


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _chart(runs: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = list(range(len(runs)))
    fig, ax = plt.subplots(figsize=(7, 3.5))
    for key, label in [("root_cause_accuracy", "Root-cause accuracy"), ("task_completion", "Task completion"),
                       ("injection_breach_rate", "Breach rate")]:
        ax.plot(x, [r["summary"][key] or 0 for r in runs], marker="o", label=label)
    ax.set_xticks(x, [r["run_at"][:10] for r in runs], rotation=30)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("score")
    ax.legend(fontsize=8)
    ax.set_title("Golden-set eval over time")
    fig.tight_layout()
    fig.savefig(os.path.join(MRM_DIR, "eval_drift.png"), dpi=120)
    plt.close(fig)




def run_health(path: str = TRACE_PATH) -> dict:
    """Health of the investigations recorded in the trace file, grouped by run.

    Reports: how many runs, which drafter produced each note, why drafts fell back, how often the challenger
    disagreed, how often a note failed the grounding check, token use, and run-time percentiles.
    """
    from collections import Counter

    if not os.path.exists(path):
        return {"runs": 0}
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    if not records:
        return {"runs": 0}
    runs = defaultdict(float)
    drafters, reasons, prompts = Counter(), Counter(), Counter()
    challenges = disagreements = grounding_fail = tokens = 0
    for r in records:
        runs[r.get("run_id")] += float(r.get("latency_ms", 0.0) or 0.0)
        tokens += int(r.get("tokens", 0) or 0)
        if r.get("prompt_version"):
            prompts[r["prompt_version"]] += 1
        if r["node"] == "draft_report":
            drafters[r.get("drafter") or "none"] += 1
            if r.get("fallback_reason"):
                reasons[str(r["fallback_reason"]).split(":")[0]] += 1
        if r["node"] == "challenge":
            challenges += 1
            if r.get("agrees") is False:
                disagreements += 1
        if r["node"] == "validate" and r.get("grounding_ok") is False:
            grounding_fail += 1
    totals = sorted(runs.values())

    def pct(p: float) -> float:
        return totals[min(int(p * len(totals)), len(totals) - 1)]

    return {
        "runs": len(runs),
        "drafters": dict(drafters),
        "fallback_reasons": dict(reasons),
        "prompt_versions": dict(prompts),
        "challenges": challenges,
        "challenger_disagreements": disagreements,
        "grounding_failures": grounding_fail,
        "tokens_total": tokens,
        "tokens_per_run": tokens / len(runs),
        "run_latency_ms_p50": pct(0.50),
        "run_latency_ms_p95": pct(0.95),
    }


def eval_series() -> list[dict]:
    """One row per full eval run, for the drift chart."""
    out = []
    for r in history():
        s = r["summary"]
        out.append({"run_at": r["run_at"], "drafter": r.get("drafter_env"), "prompt": r["prompt"]["version"],
                    "breach_rate": s["injection_breach_rate"], "root_cause": s["root_cause_accuracy"],
                    "completion": s["task_completion"], "unsupported_shipped": s["unsupported_numbers_shipped"]})
    return out


if __name__ == "__main__":
    print(write_report())
