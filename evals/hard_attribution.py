"""Harder root-cause test: the injected shock hits the SECOND-largest exposure on the desk.

The golden set always shocks the largest exposure, which is an easy case. Here the largest pre-existing
exposure is left alone, so a correct answer requires the agent to attribute the breach to the shocked
underlying, not to the distractor. Kept separate from the golden set so that set stays stable.

Run:  python evals/hard_attribution.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("RISKDESK_AUDIT_PATH", os.path.join(ROOT, "data", "audit", "eval_audit.jsonl"))

from evals.golden import INTENSITIES  # noqa: E402
from evals.run_eval import EVAL_APPROVALS  # noqa: E402
from riskdesk.agents.graph import investigate  # noqa: E402
from riskdesk.engine.book import positions_by_desk  # noqa: E402
from riskdesk.engine.limits import check_limits  # noqa: E402
from riskdesk.engine.market import apply_regime_shock  # noqa: E402
from riskdesk.engine.risk import component_var_by_underlying  # noqa: E402
from riskdesk.tools import Session  # noqa: E402

RESULTS = os.path.join(ROOT, "evals", "results", "hard_attribution.json")


def ranked_exposures(base: Session, desk: str) -> list[str]:
    comp = component_var_by_underlying(positions_by_desk(base.book, desk), base.market)
    names = set(base.market.vol_names) | set(base.market.rf)
    return [u for u in comp if u in names and comp[u] > 0]


def make(base: Session, desk: str, u2: str, k: float) -> Session:
    if u2 in base.market.rf:
        m = apply_regime_shock(base.market, [u2], last_n=20, mult=1 + 4.0 * k)
    else:
        m = apply_regime_shock(base.market, [u2], last_n=20, mult=1 + 3.0 * k, vol_jump_pts=15.0 * k)
    return Session(market=m, book=base.book, limits=base.limits)


def breaches_desk(s: Session, desk: str) -> bool:
    rows = check_limits(s.book, s.market, s.limits)
    return any(r["desk"] == desk and r["status"] == "BREACH" for r in rows)


def main() -> None:
    base = Session.base()
    cases = []
    for desk in ["DESK_EQ", "DESK_VOL", "DESK_FX"]:
        exp = ranked_exposures(base, desk)
        if len(exp) < 2:
            continue
        for u2 in exp[1:]:  # every non-largest exposure; the largest stays unshocked
            for k in INTENSITIES:
                s = make(base, desk, u2, k)
                if breaches_desk(s, desk):
                    cases.append({"desk": desk, "target": u2, "distractor": exp[0], "k": k, "session": s})
                    break
    rows = []
    for c in cases:
        res = investigate(c["session"], approval_path=EVAL_APPROVALS)
        rows.append({"desk": c["desk"], "target": c["target"], "distractor": c["distractor"],
                     "intensity": c["k"], "status": res["status"], "predicted_desk": res["desk"],
                     "top_driver": res["top_driver"], "top_is_intended": res["desk"] == c["desk"],
                     "root_cause_correct": res["desk"] == c["desk"] and res["top_driver"] == c["target"],
                     "root_cause_is_distractor": res["desk"] == c["desk"] and res["top_driver"] == c["distractor"]})
    n = len(rows)
    summary = {
        "n_cases": n,
        "breach_on_target_desk": sum(r["top_is_intended"] or r["predicted_desk"] == r["desk"] for r in rows) / n if n else None,
        "root_cause_accuracy": sum(r["root_cause_correct"] for r in rows) / n if n else None,
        "picked_distractor": sum(r["root_cause_is_distractor"] for r in rows) / n if n else None,
    }
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2, default=str)
    print(json.dumps(summary, indent=2))
    for r in rows:
        print(r["desk"], r["target"], "vs distractor", r["distractor"], "->", r["top_driver"], "correct" if r["root_cause_correct"] else "WRONG")


if __name__ == "__main__":
    main()
