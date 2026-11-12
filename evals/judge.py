"""Citation-support judge and its agreement check.

What is judged: each row pairs a claim ("this case should be handled under the cited policy section")
with a passage. Two kinds of row:
  positive          the passage is the section the agent actually cited for that case
  negative_control  the passage is a section for a DIFFERENT case type, swapped in on purpose;
                    these should be NOT_SUPPORTED. Without them there are no negatives to measure against.

The judge (rule-based, see JUDGE_KEYWORDS): SUPPORTED if the passage contains a keyword for the
classification. It is transparent and deterministic. It is not an LLM. prompts/judge.yaml holds the
rubric for a future LLM judge, which must be validated before use.

Workflow:
  python evals/judge.py --export    sample breached cases; write evals/judge_labels.csv
  python evals/judge.py --kappa     Cohen's kappa between the judge and the reviewer labels

Each row records who labelled it in the `reviewer` column. A human label and an AI reviewer's label
measure different things; report them separately.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
LABELS = os.path.join(ROOT, "evals", "judge_labels.csv")
VALID = {"SUPPORTED", "NOT_SUPPORTED"}
PASSAGE_CHARS = 700
N_REAL = 50
N_NEGATIVE = 25

JUDGE_KEYWORDS = {
    "market_move": ["breach", "escalat", "desk head", "utilisation", "limit"],
    "data_issue": ["data", "price", "jump", "stale", "owner"],
    "limit_error": ["limit", "calibrat", "baseline", "approv"],
}
# A different-type policy section to swap in for each classification (negative controls)
NEGATIVE_SWAP = {
    "market_move": "limit_policy#limit-calibration",
    "limit_error": "escalation_matrix#data-incidents",
    "data_issue": "limit_policy#breach-response",
}
CLAIM = "This {cls} case should be handled under the cited policy section."
FIELDS = ["id", "kind", "classification", "row_type", "claim", "citation_id", "passage",
          "judge_label", "automated_label", "automated_reviewer", "human_label", "human_reviewer"]


def judge(classification: str, passage: str) -> str:
    text = passage.lower()
    hit = any(k in text for k in JUDGE_KEYWORDS.get(classification, []))
    return "SUPPORTED" if hit else "NOT_SUPPORTED"


def cohens_kappa(a: list[str], b: list[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("label lists must be non-empty and the same length")
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe == 1:
        # Both label sets use a single category: kappa is undefined, not perfect.
        raise ValueError("kappa undefined: both label sets use a single category")
    return (po - pe) / (1 - pe)


def _row(sc: dict, cls: str, row_type: str, cid: str, chunks: dict) -> dict:
    passage = chunks.get(cid, "")[:PASSAGE_CHARS].replace("\n", " ")
    suffix = "-neg" if row_type == "negative_control" else ""
    return {"id": sc["id"] + suffix, "kind": sc["kind"], "classification": cls, "row_type": row_type,
            "claim": CLAIM.format(cls=cls.replace("_", " ")), "citation_id": cid,
            "passage": passage, "judge_label": judge(cls, passage),
            "automated_label": "", "automated_reviewer": "", "human_label": "", "human_reviewer": ""}


def export(seed: int = 5) -> None:
    import time
    from evals.golden import generate, to_session
    from riskdesk.agents.graph import investigate
    # Own queue file: sharing data/eval/approvals.json with a concurrent eval run corrupts it.
    queue = os.path.join(ROOT, "scratch", f"judge_approvals_{int(time.time())}.json")
    from riskdesk.config import KB_DIR
    from riskdesk.rag.index import load_chunks
    from riskdesk.tools import Session

    chunks = {c.id: c.text for c in load_chunks(KB_DIR)}
    base = Session.base()
    cases = []
    for sc in generate():
        res = investigate(to_session(sc, base), approval_path=queue)
        cits = (res["report"] or {}).get("citations", [])
        if res["status"] == "breach" and res["desk"] == sc["breach_desk"] and cits:
            cases.append((sc, res["classification"], cits))
    rng = random.Random(seed)
    sample = rng.sample(cases, min(N_REAL, len(cases)))
    negatives = rng.sample(sample, min(N_NEGATIVE, len(sample)))
    rows = [_row(sc, cls, "positive", cits[0], chunks) for sc, cls, cits in sample]
    rows += [_row(sc, cls, "negative_control", NEGATIVE_SWAP[cls], chunks) for sc, cls, _ in negatives]
    os.makedirs(os.path.dirname(LABELS), exist_ok=True)
    with open(LABELS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"exported {len(sample)} positive rows and {len(negatives)} negative controls to {LABELS}")


def kappa() -> None:
    """Agreement of the rule judge with (a) the automated reviewer and (b) human reviewers, where present.

    Human agreement is the one that counts for a claim about the judge. The automated reviewer is reported
    separately so the two are never confused.
    """
    rows = list(csv.DictReader(open(LABELS, encoding="utf-8")))
    total = len(rows)
    for name, col in (("automated reviewer", "automated_label"), ("human reviewer", "human_label")):
        labelled = [r for r in rows if r[col] in VALID and r["judge_label"] in VALID]
        if not labelled:
            print(f"{name}: no labels yet (0 of {total}); kappa not reported.")
            continue
        if len(labelled) < total:
            print(f"{name}: {len(labelled)} of {total} rows labelled; kappa not reported until all are.")
            continue
        who = sorted({r[col.replace("_label", "_reviewer")] for r in rows})
        try:
            k = cohens_kappa([r[col] for r in labelled], [r["judge_label"] for r in labelled])
        except ValueError as e:
            print(f"{name}: {e} (over {len(labelled)} cases)")
            continue
        print(f"Cohen's kappa, judge vs {name} over {len(labelled)} cases ({', '.join(who)}): {k:.3f}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--kappa", action="store_true")
    a = ap.parse_args()
    if a.export:
        export()
    if a.kappa:
        kappa()
