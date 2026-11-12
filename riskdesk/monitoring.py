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


if __name__ == "__main__":
    print(write_report())
