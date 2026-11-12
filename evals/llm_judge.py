"""LLM judge for citation support, run over evals/judge_labels.csv.

Advisory only. The judge's labels are compared with the automated reviewer's labels and, once they exist,
with human labels. No accuracy claim is made until the human comparison exists.

Usage:  python evals/llm_judge.py            (uses the local model in RISKDESK_OLLAMA_MODEL)
Writes: evals/results/llm_judge_<model>.json
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time

import httpx

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from evals.judge import LABELS, cohens_kappa  # noqa: E402
from riskdesk.agents.drafters import load_prompt  # noqa: E402
from riskdesk.config import OLLAMA_MODEL, OLLAMA_URL  # noqa: E402

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["SUPPORTED", "NOT_SUPPORTED"]},
        "reason": {"type": "string", "maxLength": 240},
    },
    "required": ["label", "reason"],
}


def judge_row(client: httpx.Client, prompt: dict, claim: str, passage: str, model: str) -> dict:
    body = {
        "model": model, "stream": False, "format": JUDGE_SCHEMA, "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["template"].format(claim=claim, passage=passage)},
        ],
    }
    r = client.post(f"{OLLAMA_URL}/api/chat", json=body)
    r.raise_for_status()
    out = r.json()
    parsed = json.loads(out["message"]["content"])
    return {"label": parsed["label"], "reason": parsed["reason"], "tokens": out.get("eval_count", 0)}


def main() -> None:
    model = OLLAMA_MODEL
    prompt = load_prompt("judge")
    rows = list(csv.DictReader(open(LABELS, encoding="utf-8")))
    results = []
    t0 = time.time()
    with httpx.Client(timeout=300) as client:
        for r in rows:
            try:
                j = judge_row(client, prompt, r["claim"], r["passage"], model)
                err = None
            except Exception as e:  # record the failure; it is not a silent label
                j, err = {"label": None, "reason": None, "tokens": 0}, f"{type(e).__name__}: {str(e)[:150]}"
            results.append({"id": r["id"], "row_type": r["row_type"], "llm_label": j["label"],
                            "llm_reason": j["reason"], "error": err, "automated_label": r["automated_label"],
                            "judge_label": r["judge_label"], "human_label": r["human_label"]})
    ok = [x for x in results if x["llm_label"] in ("SUPPORTED", "NOT_SUPPORTED")]
    summary = {"model": model, "prompt_version": prompt["version"], "rows": len(results), "answered": len(ok),
               "errors": len(results) - len(ok), "seconds": round(time.time() - t0, 1)}
    if ok:
        summary["agreement_with_automated_reviewer"] = sum(
            x["llm_label"] == x["automated_label"] for x in ok) / len(ok)
        try:
            summary["kappa_vs_automated_reviewer"] = cohens_kappa(
                [x["llm_label"] for x in ok], [x["automated_label"] for x in ok])
        except ValueError as e:
            summary["kappa_vs_automated_reviewer"] = str(e)
        labelled_human = [x for x in ok if x["human_label"] in ("SUPPORTED", "NOT_SUPPORTED")]
        summary["human_labelled_rows"] = len(labelled_human)
        if labelled_human:
            try:
                summary["kappa_vs_human"] = cohens_kappa([x["llm_label"] for x in labelled_human],
                                                         [x["human_label"] for x in labelled_human])
            except ValueError as e:
                summary["kappa_vs_human"] = str(e)
        else:
            summary["kappa_vs_human"] = "not computed: no human labels yet"
    out = os.path.join(ROOT, "evals", "results", f"llm_judge_{model.replace(':', '-').replace('.', '-')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": results}, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
