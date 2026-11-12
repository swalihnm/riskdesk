"""Build all synthetic data: market cache, calibrated limits, incident logs and the RAG question set.

Run:  python scripts/build_data.py
"""

from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from riskdesk.config import CACHE_PATH, GOLDEN_PATH, KB_DIR, LIMITS_PATH, RAG_QUESTIONS_PATH  # noqa: E402
from riskdesk.engine.book import DESKS, build_book  # noqa: E402
from riskdesk.engine.limits import calibrate_limits, save_limits  # noqa: E402
from riskdesk.engine.market import load_market  # noqa: E402

INCIDENT_TYPES = [
    ("Stale FX fixing used for DESK_FX revaluation", "Fixing was 2 days old; jump check flagged; repriced after data owner correction."),
    ("Bad equity tick on cash position", "Vendor tick 30% above market; breach was provisional until correction."),
    ("Limit typo in configuration", "Hard limit entered with a missing zero; caught by second-line review before any action."),
    ("Late breach notification to desk head", "Breach reached desk head next day; procedure reminder issued."),
    ("Vol surface gap on single name", "Implied vol missing for one expiry; interpolated and flagged for review."),
    ("Duplicate trade booked twice", "Position doubled in book feed; reconciled and removed."),
    ("Stress scenario not refreshed", "Historical windows were 60 days old; refresh added to daily job."),
    ("Agent draft cited wrong policy section", "Citation precision issue; retrieval returned adjacent section; prompt tightened."),
]


def main() -> None:
    market = load_market(CACHE_PATH)
    book = build_book(market)
    limits = calibrate_limits(book, market)
    save_limits(limits, LIMITS_PATH)
    print("limits written:", LIMITS_PATH)
    for d in DESKS:
        print(" ", d, limits[d]["limits"])

    rng = random.Random(3)
    lines = ["# Incident logs (synthetic, for demonstration)", ""]
    for n in range(1, 51):
        title, body = INCIDENT_TYPES[(n - 1) % len(INCIDENT_TYPES)]
        desk = rng.choice(DESKS)
        day = rng.randint(1, 28)
        lines += [f"## INC-{n:04d} {title}", f"Desk: {desk}. Date: 2026-{rng.randint(1, 10):02d}-{day:02d}. "
                  f"Summary: {body} Owner: Market Risk operations. Status: closed.", ""]
    with open(os.path.join(KB_DIR, "incident_logs.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("incident logs written: 50")

    questions = [
        ("What hard limits does each desk carry?", "limit_policy", "Hard limits and warning levels"),
        ("At what utilisation does a warning appear?", "limit_policy", "Hard limits and warning levels"),
        ("What must happen the same day a desk breaches?", "limit_policy", "Breach response"),
        ("How is a spike in price tested before calling it a market move?", "limit_policy", "Data quality before market conclusions"),
        ("What threshold makes a hard limit a calibration error?", "limit_policy", "Limit calibration"),
        ("Who approves a change to a limit?", "limit_policy", "Limit calibration"),
        ("How is the stress limit applied?", "limit_policy", "Stress limit"),
        ("What does the vega limit measure?", "limit_policy", "Vega limit"),
        ("Does changing a VaR window count as a model change?", "limit_policy", "Model and methodology changes"),
        ("Who gets an agent case when the top two drivers are close?", "escalation_matrix", "Human review queue for agent cases"),
        ("When should a breach go to the Head of Market Risk?", "escalation_matrix", "Level 3: Head of Market Risk"),
        ("How quickly must a failed price check reach the data owner?", "escalation_matrix", "Data incidents"),
        ("What is the escalation step for a same-day breach?", "escalation_matrix", "Level 2: Market Risk manager"),
        ("How long are escalation records kept?", "escalation_matrix", "Documentation"),
        ("What does desk head notification require for a warning?", "escalation_matrix", "Level 1: desk head"),
        ("Why does Expected Shortfall matter beyond VaR?", "market_risk_reference", "Expected Shortfall"),
        ("What does historical simulation use to reprice the portfolio?", "market_risk_reference", "Historical simulation"),
        ("Why can delta-normal VaR understate option book risk?", "market_risk_reference", "Parametric (delta-normal) VaR"),
        ("How are Monte Carlo shocks made correlated?", "market_risk_reference", "Monte Carlo VaR"),
        ("How do component VaR contributions add up?", "market_risk_reference", "Component and marginal VaR"),
        ("Which Greek measures the sensitivity to implied volatility?", "market_risk_reference", "Greeks"),
        ("What does a stress test answer that VaR does not?", "market_risk_reference", "Stress testing"),
        ("How many exceptions put a 250-day 99% backtest in the amber zone?", "market_risk_reference", "VaR backtesting"),
        ("What distribution does the Kupiec statistic follow?", "market_risk_reference", "Kupiec proportion-of-failures test"),
        ("When did PRA SS1/23 take effect?", "regulatory_summaries", "PRA SS1/23 overview"),
        ("How many principles does SS1/23 set out?", "regulatory_summaries", "PRA SS1/23 principles"),
        ("What should a model inventory record for each model?", "regulatory_summaries", "PRA SS1/23 model inventory and tiering"),
        ("What must validation be independent of?", "regulatory_summaries", "PRA SS1/23 independent validation"),
        ("What triggers should be defined for re-validation?", "regulatory_summaries", "PRA SS1/23 ongoing monitoring"),
        ("Which letter replaced SR 11-7?", "regulatory_summaries", "SR 26-2 overview"),
        ("What does the SR 26-2 letter ask banks to document about scope?", "regulatory_summaries", "SR 26-2 model definition and scope"),
        ("What governance does SR 26-2 expect for model ownership?", "regulatory_summaries", "SR 26-2 governance expectations"),
        ("What did the Basel market-risk framework move to for internal models?", "regulatory_summaries", "Basel market-risk framework summary"),
        ("What must an audit trail show for a limit or model change?", "regulatory_summaries", "Audit trail expectations"),
        ("What should happen when automation influences a risk decision?", "regulatory_summaries", "Human oversight of automated decisions"),
        ("Who must be told about a failed price check, and how fast?", "escalation_matrix", "Data incidents"),
        ("What happened in the stale FX fixing incident?", "incident_logs", "INC-0001 Stale FX fixing used for DESK_FX revaluation"),
        ("Which incident involved a vendor tick on a cash position?", "incident_logs", "INC-0002 Bad equity tick on cash position"),
        ("Which incident had a limit typo?", "incident_logs", "INC-0003 Limit typo in configuration"),
        ("Which incident was about a duplicate trade?", "incident_logs", "INC-0006 Duplicate trade booked twice"),
    ]
    rows = []
    for q, doc, heading in questions:
        from riskdesk.rag.index import slug
        if doc == "incident_logs":
            num = int(heading.split()[0].split("-")[1])
            cid = f"incident_logs#{slug(f'INC-{num:04d} ' + heading.split(' ', 1)[1])}"
        else:
            cid = f"{doc}#{slug(heading)}"
        rows.append({"q": q, "chunk": cid})
    os.makedirs(os.path.dirname(RAG_QUESTIONS_PATH), exist_ok=True)
    with open(RAG_QUESTIONS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n")
    print("rag questions written:", len(rows))


if __name__ == "__main__":
    main()
